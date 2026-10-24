"""Evidence-linked automatic reports using the supplied human report's structure.

This renderer does not run a model or promote an uncertain result to a finding.
The automation service validates citations before passing its completed run here.
Unlike the manual report endpoint, an automatic report can describe unresolved
questions without requiring a person to complete the nine audit steps first.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import html
import json
import re
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .reports import (
    SECTIONS, TABLES, _font_css, _render_quick_form, _render_table, _section_for,
    render_pdf,
)


FINDING_LABELS = {
    "pass": "مستوفٍ بحسب الأدلة المفحوصة",
    "fail": "ملاحظة تدقيقية مسندة",
    "not_applicable": "غير منطبق مع بيان السبب",
    "uncertain": "تعذّر الحسم من الأدلة المتاحة",
}
STAGE_LABELS = {
    "pending": "بانتظار التنفيذ", "queued": "بانتظار التنفيذ",
    "running": "قيد التنفيذ", "completed": "اكتملت المعالجة",
    "warning": "أُنجزت مع نقص أو تحفظ", "failed": "تعذرت المعالجة",
    "cancelled": "أُوقف التنفيذ", "interrupted": "انقطع التنفيذ",
}
BLACKLIST_LABELS = {
    "cleared": "لم يظهر تطابق في المصدر المفحوص ضمن حدود التغطية المسجلة",
    "confirmed_match": "ظهرت قرينة تطابق في المصدر الرسمي تستلزم تحديد الموقف القانوني",
    "possible_match": "ظهر تطابق محتمل يحتاج إلى حسم",
    "unavailable": "تعذر التحقق من المصدر الرسمي",
    "pending": "لم تكتمل نتيجة التحقق",
    "uncertain": "تعذر حسم الموقف من الأدلة المتاحة",
    "not_found": "لم يظهر الاسم في القوائم الرسمية المقروءة ضمن نطاق البحث؛ لا يمثل ذلك شهادة خلو",
    "insufficient_identity": "لم تثبت هوية المتعاقد بما يكفي للاستعلام",
}


def _escape(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        value = "نعم" if value else "لا"
    elif isinstance(value, (list, dict)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return html.escape(str(value), quote=True)


def _paragraph(value: Any) -> str:
    return _escape(value).replace("\n", "<br>")


def _as_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _date(value: Any) -> str:
    if not value:
        return "—"
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(ZoneInfo("Asia/Baghdad"))
        return _escape(parsed.strftime("%Y/%m/%d"))
    except (ValueError, TypeError):
        return _escape(text)


def _page(value: Any, document: dict) -> tuple[str, int | None]:
    """Accept a bounded page/range; model output never becomes a URL fragment."""
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d+)(?:\s*[-–]\s*(\d+))?", text)
    if not match:
        return "صفحة غير مثبتة", None
    start, end = int(match[1]), int(match[2] or match[1])
    maximum = document.get("page_count")
    if maximum is None:
        return "عدد صفحات المستند غير مثبت", None
    try:
        if start < 1 or end < start or (maximum is not None and end > int(maximum)):
            return "صفحة خارج حدود المستند", None
    except (TypeError, ValueError, OverflowError):
        return "حدود صفحات المستند غير مثبتة", None
    return (str(start) if start == end else f"{start}–{end}"), start


def _source(citation: dict, documents: dict[str, dict]) -> str:
    document_id = str(citation.get("document_id") or "")
    document = documents.get(document_id)
    if not document:
        return '<span class="unresolved-source">مستند غير متاح ضمن ملف التدقيق أو المراجع</span>'
    name = document.get("name") or document.get("original_name") or document_id
    label, start = _page(citation.get("page"), document)
    if start is None:
        return f'{_escape(name)}؛ <span class="unresolved-source">{label}</span>'
    pagination = str(document.get("pagination") or "")
    target = f"/api/documents/{quote(document_id, safe='')}/file"
    if pagination != "logical":
        target += f"#page={start}"
    page_label = "وحدة نصية" if pagination == "logical" else "ص"
    return f'<a href="{html.escape(target, quote=True)}">{_escape(name)}</a>، {page_label} {_escape(label)}'


def _citation_list(value: Any, documents: dict[str, dict], *, empty: str) -> str:
    citations = [item for item in _as_list(value) if isinstance(item, dict)]
    if not citations:
        return f'<p class="unresolved-source">{_escape(empty)}</p>'
    rows = []
    for citation in citations:
        source = _source(citation, documents)
        quote_text = citation.get("quote")
        excerpt = f'<blockquote dir="auto">{_paragraph(quote_text)}</blockquote>' if quote_text else '<p class="unresolved-source">لم يثبت نص اقتباس لهذا الاستشهاد.</p>'
        rows.append(f'<li>{source}{excerpt}</li>')
    return '<ol class="citations">' + "".join(rows) + '</ol>'


def _description(value: Any) -> str:
    if not isinstance(value, dict):
        return str(value or "")
    pieces = [str(value[key]) for key in ("title", "description", "note", "reason", "field", "document", "name")
              if value.get(key)]
    if value.get("expected") is not None:
        pieces.append("المتوقع: " + str(value["expected"]))
    if value.get("actual") is not None:
        pieces.append("الوارد: " + str(value["actual"]))
    return " — ".join(pieces) if pieces else json.dumps(value, ensure_ascii=False, default=str)


def _items(value: Any, empty: str) -> str:
    values = _as_list(value)
    if not values:
        return f'<p class="unresolved-source">{_escape(empty)}</p>'
    return '<ul>' + "".join(f'<li>{_paragraph(_description(item))}</li>' for item in values) + '</ul>'


def _finding(item: dict, documents: dict[str, dict], number: int) -> str:
    status = item.get("status") if item.get("status") in FINDING_LABELS else "uncertain"
    issues = _as_list(item.get("validation_issues"))
    issue_html = ""
    if issues:
        issue_html = '<div class="validation"><b>تحفظات التحقق:</b>' + _items(issues, "") + '</div>'
    review = _as_dict(item.get("review"))
    review_text = review.get("note") or review.get("reason")
    if review_text:
        issue_html += f'<p class="citation">مراجعة النتيجة: {_paragraph(review_text)}</p>'
    return f'''<article class="finding status-{status}">
      <h4>{number} ـ {_escape(item.get('title') or item.get('id'))}</h4>
      <p class="finding-status">{FINDING_LABELS[status]}</p>
      <p>{_paragraph(item.get('note') or 'لم ترد نتيجة مسندة لهذا البند.')}</p>
      {issue_html}
      <div class="citation-group"><b>أدلة العقد والأوليات:</b>{_citation_list(item.get('evidence'), documents, empty='لم يثبت استشهاد من مستندات العقد لهذا البند.')}</div>
      <div class="citation-group"><b>السند المرجعي:</b>{_citation_list(item.get('references'), documents, empty='لم يثبت استشهاد مرجعي لهذا البند.')}</div>
    </article>'''


def _renderable_finding(item: dict, documents: dict[str, dict]) -> dict:
    """Do not label a result supported if even its citation address is invalid.

    Semantic quote verification remains the automation service's job. This
    second structural check protects callers that omit its validated payload.
    """
    item = dict(item)
    status = item.get("status")
    issues = list(_as_list(item.get("validation_issues")))
    if status in {"pass", "fail"}:
        for key, label in (("evidence", "دليل العقد"), ("references", "السند المرجعي")):
            citations = _as_list(item.get(key))
            valid = False
            for citation in citations:
                if not isinstance(citation, dict):
                    continue
                document = documents.get(str(citation.get("document_id") or ""))
                text = citation.get("quote")
                if document and _page(citation.get("page"), document)[1] is not None and isinstance(text, str) and len(text.strip()) >= 12:
                    valid = True
            if not valid:
                issues.append(f"لم يثبت عنوان صفحة واقتباس صالحان لـ{label} في بيانات التقرير.")
    if status == "not_applicable" and not str(item.get("note") or "").strip():
        issues.append("لم يثبت سبب عدم الانطباق.")
    if issues and status in {"pass", "fail", "not_applicable"}:
        item["status"] = "uncertain"
    item["validation_issues"] = issues
    return item


def render_ai_report(case: dict[str, Any], references: list[dict[str, Any]]) -> str:
    """Render an automated audit, including explicit unresolved results.

    The API owns execution/staleness gating. No manual readiness gate, official
    signature, successful default finding, or human name is created here.
    """
    automation = _as_dict(case.get("automation"))
    job = _as_dict(automation.get("job")) or automation
    contract_documents = [item for item in _as_list(case.get("documents")) if isinstance(item, dict)]
    current_blacklist = _as_dict(automation.get("blacklist"))
    snapshot_ids = set(_as_list(current_blacklist.get("evidence_document_ids")))
    snapshot_ids.update(source.get("original_document_id") for source in _as_list(current_blacklist.get("searched_sources")) if isinstance(source, dict))
    contract_documents = [d for d in contract_documents if not d.get("automatic_blacklist_snapshot") or d.get("id") in snapshot_ids]
    reference_documents = [item for item in _as_list(references) if isinstance(item, dict)]
    documents = {str(item["id"]): item for item in [*reference_documents, *contract_documents] if item.get("id")}
    findings = [_renderable_finding(item, documents) for item in _as_list(automation.get("findings")) if isinstance(item, dict)]
    facts = _as_dict(automation.get("facts"))

    def fact(key: str) -> Any:
        return _as_dict(facts.get(key)).get("value")

    quick = dict(_as_dict(automation.get("quick_form")))
    # An automatic run cannot sign on behalf of a person, including a name
    # carried over from an earlier manual review of the same contract file.
    for key in ("auditor", "auditor_name", "auditor_role", "team_lead", "approval_date"):
        quick.pop(key, None)
    report_tables = _as_dict(automation.get("report_tables"))
    grouped: dict[str, list[dict]] = {key: [] for key, _, _ in SECTIONS}
    for item in findings:
        grouped[_section_for(item)].append(item)
    blacklist = _as_dict(automation.get("blacklist"))
    counts = Counter(item.get("status") if item.get("status") in FINDING_LABELS else "uncertain" for item in findings)
    unknown_count = counts["uncertain"]
    adverse_count = counts["fail"]
    report_title = "تقرير التدقيق الآلي للعقد"
    state = STAGE_LABELS.get(str(job.get("status") or "pending"), "حالة تنفيذ غير محددة")
    if automation.get("stale"):
        state = "نتيجة سابقة؛ تغيرت المدخلات ويلزم إعادة التشغيل"
    summary = automation.get("summary") or "لم يرد ملخص آلي مسند؛ تُراجع النتائج التفصيلية وحدود التغطية أدناه."
    policy = _as_dict(automation.get("instruction_policy"))
    subject = fact("title") or "لم يثبت موضوع العقد من المستندات"
    entity = fact("entity") or "الجهة المتعاقدة غير مثبتة"
    finished = job.get("finished_at") or job.get("started_at")
    stages = []
    for index, stage in enumerate(_as_list(job.get("stages")), start=1):
        if not isinstance(stage, dict):
            continue
        stage_status = STAGE_LABELS.get(str(stage.get("status") or "pending"), "حالة غير مثبتة")
        stages.append(f'<tr><td>{index}</td><td>{_escape(stage.get("title") or stage.get("id"))}</td><td>{_escape(stage_status)}</td><td>{_paragraph(stage.get("message"))}</td></tr>')
    stages_html = '<table><thead><tr><th>ت</th><th>خطوة التدقيق</th><th>حالة المعالجة</th><th>النتيجة / التحفظ</th></tr></thead><tbody>' + ("".join(stages) or '<tr><td colspan="4">لم يتوفر سجل مراحل لهذا التشغيل.</td></tr>') + '</tbody></table>'

    sections = []
    for key, letter, title in SECTIONS:
        content = "".join(_finding(item, documents, number) for number, item in enumerate(grouped[key], start=1))
        for table_id, (owner, _, _) in TABLES.items():
            if owner == key:
                content += _render_table(table_id, report_tables.get(table_id))
        if key == "blacklist":
            status = BLACKLIST_LABELS.get(str(blacklist.get("status") or "pending"), BLACKLIST_LABELS["uncertain"])
            content += f'''<div class="blacklist-result"><p><b>نتيجة الفحص الآلي للقائمة:</b> {_escape(status)}.</p>
            <p>{_paragraph(blacklist.get('note') or 'لم تتوفر نتيجة مسندة لمراجعة المصدر الرسمي.')}</p>
            <p class="citation">وقت الفحص: {_date(blacklist.get('checked_at'))}؛ رابط المصدر: <span dir="ltr">{_escape(blacklist.get('source_url'))}</span>.</p>
            <p class="citation">عدم العثور في نص جزئي أو تعذر الاتصال لا يثبت عدم الإدراج. يظل تحديد الموقف القانوني النهائي مرتبطًا بالمصدر الرسمي.</p></div>'''
            matches = [m for m in _as_list(blacklist.get("matches")) if isinstance(m, dict)]
            if matches:
                content += '<h4>القرائن الاسمية من المصدر المفحوص</h4>' + _citation_list(matches, documents, empty="لم يثبت اقتباس لتطابق الاسم")
        if not content:
            content = '<p class="unresolved-source">لم تتوفر نتيجة أو بيانات مسندة لهذا القسم؛ لا يعد ذلك إثبات استيفاء.</p>'
        sections.append(f'<section class="observation-section"><h3>{letter} ـ {_escape(title)}:</h3>{content}</section>')

    fact_rows = []
    labels = {
        "title": "موضوع العقد", "contract_number": "رقم العقد", "contractor": "المتعاقد",
        "entity": "الجهة المتعاقدة", "contract_date": "تاريخ العقد", "amount": "مبلغ العقد",
        "currency": "العملة", "duration": "مدة التنفيذ", "estimated_cost": "الكلفة التخمينية",
    }
    for key, label in labels.items():
        item = _as_dict(facts.get(key))
        if not item and fact(key) in (None, ""):
            continue
        citations = item.get("citations") or item.get("evidence")
        fact_rows.append(f'<tr><th>{_escape(label)}</th><td>{_paragraph(fact(key))}</td><td>{_citation_list(citations, documents, empty="لم يثبت اقتباس لهذا الحقل.")}</td></tr>')
    facts_html = '<table class="fact-table"><thead><tr><th>الحقل</th><th>القيمة المستخرجة</th><th>المصدر والاقتباس</th></tr></thead><tbody>' + ("".join(fact_rows) or '<tr><td colspan="3">لم تثبت حقول مستخرجة مسندة لهذا التشغيل.</td></tr>') + '</tbody></table>'

    coverage_rows = []
    for row in _as_list(automation.get("coverage")):
        if not isinstance(row, dict):
            continue
        read_pages = row.get("read_pages")
        if isinstance(read_pages, list):
            read_pages = len(read_pages)
        completeness = "مكتملة بحسب سجل الاستخراج" if row.get("complete") is True else "جزئية أو غير مثبتة"
        coverage_rows.append(f'<tr><td>{_escape(row.get("name") or row.get("document_id"))}</td><td>{_escape(row.get("page_count"))}</td><td>{_escape(read_pages)}</td><td>{completeness}</td><td>{_items(row.get("warnings"), "—")}</td></tr>')
    coverage_html = '<table><thead><tr><th>المستند</th><th>الصفحات</th><th>الصفحات المقروءة</th><th>التغطية</th><th>ملاحظات القراءة</th></tr></thead><tbody>' + ("".join(coverage_rows) or '<tr><td colspan="5">لم تتوفر معلومات تثبت اكتمال قراءة المستندات.</td></tr>') + '</tbody></table>'
    source_rows = []
    for index, document in enumerate([*contract_documents, *reference_documents], start=1):
        source_rows.append(f'<tr><td>{index}</td><td>{_source({"document_id":document.get("id"),"page":1}, documents)}</td><td>{_escape(document.get("category"))}</td><td>{_escape(document.get("page_count"))}</td><td class="hash" dir="ltr">{_escape(document.get("sha256"))}</td></tr>')
    source_html = '<table><thead><tr><th>ت</th><th>المستند / المرجع</th><th>التصنيف</th><th>الصفحات</th><th>SHA-256</th></tr></thead><tbody>' + ("".join(source_rows) or '<tr><td colspan="5">لم تربط مستندات بهذا التقرير.</td></tr>') + '</tbody></table>'
    missing = automation.get("missing_documents")
    conflicts = automation.get("conflicts") or automation.get("contradictions")
    quick_html = _render_quick_form(quick, reference_documents)
    calculations = [item for item in _as_list(automation.get("calculations")) if isinstance(item, dict)]
    calc_rows = []
    calc_labels = {"calculated": "احتساب مشتق", "match": "مطابقة حسابية", "mismatch": "اختلاف حسابي", "unavailable": "تعذر الاحتساب"}
    table_evidence = _as_dict(automation.get("table_evidence"))
    for item in calculations:
        proofs = _as_dict(table_evidence.get(str(item.get("source_row_id") or "")))
        citations, seen = [], set()
        for value in proofs.values():
            for citation in _as_list(value):
                if not isinstance(citation, dict):
                    continue
                key = (citation.get("document_id"), str(citation.get("page")), citation.get("quote"))
                if key not in seen:
                    citations.append(citation)
                    seen.add(key)
        calc_rows.append(f'<tr><td>{_escape(item.get("table_id"))} / {_escape(item.get("row"))}</td><td>{_paragraph(item.get("formula"))}</td><td>{_escape(item.get("actual"))}</td><td>{_escape(item.get("expected"))}</td><td>{_escape(calc_labels.get(item.get("status"), "غير محسوم"))}<br>{_paragraph(item.get("note"))}</td></tr>')
        if citations:
            calc_rows.append('<tr><td colspan="5">' + _citation_list(citations, documents, empty="لم يثبت دليل") + '</td></tr>')
    arithmetic_html = ''
    if calc_rows:
        arithmetic_html = '<section class="appendix"><h2>مرفق ٤ ـ التحقق الحسابي</h2><p>حُسبت الفروقات والنسب برمجيًا باستخدام أرقام عشرية دقيقة. القيم المصدرية لا تُستبدل عند الاختلاف. المقارنة الحسابية لا تثبت وحدها مخالفة قانونية، وتُقرأ مع وحدة المبلغ وسنده. يبين كل احتساب صيغته وأصوله.</p><table><thead><tr><th>الجدول / الصف</th><th>الصيغة</th><th>المثبت في المصدر</th><th>المحتسب</th><th>النتيجة</th></tr></thead><tbody>' + ''.join(calc_rows) + '</tbody></table></section>'
    warning = '<p class="run-warning">هذا التشغيل غير مكتمل؛ لا يمثل تقرير تدقيق منجزًا.</p>' if job.get("status") != "completed" else ""
    stale = '<p class="run-warning">تغيرت بيانات العقد أو مستنداته بعد التشغيل. هذا التقرير تاريخي ويجب إعادة التدقيق على المدخلات الحالية.</p>' if automation.get("stale") else ""
    return f'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'">
<title>{report_title} ـ {_escape(subject)}</title><style>{_font_css()}
*{{box-sizing:border-box}}html{{background:#e9edf0}}body{{margin:0;color:#111;font-family:AuditNaskh,'Noto Naskh Arabic',serif;font-size:13pt;line-height:1.65;direction:rtl}}.toolbar{{background:#153f43;color:white;padding:14px 24px;font:14px/1.7 Arial,sans-serif}}.toolbar strong{{display:block}}.paper{{max-width:210mm;margin:22px auto;background:white;padding:24mm 18mm 24mm 20mm;box-shadow:0 4px 20px #0002}}h1,h2,h3,h4,p{{margin:0 0 8px}}h1{{font-size:17pt;text-align:center}}h2{{font-size:16pt;margin-top:20px;text-decoration:underline;text-underline-offset:5px}}h3{{font-size:14pt;margin-top:15px}}h4{{font-size:13pt}}.letterhead{{display:flex;justify-content:space-between;gap:18px;margin-bottom:15px}}.letterhead p{{margin:0}}.metadata{{font-size:11pt;min-width:38%;overflow-wrap:anywhere}}.state{{text-align:center;border:1px solid #555;padding:6px;margin-bottom:16px;font-size:12pt}}.recipient{{text-align:center;font-size:15pt;margin-top:14px}}.subject{{margin:12px 0 20px;text-decoration:underline;text-underline-offset:5px}}.summary-note{{border-right:3px solid #536a6a;padding:7px 11px;background:#f5f7f7}}.body-text,.finding>p{{text-align:justify}}table{{border-collapse:collapse;width:100%;font-size:11pt;line-height:1.5;margin:9px 0 16px}}th,td{{border:1px solid #444;padding:5px 6px;text-align:center;vertical-align:middle;overflow-wrap:anywhere}}th{{background:#f4f4f4;font-weight:700}}thead{{display:table-header-group}}tr{{break-inside:avoid}}.finding{{padding-bottom:9px;margin-bottom:11px;border-bottom:1px solid #ddd}}.finding-status{{font-size:11pt;font-weight:700}}.citation-group,.citation{{font-size:10.5pt;line-height:1.65}}.citations{{margin:5px 0 9px;padding-right:23px}}.citations li{{margin:5px 0;break-inside:avoid}}blockquote{{margin:4px 0;padding:3px 9px;border-right:2px solid #bbb;text-align:justify;font-size:10.5pt;white-space:normal;overflow-wrap:anywhere}}.unresolved-source{{color:#555;font-size:11pt}}.validation,.run-warning{{border:1px dashed #666;padding:7px 10px;font-size:11pt;margin:8px 0}}.validation ul{{margin:3px 0}}.table-title{{font-size:12pt;text-align:center;font-weight:700;margin:10px 0 3px}}.hash{{font:6pt monospace;word-break:break-all}}a{{color:inherit;overflow-wrap:anywhere}}.appendix{{break-before:page}}.appendix h2{{margin-top:0}}.approval-note,.official-notice,.quick-notice{{font-size:10.5pt;border-top:1px solid #777;padding-top:7px;margin-top:15px}}.quick-table th{{text-align:right}}.quick-table td{{text-align:right}}.quick-indicator{{font-size:10pt;font-weight:400;line-height:1.5}}.quick-page{{white-space:nowrap;text-align:center!important}}.fact-table th{{width:18%}}.fact-table td:nth-child(2){{width:27%}}.quick-section h3{{break-after:avoid}}
@page{{size:A4 portrait;margin:23mm 18mm 20mm 20mm;@bottom-center{{content:'(' counter(pages) ' - ' counter(page) ')';font-family:AuditNaskh,serif;font-size:10pt;direction:rtl}}}}
@media print{{html,body{{background:white}}.toolbar{{display:none}}.paper{{max-width:none;margin:0;padding:0;box-shadow:none}}h2,h3,h4,.table-title{{break-after:avoid}}a{{color:#111}}}}
</style></head><body><div class="toolbar"><strong>{report_title}</strong>أُنشئ من تشغيل التدقيق الآلي مع إظهار الأدلة والنواقص؛ لا يحمل توقيعًا أو ختمًا رسميًا.</div>
<main class="paper"><header class="letterhead"><div><p>جمهورية العراق</p><p><b>{_escape(entity)}</b></p><p>رقيب — تدقيق العقود الحكومية</p></div><div class="metadata"><p>رقم التشغيل الآلي: <span dir="ltr">{_escape(job.get('id'))}</span></p><p>تاريخ التقرير: {_date(finished)}</p><p>رقم ملف العقد: <span dir="ltr">{_escape(case.get('id'))}</span></p></div></header>
<div class="state">{report_title} — {_escape(state)}</div>{warning}{stale}
<p class="recipient">إلى / {_escape(entity)}</p><h1 class="subject">م / تدقيق {_escape(subject)}</h1>
<p>بعد التحية:</p><p class="body-text">نفّذ نظام رقيب فحصًا آليًا لملف العقد رقم ({_escape(fact('contract_number'))}) الخاص بـ ({_escape(subject)})، مع المتعاقد ({_escape(fact('contractor'))})، وبمبلغ مستخرج قدره ({_escape(fact('amount'))}) {_escape(fact('currency'))}. يعرض التقرير نتائج التشغيل والأدلة المرتبطة بها وما تعذر حسمه، وفق المدخلات المتاحة لهذا التشغيل.</p>
<p class="body-text">لدينا بشأن ذلك الإيضاحات والملاحظات الآتية:</p>
<section><h2>١ ـ الإيضاحات:</h2><p class="summary-note">{_paragraph(summary)}</p>
<p>أ ـ نطاق المعالجة: {len(contract_documents)} مستندًا من العقد وأولياته، و{len(reference_documents)} مرجعًا محفوظًا. لا يثبت عدد الملفات اكتمال الأوليات؛ يبين ملحق التغطية الصفحات التي أمكن قراءتها والتحفظات.</p>
<p>ب ـ نتائج البنود: مستوفٍ بحسب الأدلة ({counts['pass']})؛ ملاحظات تدقيقية ({adverse_count})؛ غير منطبق ({counts['not_applicable']})؛ غير محسوم ({unknown_count}). تُقرأ النتيجة مع استشهاداتها، ولا تمثل هذه الأعداد نسبة ضمان لدقة التدقيق.</p>
<table><tbody><tr><th>تاريخ العقد</th><td>{_date(fact('contract_date'))}</td><th>التعليمات المختارة</th><td>{_escape(policy.get('instruction_year'))}</td></tr><tr><th>المزود</th><td>{_escape(job.get('provider'))}</td><th>النموذج</th><td><span dir="ltr">{_escape(job.get('model'))}</span></td></tr></tbody></table>
<p class="citation">{_paragraph(policy.get('year_warning') or 'يراجع نطاق تطبيق التعليمات وتواريخ نفاذها والاستثناءات في نتائج الفحص المرجعي.')}</p>
{_render_table('award_recommendations', report_tables.get('award_recommendations'))}
<h3>النواقص والوثائق المطلوبة</h3>{_items(missing, 'لم تسجل قائمة مستقلة للوثائق الناقصة؛ لا يعني ذلك اكتمال الملف.')}
<h3>التعارضات التي ظهرت في المستندات</h3>{_items(conflicts, 'لم تسجل تعارضات مثبتة في المخرجات المتاحة؛ تبقى حدود القراءة سارية.')}
</section><section><h2>٢ ـ الملاحظات:</h2>{''.join(sections)}</section>
<p class="body-text">للاطلاع واتخاذ الإجراءات اللازمة لمعالجة الملاحظات واستكمال النواقص المسجلة، وفق صلاحيات الجهة المختصة، مع التقدير.</p>
<p class="approval-note">أعد نظام رقيب هذا التقرير آليًا دون نقل توقيع أو ختم أو اسم مسؤول من الحالة النموذجية. اكتمال التشغيل يعني اكتمال المعالجة المسجلة، ولا يمثل اعتمادًا رسميًا أو حسمًا لما وُسم غير محسوم. يعتمد الإجراء النهائي من الجهة المخولة.</p>
<section class="appendix"><h2>مرفق ١ ـ استمارة الفحص السريع</h2><p>أُدرجت القيم التي أنتجها التشغيل. الخانات غير المثبتة تبقى فارغة، ولا تُنسب المراجعة أو الموافقة إلى شخص افتراضي.</p>{quick_html}</section>
<section class="appendix"><h2>مرفق ٢ ـ فهرس الأدلة والمراجع</h2>{source_html}<h3>الحقول المستخرجة واقتباساتها</h3>{facts_html}</section>
<section class="appendix"><h2>مرفق ٣ ـ سجل المراحل وحدود التغطية</h2>{stages_html}<h3>تغطية المستندات</h3>{coverage_html}<h3>التحفظات وحدود النتيجة</h3>{_items(automation.get('limitations'), 'لم ترد قائمة مستقلة للتحفظات؛ تطبق النواقص ونتائج القراءة المبينة أعلاه.')}<p class="citation">قد يعتمد الفحص على صفحات مسترجعة من النصوص المقروءة؛ قراءة الصفحات أو استرجاعها لا تعني بمفردها ثبوت الامتثال. تعذر قراءة أصل أو مرجع يظل ظاهرًا في النتيجة ولا يتحول إلى استيفاء.</p></section>
{arithmetic_html}</main></body></html>'''


__all__ = ["render_ai_report", "render_pdf"]
