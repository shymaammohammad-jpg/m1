"""Automatic, bounded Ministry-source lookup with retained evidence snapshots.

This module reports search observations, never a certificate of legal eligibility.
Response bodies and uploaded files are inert evidence, not model instructions.
The existing human-reviewed blacklist workflow remains unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
import unicodedata
import uuid
from urllib.parse import urljoin, urlsplit

import httpx
from pypdf import PdfReader

from .blacklist import (
    MAX_PDF_PAGES, MAX_REDIRECTS, MAX_SOURCE_BYTES, MAX_SOURCE_CHARACTERS,
    OFFICIAL_NOTICE, OFFICIAL_SOURCES, _validate_fetch_url,
    normalize_arabic, validate_official_url,
)
from .storage import Store, now


CURRENT_SOURCES = tuple(OFFICIAL_SOURCES[:2])
MAX_LINKED_SOURCES = 4
MAX_MATCHES = 20
_GENERIC_WORDS = frozenset({
    "شركة", "الشركة", "شركه", "مكتب", "المكتب", "مؤسسة", "موسسة",
    "مؤسسه", "للتجارة", "تجارة", "العامة", "عامه", "المحدودة", "محدودة",
    "محدوده", "للمقاولات", "مقاولات", "العراقية", "عراقيه",
})


class _Cancelled(Exception):
    pass


class _SourceError(ValueError):
    pass


class _Page(HTMLParser):
    """Only visible text and ordinary links; scripts/forms are never executed."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[dict] = []
        self.hidden = 0
        self.anchor: dict | None = None

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"p", "br", "tr", "li", "div", "h1", "h2", "h3", "td", "th"}:
            self.parts.append("\n" if tag in {"tr", "p", "div", "br"} else " ")
        if tag == "a":
            href = dict(attrs).get("href", "")
            self.anchor = {"href": href, "text": ""}

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "template"}:
            self.hidden = max(0, self.hidden - 1)
        if tag == "a" and self.anchor is not None:
            self.links.append(self.anchor)
            self.anchor = None

    def handle_data(self, data):
        if self.hidden:
            return
        self.parts.append(data)
        if self.anchor is not None:
            self.anchor["text"] += data


def _new_client():
    return httpx.Client(timeout=httpx.Timeout(15.0, connect=8.0),
                        follow_redirects=False, trust_env=True)


def _check_cancelled(cancelled):
    if cancelled and cancelled():
        raise _Cancelled


def _fetch(client: httpx.Client, url: str, cancelled=None) -> tuple[bytes, str, str]:
    current = _validate_fetch_url(url)
    for redirect in range(MAX_REDIRECTS + 1):
        _check_cancelled(cancelled)
        with client.stream("GET", current, headers={
            "Accept": "application/pdf,text/html,text/plain",
            "User-Agent": "RaqibAutomaticAudit/2.0",
        }) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if redirect == MAX_REDIRECTS or not location:
                    raise _SourceError("تعذر اتباع تحويلات مصدر الوزارة ضمن الحد المسموح.")
                current = _validate_fetch_url(urljoin(current, location))
                continue
            response.raise_for_status()
            length = response.headers.get("content-length", "")
            if length.isdigit() and int(length) > MAX_SOURCE_BYTES:
                raise _SourceError("حجم المصدر الرسمي يتجاوز عشرة ميغابايت.")
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                _check_cancelled(cancelled)
                size += len(chunk)
                if size > MAX_SOURCE_BYTES:
                    raise _SourceError("حجم المصدر الرسمي يتجاوز عشرة ميغابايت.")
                chunks.append(chunk)
            body = b"".join(chunks)
            if not body:
                raise _SourceError("أعاد المصدر الرسمي ملفاً فارغاً.")
            media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            return body, current, media
    raise _SourceError("تعذر تحميل المصدر الرسمي.")


