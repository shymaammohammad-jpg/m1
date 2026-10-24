"""Deterministic provenance gates for AI-produced contract-audit data.

These functions verify source membership, quoted text and basic data formats.
An authentic quotation does not prove the model's legal interpretation: the
orchestrator must separately review that interpretation against its evidence.
Neither uploaded documents nor model output are executed here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from .ai_documents import normalize_quote, quote_exists
from .audit_engine import reference_matches

FACT_KEYS = frozenset({"title", "contract_number", "contractor", "entity", "contract_date",
                       "amount", "currency", "contract_type"})
CONCLUSIVE = frozenset({"pass", "fail", "not_applicable"})
STATUSES = CONCLUSIVE | {"uncertain"}
MIN_CONFIDENCE = .8
MAX_CITATIONS = 12


def validate_citation(cite: Any, lookup: dict, allowed_ids=None) -> tuple[dict | None, str]:
    """Accept only an actual indexed page and a sufficiently specific quotation."""
    if not isinstance(cite, dict):
        return None, "الاستشهاد ليس كائناً صالحاً"
    document_id = cite.get("document_id")
    if not isinstance(document_id, str) or not document_id or len(document_id) > 160:
        return None, "معرّف مستند الاستشهاد غير صالح"
    if allowed_ids is not None and document_id not in allowed_ids:
        return None, "مستند الاستشهاد خارج المصادر المسموحة لهذا الإجراء"
    page = cite.get("page")
    if isinstance(page, bool):
        return None, "رقم صفحة الاستشهاد غير صالح"
    if isinstance(page, str) and len(page) <= 10 and re.fullmatch(r"[0-9]+", normalize_quote(page)):
        page = int(normalize_quote(page))
    if not isinstance(page, int) or page < 1:
        return None, "رقم صفحة الاستشهاد غير صالح"
    source = lookup.get((document_id, page))
    if not isinstance(source, dict) or not isinstance(source.get("text"), str):
        return None, "صفحة الاستشهاد غير موجودة في النص المقروء فعلياً"
    quote = cite.get("quote")
    if not isinstance(quote, str) or len(quote) > 6000:
        return None, "نص الاقتباس غير صالح أو يتجاوز الحد المسموح"
    quote = quote.strip()
    if not quote_exists(quote, source["text"], min_length=12):
        return None, "الاقتباس قصير أو غير موجود في صفحة المصدر المحددة"
    result = {"document_id": document_id, "page": page, "quote": quote}
    name = source.get("document_name") or source.get("name")
    if isinstance(name, str) and name.strip():
        result["document_name"] = name.strip()[:500]
    return result, ""


def _bounded_contains(value: str, source: str, *, identifier=False) -> bool:
    needle, haystack = normalize_quote(value), normalize_quote(source)
    if not needle:
        return False
    boundary = r"[\w/\-]" if identifier else r"\w"
    return re.search(r"(?<!" + boundary + ")" + re.escape(needle) + r"(?!" + boundary + ")", haystack) is not None


def _decimal(value: str) -> Decimal | None:
    """Parse explicit decimal notation without rounding through a float."""
    text = normalize_quote(value).strip()
    if not re.fullmatch(r"[+-]?[0-9]+(?:[ ,][0-9]{3})*(?:\.[0-9]+)?", text):
        return None
    try:
        number = Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


_AMOUNT_TOKEN = re.compile(r"(?<![0-9A-Za-z.])[+-]?[0-9]+(?:[ ,][0-9]{3})*(?:\.[0-9]+)?(?![0-9.])")
_MONEY_CONTEXT = re.compile(r"دينار|دولار|يورو|مبلغ|قيم[ةته]|كلف[ةته]|تكلف[ةته]|تخميني|iqd|usd|eur|amount|cost|price|value|[$€]", re.I)


def _amount_supported(value: str, quotes: list[str]) -> str | None:
    wanted = _decimal(value)
    if wanted is None or wanted <= 0:
        return None
    for quote in quotes:
        normalized = normalize_quote(quote)
        for match in _AMOUNT_TOKEN.finditer(normalized):
            context = normalized[max(0, match.start() - 65):match.end() + 65]
            if _MONEY_CONTEXT.search(context) and _decimal(match.group()) == wanted:
                return format(wanted, "f")
    return None


_MONTHS = {
    1: ("كانون الثاني", "يناير"), 2: ("شباط", "فبراير"), 3: ("آذار", "اذار", "مارس"),
    4: ("نيسان", "أبريل", "ابريل"), 5: ("أيار", "ايار", "مايو"), 6: ("حزيران", "يونيو"),
    7: ("تموز", "يوليو"), 8: ("آب", "اب", "أغسطس", "اغسطس"), 9: ("أيلول", "ايلول", "سبتمبر"),
    10: ("تشرين الأول", "تشرين الاول", "أكتوبر", "اكتوبر"),
    11: ("تشرين الثاني", "نوفمبر"), 12: ("كانون الأول", "كانون الاول", "ديسمبر"),
}


def _dates_in(value: str) -> set[str]:
    normalized = normalize_quote(value)
    triples = []
    for match in re.finditer(r"(?<![0-9])([0-9]{4})\s*[-/.]\s*([0-9]{1,2})\s*[-/.]\s*([0-9]{1,2})(?![0-9])", normalized):
        triples.append(tuple(int(x) for x in match.groups()))
    for match in re.finditer(r"(?<![0-9])([0-9]{1,2})\s*[-/.]\s*([0-9]{1,2})\s*[-/.]\s*([0-9]{4})(?![0-9])", normalized):
        day, month, year = (int(x) for x in match.groups())
        triples.append((year, month, day))
    for month, names in _MONTHS.items():
        for name in {normalize_quote(n) for n in names}:
            pattern = r"(?<![0-9])([0-9]{1,2})\s+" + re.escape(name) + r"(?:\s+سنة|\s+عام)?\s+([0-9]{4})(?![0-9])"
            for match in re.finditer(pattern, normalized):
                triples.append((int(match[2]), month, int(match[1])))
    values = set()
    for year, month, day in triples:
        try:
            values.add(date(year, month, day).isoformat())
        except ValueError:
            pass
    return values


_CURRENCIES = {
    "IQD": ("iqd", "دينار عراقي", "الدينار العراقي", "د.ع"),
    "USD": ("usd", "دولار أمريكي", "الدولار الأمريكي", "us$"),
    "EUR": ("eur", "يورو", "€"),
}
_TYPE_TERMS = {
    "works": ("أشغال", "الأشغال", "أعمال إنشائية", "الاعمال الانشائية", "تشييد", "construction", "works"),
    "goods": ("تجهيز", "التجهيز", "توريد", "التوريد", "سلع", "بضائع", "goods", "supply"),
    "services": ("خدمات", "الخدمات", "services"),
    "consultancy": ("استشارية", "الاستشارية", "استشاري", "consultancy", "consulting"),
}


def validate_fact(key: str, value: Any, citations: Any, lookup: dict, case_ids: set) -> dict | None:
    """Return a source-supported value/citations pair, or no fact at all.

    A date may be normalized to ISO and an amount to decimal digits; every such
    conversion comes from an explicit source token, never a model calculation.
    """
    if not isinstance(key, str) or key not in FACT_KEYS or not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    limit = 120 if key == "contract_number" else 500
    if len(value) > limit or not isinstance(citations, list) or not 1 <= len(citations) <= MAX_CITATIONS:
        return None
    validated = []
    for cite in citations:
        result, _ = validate_citation(cite, lookup, case_ids)
        if result is None:
            return None
        validated.append(result)
    quotes = [cite["quote"] for cite in validated]
    if key == "amount":
        supported = _amount_supported(value, quotes)
        if supported is None:
            return None
        value = supported
    elif key == "contract_date":
        wanted = _dates_in(value)
        if len(wanted) != 1 or not any(wanted & _dates_in(quote) for quote in quotes):
            return None
        value = next(iter(wanted))
    elif key == "currency":
        code = value.upper()
        terms = _CURRENCIES.get(code)
        if terms is None:
            code = next((c for c, names in _CURRENCIES.items() if normalize_quote(value) in {normalize_quote(n) for n in names}), "")
            terms = _CURRENCIES.get(code)
        if not terms or not any(_bounded_contains(term, quote) for quote in quotes for term in terms):
            return None
        value = code
    elif key == "contract_type" and value.lower() in _TYPE_TERMS:
        if not any(_bounded_contains(term, quote) for quote in quotes for term in _TYPE_TERMS[value.lower()]):
            return None
        value = value.lower()
    else:
        if key in {"title", "contractor", "entity", "contract_type"} and sum(c.isalnum() for c in value) < 3:
            return None
        if not any(_bounded_contains(value, quote, identifier=key == "contract_number") for quote in quotes):
            return None
    return {"value": value, "citations": validated}


def validate_finding(raw: dict, check: dict, lookup: dict, case_ids: set,
                     reference_documents: list[dict], instruction_year: int | None,
                     *, corpus_complete: bool = True) -> dict:
    """Gate an AI decision against the canonical question and actual sources."""
    raw = raw if isinstance(raw, dict) else {}
    issues: list[str] = []
    status = raw.get("status")
    if not isinstance(status, str) or status not in STATUSES:
        issues.append("حالة نتيجة الذكاء الاصطناعي غير معتمدة")
        status = "uncertain"
    if raw.get("id") != check.get("id"):
        issues.append("معرّف نتيجة الذكاء الاصطناعي لا يطابق بند التدقيق المطلوب")
    if raw.get("step") is not None and raw.get("step") != check.get("step"):
        issues.append("مرحلة النتيجة لا تطابق بند التدقيق المطلوب")
    note = raw.get("note")
    if not isinstance(note, str) or not note.strip():
        issues.append("لم يقدّم النموذج تعليلاً لنتيجة الفحص")
        note = "لم تتوافر نتيجة آلية مسندة لهذا البند."
    else:
        note = note.strip()
        if len(note) > 12000:
            issues.append("تعليل النتيجة يتجاوز الحد المسموح")
            note = note[:12000]
    confidence = raw.get("confidence", 0)
    try:
        if isinstance(confidence, bool):
            raise ValueError
        confidence = float(confidence)
        if not math.isfinite(confidence):
            raise ValueError
        if not 0 <= confidence <= 1:
            issues.append("درجة الثقة المرسلة خارج الحدود المسموحة")
        confidence = min(1., max(0., confidence))
    except (ValueError, TypeError, OverflowError):
        confidence = 0.
        issues.append("درجة الثقة المرسلة غير صالحة")
    if status in CONCLUSIVE and confidence < MIN_CONFIDENCE:
        issues.append("الثقة التقديرية أقل من حد إصدار نتيجة حاسمة")

    catalog = {doc["id"]: doc for doc in reference_documents if isinstance(doc, dict) and isinstance(doc.get("id"), str)}
    validated: dict[str, list[dict]] = {"evidence": [], "references": []}
    for group, allowed in (("evidence", case_ids), ("references", set(catalog))):
        values = raw.get(group, [])
        if not isinstance(values, list) or len(values) > MAX_CITATIONS:
            issues.append("قائمة استشهادات " + group + " غير صالحة")
            continue
        seen = set()
        for cite in values:
            result, reason = validate_citation(cite, lookup, allowed)
            if result is None:
                issues.append(reason)
                continue
            if group == "references":
                reference = catalog[result["document_id"]]
                if (check.get("id") == "instructions_basis" and instruction_year not in {2014, 2025}) or not reference_matches(check, reference, instruction_year):
                    issues.append("تصنيف المرجع أو سنة التعليمات لا يطابقان بند التدقيق")
                    continue
                if reference.get("name"):
                    result["document_name"] = str(reference["name"])[:500]
            marker = (result["document_id"], result["page"], normalize_quote(result["quote"]))
            if marker not in seen:
                validated[group].append(result)
                seen.add(marker)
    if status in CONCLUSIVE:
        if not validated["evidence"]:
            issues.append("لا يوجد دليل مقروء صالح من مستندات العقد يسند النتيجة")
        if not validated["references"]:
            issues.append("لا يوجد سند مرجعي مقروء صالح للنتيجة")
    if not corpus_complete and status in {"pass", "not_applicable"}:
        issues.append("قراءة ملف العقد غير مكتملة؛ لا يصح الجزم بالاستيفاء أو عدم الانطباق")
    if issues:
        status = "uncertain"
    missing = raw.get("missing_documents", [])
    missing = [item.strip()[:500] for item in missing[:50] if isinstance(item, str) and item.strip()] if isinstance(missing, list) else []
    return {"id": check.get("id", ""), "step": check.get("step", ""), "title": check.get("title", ""),
            "status": status, "note": note, "confidence": confidence,
            "evidence": validated["evidence"], "references": validated["references"],
            "missing_documents": list(dict.fromkeys(missing)),
            "validation_issues": list(dict.fromkeys(issues))}
