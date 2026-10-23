"""Bounded, read-only Ministry of Planning blacklist evidence lookup.

Matching is a candidate finder, not a certificate that a contractor is eligible.
In particular, an empty match result must never automatically become ``cleared``.
Uploaded reference text is inert data and is not interpreted as instructions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
import ipaddress
import re
import socket
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import getproxies, proxy_bypass

import httpx
from pypdf import PdfReader


OFFICIAL_HOSTS = frozenset({"mop.gov.iq", "www.mop.gov.iq", "blacklist.mop.gov.iq"})
OFFICIAL_NOTICE = (
    "توضح وزارة التخطيط أن المعلومات المنشورة عن الشركات والمكاتب للعرض فقط، "
    "ويجب الرجوع إلى دائرة العقود الحكومية للتأكد من سلامة الموقف القانوني. "
    "نتيجة البحث أو مراجعة المدقق هنا لا تمثل شهادة رسمية بالخلو من الإدراج."
)
OFFICIAL_SOURCES = [
    {"title": "منصة الاستعلام الرسمية عن القائمة السوداء والمتلكئة", "url": "https://blacklist.mop.gov.iq/"},
    {"title": "صفحة الوزارة الحالية وتنبيه الموقف القانوني", "url": "https://mop.gov.iq/القائمة-السوداء-2"},
    {"title": "فهرس القرارات والجلسات التاريخية؛ ليس قائمة كاملة محدثة", "url": "https://mop.gov.iq/القائمة-السوداء"},
]
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_CHARACTERS = 1_000_000
MAX_PDF_PAGES = 200
MAX_REDIRECTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_arabic(value: str) -> str:
    """Normalize common orthographic variants without fuzzy legal conclusions."""
    value = unicodedata.normalize("NFKC", value).lower()
    value = value.translate(str.maketrans({
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي",
        "ی": "ي", "ک": "ك", "ـ": "", "ؤ": "و", "ئ": "ي",
    }))
    value = "".join(c for c in value if unicodedata.category(c) != "Mn")
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def validate_official_url(url: str, *, resolve_dns: bool = True) -> str:
    """Permit only verified HTTPS Ministry hosts and public DNS destinations."""
    try:
        parts = urlsplit(url.strip())
        if (
            parts.scheme.lower() != "https"
            or parts.hostname not in OFFICIAL_HOSTS
            or parts.username is not None
            or parts.password is not None
            or parts.port not in (None, 443)
        ):
            raise ValueError
        host = parts.hostname
        if not host:
            raise ValueError
    except (TypeError, ValueError, AttributeError):
        raise ValueError("يُسمح فقط برابط HTTPS مباشر من موقع وزارة التخطيط mop.gov.iq أو منصتها الرسمية blacklist.mop.gov.iq.") from None
    if resolve_dns:
        try:
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise ValueError("تعذر التحقق من عنوان موقع وزارة التخطيط؛ أرفق نسخة رسمية من القائمة للمراجعة.") from None
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise ValueError("عنوان موقع المصدر غير مسموح للوصول الشبكي.")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def _validate_fetch_url(url: str) -> str:
    """Preserve the platform's trusted HTTPS proxy and its DNS routing.

    Proxy addresses are used only by HTTPX's normal trust_env configuration;
    they are never returned or logged. Exact Ministry-host restrictions still
    apply to every URL. A direct route, including a NO_PROXY bypass, additionally
    requires all locally resolved addresses to be public.
    """
    clean_url = validate_official_url(url, resolve_dns=False)
    host = urlsplit(clean_url).hostname
    proxies = getproxies()
    uses_proxy = bool(proxies.get("https") or proxies.get("all")) and not (
        proxy_bypass(host) or proxy_bypass(f"{host}:443")
    )
    return validate_official_url(clean_url, resolve_dns=not uses_proxy)


class _VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.fragments: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        elif tag in {"p", "br", "tr", "li", "div", "h1", "h2", "h3"}:
            self.fragments.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.fragments.append(data)


def _fetch_official_source(url: str) -> tuple[str, str, bool]:
    """Return visible text, final provenance URL, and whether it is a PDF."""
    current = _validate_fetch_url(url)
    with httpx.Client(timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=False, trust_env=True) as client:
        for redirect in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current, headers={"Accept": "application/pdf,text/html,text/plain", "User-Agent": "ContractAuditEvidence/1.0"}) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if redirect == MAX_REDIRECTS:
                        raise ValueError("تجاوز المصدر عدد التحويلات المسموح؛ أرفق نسخة القائمة الرسمية.")
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("أعاد موقع المصدر تحويلاً غير مكتمل.")
                    current = _validate_fetch_url(urljoin(current, location))
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length", "")
                if content_length.isdigit() and int(content_length) > MAX_SOURCE_BYTES:
                    raise ValueError("حجم مصدر القوائم يتجاوز 10 ميغابايت؛ أرفقه كوثيقة رسمية محلية.")
                chunks = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > MAX_SOURCE_BYTES:
                        raise ValueError("حجم مصدر القوائم يتجاوز 10 ميغابايت؛ أرفقه كوثيقة رسمية محلية.")
                    chunks.append(chunk)
                body = b"".join(chunks)
                media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if body.startswith(b"%PDF-") or media_type == "application/pdf":
                    try:
                        reader = PdfReader(BytesIO(body))
                        if len(reader.pages) > MAX_PDF_PAGES:
                            raise ValueError("يتجاوز المصدر 200 صفحة؛ أرفق الصفحات ذات الصلة للمراجعة.")
                        text = "\n\f\n".join((page.extract_text() or "") for page in reader.pages)
                    except ValueError:
                        raise
                    except Exception:
                        raise ValueError("تعذر استخراج نص القائمة الرسمية؛ قد تحتاج الوثيقة إلى التعرف الضوئي.") from None
                    return text[:MAX_SOURCE_CHARACTERS], current, True
                if media_type not in {"text/html", "text/plain", "application/xhtml+xml", ""}:
                    raise ValueError("نوع ملف المصدر غير مدعوم؛ استخدم PDF أو صفحة القائمة الرسمية.")
                text = body.decode("utf-8", errors="replace")
                if media_type in {"text/html", "application/xhtml+xml"} or "<html" in text[:1000].lower():
                    parser = _VisibleText()
                    parser.feed(text)
                    text = " ".join(parser.fragments)
                return text[:MAX_SOURCE_CHARACTERS], current, False
    raise ValueError("تعذر تحميل مصدر القوائم الرسمية.")


def check_blacklist(
    contractor: str,
    *,
    source_url: str | None = None,
    reference_text: str | None = None,
    reference_id: str | None = None,
) -> dict:
    """Find possible names in official evidence; human confirmation is mandatory.

    A supplied local document is never silently represented as a fresh live-site
    check. ``source_url`` is provenance only when local text is supplied; it is
    still constrained to Ministry hosts. The caller stores the original evidence.
    """
    contractor = str(contractor or "").strip()
    if len(contractor) > 300 or len(normalize_arabic(contractor)) < 4:
        raise ValueError("أدخل الاسم الكامل للشركة أو المقاول، بأربعة أحرف على الأقل، قبل فحص القائمة.")
    result = {
        "status": "pending",
        "checked_at": _now(),
        "source_url": None,
        "note": "",
        "evidence_document_id": reference_id,
        "matches": [],
        "human_confirmed": False,
        "source_notice": OFFICIAL_NOTICE,
        "official_sources": OFFICIAL_SOURCES,
    }
    if source_url:
        # Local evidence can be processed without network, but arbitrary URLs
        # must not be presented as Ministry provenance.
        result["source_url"] = validate_official_url(source_url, resolve_dns=False)
    remote_pdf = False
    if reference_text:
        source_text = str(reference_text)[:MAX_SOURCE_CHARACTERS]
        provenance = "الوثيقة المرفقة؛ لم يُتحقق آلياً من حداثتها أو اكتمالها"
    elif source_url:
        try:
            source_text, final_url, remote_pdf = _fetch_official_source(source_url)
            result["source_url"] = final_url
        except (httpx.HTTPError, ValueError) as exc:
            result["status"] = "unavailable"
            if isinstance(exc, ValueError):
                result["note"] = str(exc)
            else:
                result["note"] = "تعذر الوصول إلى مصدر وزارة التخطيط أو رفض الموقع الطلب. لا يمكن استنتاج سلامة الموقف؛ أرفق القائمة الرسمية للمراجعة."
            return result
        provenance = "النص المحمل من موقع وزارة التخطيط"
    else:
        result["status"] = "unavailable"
        result["note"] = "أرفق قائمة رسمية حديثة أو أدخل رابطها المباشر من موقع وزارة التخطيط لبدء الفحص."
        return result

    normalized_name = normalize_arabic(contractor)
    normalized_text = normalize_arabic(source_text)
    if len(normalized_text) < 30:
        result["status"] = "unavailable"
        result["note"] = "لا يحتوي المصدر على نص كافٍ للبحث؛ قد يكون ممسوحاً ضوئياً. يلزم فحص الوثيقة يدوياً أو إجراء التعرف الضوئي."
        return result
    pattern = re.compile(r"(?<!\w)" + re.escape(normalized_name) + r"(?!\w)")
    for found in pattern.finditer(normalized_text):
        result["matches"].append({
            "name": contractor,
            "excerpt": normalized_text[max(0, found.start() - 110):found.end() + 160],
            "confidence": "candidate",
        })
        if len(result["matches"]) >= 20:
            break
    if result["matches"]:
        result["status"] = "possible_match"
        result["note"] = f"ظهر تطابق اسمي محتمل في {provenance}. تحقق من الهوية ورقم الشركة والقرار وتاريخ رفع الإدراج قبل اعتماد النتيجة."
    elif not reference_text and not remote_pdf:
        result["status"] = "unavailable"
        result["note"] = "تم تحميل صفحة من الموقع، لكنها لا تثبت الاطلاع على كامل القوائم السوداء. عدم العثور على الاسم لا يثبت سلامة الموقف؛ أرفق ملف القائمة الرسمية وراجعها."
    else:
        result["status"] = "pending"
        result["note"] = f"لم يظهر تطابق نصي كامل في {provenance}. هذه نتيجة بحث أولية؛ اختلاف الكتابة أو نقص المصدر قد يحجب الاسم. يلزم تأكيد المدقق مع دليل رسمي قبل اعتماد سلامة الموقف."
    return result