def _source_document(store: Store, case_id: str, body: bytes, url: str,
                     media: str, *, text: str, suffix: str, label: str,
                     page_count: int | None = 1, complete: bool = True,
                     source_document_id: str | None = None,
                     source_sha256: str | None = None) -> dict:
    document_id = uuid.uuid4().hex
    path = store.uploads / (document_id + suffix)
    path.write_bytes(body)
    document = {
        "id": document_id, "name": label, "original_name": label + suffix,
        "category": "blacklist", "size": len(body),
        "sha256": hashlib.sha256(body).hexdigest(), "page_count": page_count,
        "extraction_status": "text" if complete else "partial",
        "extracted_characters": len(text), "warnings": [] if complete else ["النص المستخرج غير مكتمل؛ لا يثبت عدم الإدراج."],
        "reference_year": None, "created_at": now(),
        "source_url": url, "fetched_at": now(), "snapshot_media_type": media,
        "automatic_blacklist_snapshot": True, "snapshot_complete": complete,
        "pagination": "physical" if suffix == ".pdf" else "logical",
        "_path": str(path), "_text": text,
    }
    if source_document_id:
        document.update(source_document_id=source_document_id,
                        derived_from_document_id=source_document_id,
                        source_sha256=source_sha256,
                        extraction_note="نص مرئي مشتق من لقطة HTML الأصلية المحفوظة، وليس استجابة مستقلة من الموقع.")
    try:
        store.add_documents([document], case_id)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return document


def _is_list_text(text: str) -> bool:
    normalized = normalize_arabic(text)
    heading = any(normalize_arabic(s) in normalized for s in (
        "القائمة السوداء", "القائمه السوداء", "الشركات المتلكئة", "الشركات المتلكيه",
        "blacklist", "black list", "debarred contractors",
    ))
    records = any(normalize_arabic(s) in normalized for s in (
        "اسم الشركة", "اسم الشركه", "اسم المقاول", "اسم المكتب", "رقم القرار",
        "company name", "contractor name", "decision number",
    ))
    return heading and records and len(normalized) >= 40


def _pdf_text(body: bytes, cancelled=None) -> tuple[list[str], int, bool, list[str]]:
    warnings = []
    try:
        reader = PdfReader(BytesIO(body), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return [], 0, False, ["المصدر الرسمي PDF محمي ولا يمكن قراءة نصه آلياً."]
        count = len(reader.pages)
        limit = min(count, MAX_PDF_PAGES)
        if count > limit:
            warnings.append("يتجاوز المصدر حد الصفحات المسموح؛ النص المقروء جزئي.")
        pages, total, missing = [], 0, False
        for index in range(limit):
            _check_cancelled(cancelled)
            text = reader.pages[index].extract_text() or ""
            available = MAX_SOURCE_CHARACTERS - total
            if len(text) > available:
                text = text[:max(0, available)]
                missing = True
            pages.append(text)
            total += len(text)
            if len(normalize_arabic(text)) < 20:
                missing = True
            if total >= MAX_SOURCE_CHARACTERS:
                missing = True
                break
        complete = bool(count) and count == len(pages) and not missing
        if not complete and not warnings:
            warnings.append("بعض صفحات المصدر غير مقروءة أو ممسوحة ضوئياً؛ لا يُستنتج منها عدم الإدراج.")
        return pages, count, complete, warnings
    except _Cancelled:
        raise
    except Exception:
        return [], 0, False, ["تعذر استخراج نص PDF الرسمي؛ الأصل محفوظ ولا يثبت غياب الاسم."]


def _relevant_links(page: _Page, url: str) -> list[str]:
    links = []
    for link in page.links:
        try:
            candidate = urljoin(url, link["href"])
            is_pdf = urlsplit(candidate).path.lower().endswith(".pdf")
        except ValueError:
            continue
        if not is_pdf:
            continue
        context = normalize_arabic(link["text"] + " " + candidate)
        if not any(normalize_arabic(s) in context for s in ("السوداء", "متلك", "قائمة", "قائمه", "blacklist", "black list", "debar")):
            continue
        try:
            candidate = validate_official_url(candidate, resolve_dns=False)
        except ValueError:
            continue
        if candidate not in links:
            links.append(candidate)
    return links[:MAX_LINKED_SOURCES]


def _verbatim_window(text: str, start: int, end: int, expected_normalized: str) -> str:
    """Map ordinary Arabic normalization offsets back to retained source text.

    Diacritics and Arabic presentation ligatures can change offsets. The mapping
    is accepted only if it reproduces the complete normalized page exactly.
    """
    characters, positions = [], []
    cache = {}
    for index, original in enumerate(text):
        if original not in cache:
            cache[original] = normalize_arabic(original)
        part = cache[original]
        if not part:
            if unicodedata.category(original) == "Mn" or original == "ـ":
                continue
            if characters and characters[-1] != " ":
                characters.append(" ")
                positions.append(index)
            continue
        for character in part:
            if character == " " and (not characters or characters[-1] == " "):
                continue
            characters.append(character)
            positions.append(index)
    if characters and characters[-1] == " ":
        characters.pop()
        positions.pop()
    if "".join(characters) == expected_normalized and end <= len(positions):
        return text[max(0, positions[start] - 100):min(len(text), positions[end - 1] + 241)].strip()
    # Unusual Unicode normalization cannot manufacture a quote. A short whole
    # page is still an exact quote; long unmappable pages stay explicitly uncited.
    return text.strip() if len(text) <= 10000 else ""


def _matching_pages(contractor: str, pages: list[str], document: dict,
                    source_url: str | None, *, live: bool) -> list[dict]:
    name = normalize_arabic(contractor)
    pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)")
    found = []
    for page, text in enumerate(pages, 1):
        normalized = normalize_arabic(text)
        # The normalized excerpt is explicitly a search aid, not a verbatim quote.
        # Preserve the actual source page as the citation text for independent checks.
        for match in pattern.finditer(normalized):
            found.append({
                "name": contractor, "document_id": document["id"], "page": page,
                "source_url": source_url, "live_source": live, "confidence": "candidate",
                "excerpt": normalized[max(0, match.start() - 100):match.end() + 180],
                "excerpt_normalized": True,
                "quote": _verbatim_window(text, match.start(), match.end(), normalized),
                "note": "تطابق اسمي محتمل؛ لا يحسم هوية الشركة أو استمرار القرار أو رفعه.",
            })
            if len(found) >= MAX_MATCHES:
                return found
    return found


def _analyse_live(body: bytes, url: str, media: str, store: Store, case_id: str,
                  contractor: str, cancelled=None) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = "وزارة التخطيط — مصدر القوائم " + stamp
    if body.startswith(b"%PDF-") or media == "application/pdf":
        pages, count, complete, warnings = _pdf_text(body, cancelled)
        joined = "\n\f\n".join(pages)
        document = _source_document(store, case_id, body, url, "application/pdf",
                                    text=joined, suffix=".pdf", label=label,
                                    page_count=count or None, complete=complete)
        return {"document": document, "original_document": document,
                "pages": pages, "complete": complete, "list_like": _is_list_text(joined),
                "warnings": warnings, "links": [],
                "matches": _matching_pages(contractor, pages, document, url, live=True)}
    if media not in {"text/html", "text/plain", "application/xhtml+xml", ""}:
        raise _SourceError("نوع استجابة المصدر الرسمي غير مدعوم.")
    decoded = body.decode("utf-8-sig", errors="replace")
    html = media in {"text/html", "application/xhtml+xml"} or bool(re.search(r"<html\b|<!doctype\s+html", decoded[:1000], re.I))
    if html:
        parser = _Page()
        parser.feed(decoded)
        full_text = "".join(parser.parts)
        text = full_text[:MAX_SOURCE_CHARACTERS]
        complete = len(full_text) <= MAX_SOURCE_CHARACTERS and "\ufffd" not in decoded
        # Exact HTML bytes are kept as plain text, so a click cannot execute site
        # scripts in the audit application's origin. The derived text has its own
        # evidence identity and a SHA-linked pointer to that original snapshot.
        original = _source_document(store, case_id, body, url, media or "text/html",
                                    text=decoded[:MAX_SOURCE_CHARACTERS], suffix=".txt",
                                    label=label + " — HTML الأصلي", complete=complete)
        document = _source_document(store, case_id, text.encode("utf-8"), url, "text/plain",
                                    text=text, suffix=".txt", label=label + " — النص المرئي",
                                    complete=complete, source_document_id=original["id"],
                                    source_sha256=original["sha256"])
        warnings = ["صفحة HTML لا تثبت استعراض جميع سجلات المنصة أو نتائجها المقسمة إلى صفحات."]
        if not complete:
            warnings.append("نص الصفحة جزئي أو يحتوي محارف غير مقروءة.")
        return {"document": document, "original_document": original,
                "pages": [text], "complete": False, "list_like": _is_list_text(text),
                "warnings": warnings, "links": _relevant_links(parser, url),
                "matches": _matching_pages(contractor, [text], document, url, live=True)}
    text = decoded[:MAX_SOURCE_CHARACTERS]
    complete = len(decoded) <= MAX_SOURCE_CHARACTERS and "\ufffd" not in decoded
    document = _source_document(store, case_id, body, url, "text/plain", text=text,
                                suffix=".txt", label=label, complete=complete)
    return {"document": document, "original_document": document,
            "pages": [text], "complete": complete, "list_like": _is_list_text(text),
            "warnings": [] if complete else ["النص الرسمي المقروء جزئي أو غير سليم الترميز."],
            "links": [], "matches": _matching_pages(contractor, [text], document, url, live=True)}


def _local_sources(contractor: str, store: Store, case_id: str) -> tuple[list[dict], list[dict], list[str]]:
    matches, searched, limitations = [], [], []
    documents = [*store.documents(), *store.documents(case_id)]
    for public in documents:
        if public.get("category") != "blacklist" or public.get("automatic_blacklist_snapshot"):
            continue
        document = store.document(public["id"])
        if not document:
            continue
        text = str(document.get("_text") or "")[:MAX_SOURCE_CHARACTERS]
        source_url = None
        try:
            if document.get("source_url"):
                source_url = validate_official_url(document["source_url"], resolve_dns=False)
        except ValueError:
            pass
        pages = re.split(r"\n\f\n|\n\[صفحة\s+\d+\]\n", text)
        if pages and not pages[0].strip():
            pages = pages[1:]
        matches += _matching_pages(contractor, pages or [text], document, source_url, live=False)
        searched.append({"source_url": source_url, "document_id": document["id"],
                         "source_kind": "uploaded", "status": "searched_local",
                         "complete": False, "live": False,
                         "note": "مرفق مصنف قائمة سوداء؛ لم تُثبت حداثته أو أصالته من الموقع في هذه العملية."})
        limitations.append("المرفق «" + str(document.get("name", "")) + "» مصدر محلي؛ لم يُتحقق من حداثته أو اكتماله عبر الموقع.")
        if len(matches) >= MAX_MATCHES:
            break
    return matches[:MAX_MATCHES], searched, limitations


def run_automatic_blacklist(contractor: str, store: Store, case_id: str, *, cancelled=None) -> dict:
    """Search official live evidence automatically and retain its provenance.

    ``not_found`` means only that the exact normalized name was absent from a
    complete, list-like official PDF read in this run. It never means ``cleared``.
    A name in a local attachment is explicitly not presented as a live lookup.
    """
    result = {"status": "unavailable", "note": "", "source_url": None,
              "checked_at": now(), "matches": [], "evidence_document_ids": [],
              "searched_sources": [], "limitations": [OFFICIAL_NOTICE],
              "human_confirmed": False, "source_notice": OFFICIAL_NOTICE}
    contractor = str(contractor or "").strip()
    normalized = normalize_arabic(contractor)
    words = normalized.split()
    if len(contractor) > 300 or len(normalized) < 4 or len(words) < 2 or not any(
            word not in _GENERIC_WORDS and any(char.isalpha() for char in word) for word in words):
        result.update(status="insufficient_identity", note="اسم الشركة غير كافٍ لبحث موثوق؛ لم يُستنتج أي موقف من القائمة السوداء.")
        return result
    queue = [source["url"] for source in CURRENT_SOURCES]
    seen, complete_lists, linked = set(), [], 0
    try:
        with _new_client() as client:
            while queue and len(seen) < len(CURRENT_SOURCES) + MAX_LINKED_SOURCES:
                _check_cancelled(cancelled)
                url = queue.pop(0)
                if url in seen:
                    continue
                seen.add(url)
                try:
                    body, final_url, media = _fetch(client, url, cancelled)
                    source = _analyse_live(body, final_url, media, store, case_id, contractor, cancelled)
                    document = source["document"]
                    result["evidence_document_ids"].append(document["id"])
                    result["searched_sources"].append({
                        "source_url": final_url, "requested_url": url,
                        "document_id": document["id"],
                        "original_document_id": source["original_document"]["id"],
                        "sha256": source["original_document"]["sha256"],
                        "fetched_at": source["original_document"]["fetched_at"],
                        "source_kind": "live", "live": True,
                        "status": "matched" if source["matches"] else "searched",
                        "complete": source["complete"], "list_like": source["list_like"],
                        "note": "نطاق البحث هو هذه النسخة المحفوظة؛ لم تُثبت شمولية القائمة الحالية أو شهادة الموقف القانوني.",
                    })
                    result["matches"] += source["matches"]
                    result["limitations"] += source["warnings"]
                    if (source["complete"] and source["list_like"] and
                            source["original_document"]["snapshot_media_type"] == "application/pdf"):
                        complete_lists.append(final_url)
                    for candidate in source["links"]:
                        if linked < MAX_LINKED_SOURCES and candidate not in seen and candidate not in queue:
                            queue.append(candidate)
                            linked += 1
                except (httpx.HTTPError, ValueError, OSError) as exc:
                    message = str(exc) if isinstance(exc, _SourceError) else "تعذر الوصول إلى المصدر الرسمي أو قراءة استجابته ضمن القيود المسموحة."
                    result["searched_sources"].append({"source_url": url, "source_kind": "live",
                                                        "status": "unavailable", "live": True,
                                                        "complete": False, "note": message})
                    result["limitations"].append(message)
    except _Cancelled:
        result["note"] = "أُوقف بحث القوائم السوداء قبل اكتماله؛ لم تُستنتج سلامة الموقف القانوني."
        result["limitations"].append("عملية البحث غير مكتملة بسبب الإيقاف.")
        return result
    local_matches, local_searched, local_limits = _local_sources(contractor, store, case_id)
    result["matches"] = (result["matches"] + local_matches)[:MAX_MATCHES]
    result["searched_sources"] += local_searched
    result["limitations"] += local_limits
    result["evidence_document_ids"] += [m["document_id"] for m in local_matches]
    result["evidence_document_ids"] = list(dict.fromkeys(result["evidence_document_ids"]))
    result["limitations"] = list(dict.fromkeys(result["limitations"]))
    if result["matches"]:
        result["status"] = "possible_match"
        live = next((match for match in result["matches"] if match["live_source"]), None)
        result["source_url"] = (live or result["matches"][0]).get("source_url")
        result["note"] = ("ظهر تطابق اسمي محتمل في مصدر رسمي جُلب في هذه العملية. " if live else
                           "ظهر تطابق اسمي محتمل في مرفق محلي، وليس نتيجة تحقق مباشر من الموقع. ")
        result["note"] += "لا يكفي الاسم وحده لتأكيد الهوية أو نفاذ الإدراج؛ تُراجع أرقام الشركة والقرار وتواريخ الرفع."
    elif complete_lists:
        result["status"] = "not_found"
        result["source_url"] = complete_lists[0]
        result["note"] = "لم يظهر الاسم المطابق نصياً في وثائق القوائم الرسمية التي قُرئ نصها كاملاً في هذه العملية. النتيجة تخص النسخ المشار إليها فقط؛ لا تثبت شمولها لكل القوائم الحالية أو سلامة الموقف القانوني."
    else:
        result["status"] = "unavailable"
        result["note"] = "لم يتوفر مصدر رسمي كامل صالح لنفي وجود الاسم؛ صفحة الدخول أو تعذر الاتصال أو النص الجزئي لا تثبت عدم الإدراج."
    return result
