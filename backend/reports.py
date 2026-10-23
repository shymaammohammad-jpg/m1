"""Arabic evidence-linked reports based on the user's nine-page example.

The sample is a scanned, signed audit letter. This module reproduces its
section order and table vocabulary; it never copies the signature, seal,
letter number, or the example's factual findings into a new case.
"""

from __future__ import annotations

import base64
import functools
import html
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


STATUSES = {
    "pending": "لم يكتمل الفحص",
    "pass": "مطابق حسب الدليل المسجل",
    "fail": "ملاحظة تدقيقية",
    "not_applicable": "غير منطبق مع بيان السبب",
    "possible_match": "تطابق محتمل يحتاج إلى حسم",
    "confirmed_match": "تطابق مثبت بمراجعة المدقق",
    "cleared": "عدم إدراج وفق الدليل الذي راجعه المدقق",
    "unavailable": "تعذر التحقق من المصدر",
}

SECTIONS = [
    ("estimate", "أ", "الكلفة التخمينية"),
    ("basic", "ب", "استمارة البيانات الأساسية للمشروع أو العقد"),
    ("feasibility", "ج", "دراسة الجدوى الاقتصادية"),
    ("need", "د", "الحاجة الفعلية والرصيد المخزني"),
    ("warehouses", "هـ", "جاهزية المخازن والجهة المستفيدة"),
    ("signatures", "و", "تأييد المرفقات والتواقيع"),
    ("blacklist", "ز", "القائمة السوداء والشركات المتلكئة"),
    ("local", "ح", "أفضلية المنتجات المحلية"),
    ("similar", "ط", "الأعمال المماثلة"),
    ("financial", "ي", "الكفاءة المالية"),
    ("evaluation", "ك", "لجنة تحليل العطاءات والوثائق القياسية"),
    ("other", "ل", "أمور أخرى"),
]

# All rows are supplied by the auditor from the actual case. No sample
# figures, names, statutory thresholds, or successful outcomes are seeded.
TABLES: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "award_recommendations": (
        "clarifications", "موقف التوصية بالإحالة",
        [("number", "ت"), ("company", "اسم الشركة"),
         ("schedules", "أرقام الجداول الموصى بإحالتها"),
         ("recommendation", "موقف التوصية بالإحالة")],
    ),
    "estimate_market_comparison": (
        "estimate", "مقارنة الكلفة التخمينية بأسعار السوق السائدة",
        [("details", "التفاصيل"), ("estimate", "الكلفة التخمينية / دينار"),
         ("market_price", "أسعار السوق السائدة / دينار"), ("difference", "الفرق / دينار")],
    ),
    "award_market_comparison": (
        "estimate", "مقارنة مبالغ الإحالة بأسعار السوق",
        [("schedule", "رقم جدول المناقصة"), ("award_amount", "مبلغ الجدول المصادق عليه / دينار"),
         ("market_amount", "مبلغ الجدول بأسعار السوق / دينار"),
         ("difference", "الفرق / دينار"), ("difference_percent", "نسبة الفرق / %")],
    ),
    "similar_works": (
        "similar", "الأعمال المماثلة",
        [("number", "ت"), ("company", "الشركة"), ("estimated_cost", "الكلفة التخمينية"),
         ("similar_amount", "مبلغ الأعمال المماثلة"), ("provided_percent", "نسبة الأعمال المقدمة / %"),
         ("required_percent", "النسبة حسب المرجع المنطبق / %"), ("result", "النتيجة")],
    ),
    "financial_capacity": (
        "financial", "الكفاءة المالية",
        [("number", "ت"), ("company", "الشركة"), ("estimated_cost", "الكلفة التخمينية"),
         ("capacity_amount", "قيمة الكفاءة المالية المقدمة"), ("provided_percent", "النسبة المقدمة / %"),
         ("required_percent", "النسبة حسب المرجع المنطبق / %"), ("result", "النتيجة")],
    ),
    "evaluation_notes": (
        "evaluation", "الملاحظات المسجلة على تحليل العطاءات",
        [("company", "اسم الشركة"), ("observation", "الملاحظة المسجلة")],
    ),
    "discount_check": (
        "evaluation", "احتساب التخفيض ومطابقة المبالغ",
        [("company", "اسم الشركة"), ("schedule", "الجدول"),
         ("opening_amount", "مبلغ استمارة فتح العطاءات / دينار"),
         ("discount_percent", "نسبة التخفيض / %"), ("discounted_amount", "المبلغ بعد التخفيض / دينار"),
         ("analysis_amount", "مبلغ جدول التحليل / دينار")],
    ),
    "bid_amount_discrepancies": (
        "evaluation", "الفروقات بين فتح العطاءات وتحليلها",
        [("number", "ت"), ("company", "اسم الشركة"), ("schedule", "رقم الجدول"),
         ("opening_amount", "مبلغ استمارة الفتح / دينار"),
         ("discounted_amount", "المبلغ بعد التخفيض / دينار"),
         ("analysis_amount", "مبلغ جدول التحليل / دينار")],
    ),
    "missing_decisions": (
        "evaluation", "الجداول التي لم يثبت القرار لها",
        [("company", "اسم الشركة"), ("schedules", "أرقام الجداول التي لم يثبت القرار لها")],
    ),
    "unclassified_bidders": (
        "evaluation", "موقف الشركات وجداول المناقصة",
        [("number", "ت"), ("company", "اسم الشركة"), ("schedules", "جداول المناقصة")],
    ),
}

def _escape(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        value = "نعم" if value else "لا"
    if isinstance(value, (dict, list)):
        import json
        value = json.dumps(value, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def _paragraph(value: Any) -> str:
    return _escape(value).replace("\n", "<br>")


def _display_date(value: Any) -> str:
    value = str(value or "")
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%Y/%m/%d")
    except ValueError:
        return value


@functools.lru_cache(maxsize=1)
def _font_css() -> str:
    styles = []
    for weight, filename in [(400, "NotoNaskhArabic-Regular.ttf"), (700, "NotoNaskhArabic-Bold.ttf")]:
        font = Path("/usr/share/fonts/truetype/noto") / filename
        if font.is_file():
            encoded = base64.b64encode(font.read_bytes()).decode("ascii")
            styles.append(
                f"@font-face{{font-family:AuditNaskh;font-style:normal;font-weight:{weight};"
                f"src:url(data:font/ttf;base64,{encoded}) format('truetype');}}"
            )
    return "\n".join(styles)


def _section_for(check: dict[str, Any]) -> str:
    explicit = check.get("report_section")
    if explicit in {entry[0] for entry in SECTIONS}:
        return str(explicit)
    text = " ".join(str(check.get(k) or "") for k in ("id", "title", "description"))
    if check.get("step") == "blacklist" or any(x in text for x in ("السوداء", "المتلكئة")):
        return "blacklist"
    tests = [
        ("similar", ("مماثلة", "خبرة تخصصية")),
        ("financial", ("الكفاءة المالية", "السيولة النقدية", "كشف مصرفي")),
        ("warehouses", ("جاهزية المخازن", "جاهزية الجهة", "warehouse")),
        ("need", ("الرصيد المخزني", "رصيد مخزني", "الحاجة الفعلية", "inventory")),
        ("basic", ("البيانات الأساسية", "basic_data")),
        ("feasibility", ("الجدوى", "feasibility")),
        ("estimate", ("التخمينية", "أسعار السوق", "الكلفة", "estimate")),
        ("signatures", ("التواقيع", "توقيع الإقرار", "تأييد المرفقات", "سند التخويل")),
        ("local", ("المنتجات المحلية", "المحلي", "local_product")),
        ("evaluation", ("تحليل العطاءات", "الوثيقة القياسية", "الوثائق القياسية", "التخفيض", "فتح العطاءات")),
    ]
    for section, keywords in tests:
        if any(word in text for word in keywords):
            return section
    if check.get("step") == "standard":
        return "evaluation"
    return "other"


def _source_link(document: dict[str, Any] | None, page: Any = None) -> str:
    if not document:
        return "لم يربط مستند"
    name = document.get("name") or document.get("title") or document.get("id")
    document_id = str(document.get("id") or "")
    # IDs are escaped, and a relative path keeps the report usable on the
    # actual local application origin without embedding network destinations.
    from urllib.parse import quote
    target = f"/api/documents/{quote(document_id, safe='')}/file"
    label = _escape(name)
    result = f'<a href="{html.escape(target, quote=True)}">{label}</a>' if document_id else label
    if page:
        result += f"، ص {_escape(page)}"
    return result


def _render_check(check: dict[str, Any], documents: dict[str, dict[str, Any]], ordinal: int) -> str:
    status = str(check.get("status") or "pending")
    evidence = documents.get(str(check.get("evidence_document_id") or ""))
    reference = documents.get(str(check.get("reference_id") or ""))
    note = check.get("note") or "لم يسجل المدقق نتيجة مسندة لهذا البند بعد."
    source_name = check.get("source_name")
    source_page = check.get("source_page")
    origin = ""
    if source_name:
        origin = f"<div>أصل بند الفحص: {_escape(source_name)}"
        if source_page:
            origin += f"، ص {_escape(source_page)}"
        origin += ".</div>"
    reference_text = _source_link(reference)
    if check.get("legal_basis"):
        reference_text += f"؛ {_escape(check['legal_basis'])}"
    return f'''<article class="finding status-{_escape(status)}">
      <p class="finding-heading"><b>{ordinal} ـ {_escape(check.get('title'))}</b>
      <span class="status">[{_escape(STATUSES.get(status, status))}]</span></p>
      <p>{_paragraph(note)}</p>
      <div class="citation">الدليل: {_source_link(evidence, check.get('evidence_page'))}.
      <br>السند المرجعي: {reference_text}.{origin}</div>
    </article>'''


def _render_table(table_id: str, rows: Any) -> str:
    if not isinstance(rows, list) or not rows:
        return ""
    _, title, columns = TABLES[table_id]
    heads = "".join(f"<th>{_escape(label)}</th>" for _, label in columns)
    body = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        cells = []
        for key, label in columns:
            value = row.get(key, row.get(label))
            if key == "number" and value is None:
                value = index + 1
            cells.append(f"<td>{_paragraph(value)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        return ""
    return f'<div class="report-table"><p class="table-title">{_escape(title)}</p><table><thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def _render_quick_form(quick: dict[str, Any], references: list[dict[str, Any]]) -> str:
    """Print the same source-derived form the UI and readiness gate use."""
    from .audit_engine import QUICK_FORM_SCHEMA, SOURCE

    source = SOURCE["quick_form"]
    source_name = SOURCE["source"]["filename"]
    source_document = next(
        (document for document in references
         if document.get("name") == source_name or document.get("category") == "structure"),
        None,
    )
    source_label = _source_link(source_document, "24–29") if source_document else f"{_escape(source_name)}، ص 24–29"
    rendered = [
        f'<p class="quick-notice">{_escape(source["source_note"])}</p>',
        f'<p class="citation">مصدر الاستمارة: {source_label}.</p>',
    ]
    for index, section in enumerate(QUICK_FORM_SCHEMA):
        section_source = source["sections"][index]
        section_page = section_source.get("page")
        rows = []
        for field in section["fields"]:
            value = quick.get(field["key"])
            # Missing optional explanatory notes need no repetitive blank
            # rows; required fields and the six sections always remain visible.
            if field["key"].endswith("_note") and not field.get("required") and not value:
                continue
            if field["type"] == "select" and value:
                options = {str(option["value"]): option["label"] for option in field.get("options", [])}
                value = options.get(str(value), f"قيمة غير معتمدة: {value}")
            elif field["type"] == "date" and value:
                value = _display_date(value)
            description = field.get("description")
            label = _escape(field["label"])
            if description:
                label += f'<div class="quick-indicator">{_paragraph(description)}</div>'
            page = field.get("source_page") or section_page
            rows.append(f'<tr><th>{label}</th><td>{_paragraph(value)}</td><td class="quick-page">{_escape(page)}</td></tr>')
        section_note = ""
        if section.get("description"):
            section_note = f'<p class="quick-notice">{_escape(section["description"])}</p>'
        if section["id"] == "decision":
            section_note += '<p class="citation">عنوان القرار الوارد بالمصدر يخص قرار استمارة الفحص الأولي وتوجيه الفحص اللاحق؛ لا يمثل اعتماداً للتقرير النهائي.</p>'
        rendered.append(
            f'<section class="quick-section"><h3>{_escape(section["title"])}</h3>'
            f'<p class="citation">المصدر: {_escape(source_name)}، ص {_escape(section_page)}.</p>'
            f'{section_note}<table class="quick-table"><thead><tr><th>البند</th><th>البيانات / النتيجة المسجلة</th><th>صفحة المصدر</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>'
        )
    return "".join(rendered)


def render_report(case: dict[str, Any], references: list[dict[str, Any]], final: bool = False) -> str:
    """Return a complete, self-contained printable Arabic HTML report.

    Readiness is enforced by the API before allowing ``final=True``. The
    resulting document still requires the authorized human's signature.
    Dynamic text is HTML-escaped, including text extracted from attachments.
    """
    quick = case.get("quick_form") or {}
    if not isinstance(quick, dict):
        quick = {}
    documents = {str(document.get("id")): document for document in [*references, *case.get("documents", [])]}
    checks = case.get("checks") or []
    grouped: dict[str, list[dict[str, Any]]] = {key: [] for key, _, _ in SECTIONS}
    for check in checks:
        grouped[_section_for(check)].append(check)
    report_tables = quick.get("report_tables") or {}
    if not isinstance(report_tables, dict):
        report_tables = {}
    readiness = case.get("readiness") or {}
    blockers = readiness.get("blockers") or []
    case_title = case.get("title") or "تدقيق عقد حكومي"
    subject = quick.get("subject") or f"تدقيق العقد رقم ({case.get('contract_number') or 'غير مثبت'}) ـ {case_title}"
    institution = quick.get("issuing_entity") or case.get("entity") or "الجهة المدققة"
    department = quick.get("department") or "وحدة التدقيق والرقابة الداخلية"
    recipient = quick.get("recipient") or case.get("entity") or "الجهة المعنية"
    report_date = _display_date(quick.get("report_date") or quick.get("audit_date") or case.get("updated_at"))
    instruction_year = case.get("instruction_year")
    instruction = f"تعليمات سنة {instruction_year}" if instruction_year else "لم تحسم سنة التعليمات"
    status_label = "تقرير مكتمل المراجعة ـ غير موقع" if final else "مسودة تقرير للمراجعة"
    original_report = next((r for r in references if r.get("category") in ("report", "report_template", "human_report") or "نموذج تدقيق" in str(r.get("name", ""))), None)
    source_view = _source_link(original_report) if original_report else "النموذج البشري المرفق"
    report_parts = []
    for section, letter, title in SECTIONS:
        content = "".join(_render_check(check, documents, i + 1) for i, check in enumerate(grouped[section]))
        for table_id, (owner_section, _, _) in TABLES.items():
            if owner_section == section:
                content += _render_table(table_id, report_tables.get(table_id))
        if section == "blacklist":
            from .blacklist import OFFICIAL_NOTICE

            blacklist = case.get("blacklist") or {}
            evidence = documents.get(str(blacklist.get("evidence_document_id") or ""))
            checked_at = _display_date(blacklist.get("checked_at"))
            content += f'''<p><b>نتيجة مراجعة القائمة:</b> {_escape(STATUSES.get(str(blacklist.get('status') or 'pending'), 'لم يكتمل الفحص'))}.</p>
            <p>{_paragraph(blacklist.get('note') or 'لم تسجل نتيجة تحقق مسندة من موقع وزارة التخطيط.')}</p>
            <div class="citation">مستند التحقق: {_source_link(evidence)}؛ تاريخ التحقق: {_escape(checked_at)}؛ رابط المصدر: <span dir="ltr">{_escape(blacklist.get('source_url'))}</span>.</div>
            <p class="official-notice">{_escape(OFFICIAL_NOTICE)}</p>'''
        if not content:
            content = '<p class="unreviewed">لم يسجل فحص أو جدول لهذا القسم في الحالة الحالية.</p>'
        report_parts.append(f'<section class="observation-section"><h3>{letter} ـ {_escape(title)}:</h3>{content}</section>')
    blockers_html = ""
    if blockers:
        items = "".join(f"<li>{_escape(item)}</li>" for item in blockers)
        blockers_html = f'<div class="blockers"><b>بنود تحتاج إلى استكمال قبل إصدار النسخة المكتملة:</b><ul>{items}</ul></div>'
    quick_form_html = _render_quick_form(quick, references)
    reference_rows = []
    used_reference_ids = {str(check.get("reference_id")) for check in checks if check.get("reference_id")}
    # Include the attached authoritative reference library alongside the
    # citations, but mark explicitly whether it was selected in an assessment.
    for i, document in enumerate(references, start=1):
        referenced = "مرتبط ببند فحص" if str(document.get("id")) in used_reference_ids else "مرجع محفوظ؛ لم يربط بنتيجة"
        reference_rows.append(f'<tr><td>{i}</td><td>{_source_link(document)}</td><td>{_escape(document.get("page_count"))}</td><td>{referenced}</td></tr>')
    clarification_table = _render_table("award_recommendations", report_tables.get("award_recommendations"))
    clarifications = quick.get("clarifications") or "تقتصر الإيضاحات الآتية على بيانات الحالة المدخلة والمستندات المرفوعة؛ ولم تنقل أسماء الشركات أو مبالغ أو نتائج من التقرير النموذجي."
    contract_documents = case.get("documents") or []
    document_rows = "".join(
        f'<tr><td>{i}</td><td>{_source_link(document)}</td><td>{_escape(document.get("page_count"))}</td><td>{_escape(document.get("extraction_status"))}</td><td class="hash" dir="ltr">{_escape(document.get("sha256"))}</td></tr>'
        for i, document in enumerate(contract_documents, start=1)
    )
    closing = quick.get("closing") or "للتفضل بالاطلاع واتخاذ الإجراءات اللازمة لمعالجة الملاحظات المسجلة واستكمال النواقص، وإعلامنا بالإجراءات المتخذة، مع التقدير."
    css = '''
    *{box-sizing:border-box}html{background:#e9edf0}body{margin:0;color:#111;font-family:AuditNaskh,'Noto Naskh Arabic',serif;font-size:14pt;line-height:1.7;direction:rtl}
    .toolbar{font-family:Arial,sans-serif;background:#113e43;color:#fff;padding:16px 24px;font-size:14px;display:flex;justify-content:space-between;align-items:center;gap:20px}.toolbar a{color:#e4d6a8}.toolbar p{margin:0}.toolbar strong{display:block;margin-bottom:6px}
    .paper{max-width:210mm;margin:22px auto;background:white;padding:24mm 18mm 24mm 20mm;box-shadow:0 5px 30px #0002;min-height:297mm;position:relative}h1,h2,h3,p{margin:0 0 9px}h1{font-size:17pt;text-align:center;line-height:1.65}h2{font-size:16pt;margin-top:19px;text-decoration:underline;text-underline-offset:5px}h3{font-size:14pt;font-weight:700;margin-top:15px}.letterhead{display:flex;justify-content:space-between;align-items:flex-start;gap:25px;margin-bottom:15px}.letterhead p{margin:0}.letter-meta{font-size:12pt;min-width:35%}.institution{text-align:right}.recipient{text-align:center;font-size:16pt;margin-top:22px}.subject{font-size:16pt;text-decoration:underline;text-underline-offset:6px;margin:12px auto 22px}.salutation{text-align:right}.body-text,.finding>p,.observation-section>p{text-align:justify}.document-state{text-align:center;border:1px solid #777;font-size:12pt;margin:0 0 17px;padding:4px 12px}.summary{width:100%;margin-bottom:14px}.summary th{width:21%}.summary td{width:29%}table{border-collapse:collapse;width:100%;font-size:12pt;line-height:1.5;margin:8px 0 17px;table-layout:auto}th,td{border:1px solid #444;padding:5px 7px;text-align:center;vertical-align:middle;overflow-wrap:anywhere}th{font-weight:700;background:#f6f6f6}thead{display:table-header-group}tr{break-inside:avoid}.table-title{font-size:13pt;text-align:center;margin:12px 0 2px;font-weight:700}.report-table{break-inside:auto}.finding{margin-bottom:13px}.finding-heading{margin-bottom:2px}.status{font-size:11pt}.citation{font-size:10.5pt;line-height:1.65;margin:3px 0 6px;color:#333}.citation a,a{color:inherit;text-decoration:underline;overflow-wrap:anywhere}.unreviewed{color:#555;font-size:12pt}.blockers{border:1px dashed #777;font-size:12pt;padding:9px 13px;margin:15px 0}.blockers ul{margin:4px 0;padding-right:23px}.closing{margin:22px 0 20px;text-align:justify}.signature{margin-right:auto;margin-left:0;width:50%;text-align:center;min-height:38mm;padding-top:5mm}.signature p{margin:2px 0}.approval-note{font-size:10pt;border-top:1px solid #777;padding-top:6px;color:#444;margin-top:14px}.appendix{break-before:page}.appendix h2{margin-top:0}.quick-table th{text-align:right}.quick-table th:first-child{width:49%}.quick-table td:nth-child(2),.quick-table th:nth-child(2){width:43%}.quick-table td{text-align:right;min-height:24px}.quick-table .quick-page,.quick-table th:last-child{width:8%;text-align:center;font-size:10pt}.quick-indicator{font-size:10.5pt;line-height:1.6;font-weight:400;margin-top:4px;color:#444}.quick-notice,.official-notice{font-size:11pt;border-right:2px solid #777;padding:4px 10px;margin:8px 0;line-height:1.7}.quick-section h3{break-after:avoid}.hash{font-family:monospace;font-size:6pt;word-break:break-all}.report-footer{margin-top:14px;border-top:1px solid #ccc;padding-top:5px;font-size:9pt;color:#555}.watermark{position:fixed;top:47%;left:0;right:0;text-align:center;opacity:.08;transform:rotate(-30deg);font-size:70pt;font-weight:bold;pointer-events:none;z-index:0}.paper>*{position:relative;z-index:1}
    @page{size:A4 portrait;margin:23mm 18mm 20mm 20mm;@bottom-center{content:'(' counter(pages) ' - ' counter(page) ')';font-family:AuditNaskh,serif;font-size:10pt;direction:rtl}}
    @media print{html,body{background:#fff}.toolbar{display:none}.paper{max-width:none;min-height:0;margin:0;padding:0;box-shadow:none}.watermark{position:fixed}.paper>.watermark{position:fixed;z-index:0}h2,h3,.finding-heading,.table-title{break-after:avoid}a{color:#111}.document-state{font-size:11pt}}
    '''
    watermark = '' if final else '<div class="watermark" aria-hidden="true">مسودة للمراجعة</div>'
    return f'''<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'">
<title>{_escape(status_label)} ـ {_escape(case_title)}</title><style>{_font_css()}{css}</style></head>
<body><div class="toolbar"><div><strong>{_escape(status_label)}</strong><p>ترتيب الأقسام والجداول مستند إلى النموذج البشري المرفق. هذا المستند لا يحمل توقيعاً أو ختماً رسمياً.</p></div><div>النموذج للمقارنة: {source_view}</div></div>
<main class="paper">{watermark}
<header class="letterhead"><div class="institution"><p>جمهورية العراق</p><p><b>{_escape(institution)}</b></p><p>{_escape(department)}</p></div><div class="letter-meta"><p>العدد: {_escape(quick.get('report_number'))}</p><p>التاريخ: {_escape(report_date)}</p><p>رقم ملف التدقيق: <span dir="ltr">{_escape(case.get('id'))}</span></p></div></header>
<div class="document-state">{_escape(status_label)}</div>
<p class="recipient">إلى / {_escape(recipient)}</p><h1 class="subject">م / {_escape(subject)}</h1>
<p class="salutation">بعد التحية:</p>
<p class="body-text">قمنا بأعمال فحص أوليات العقد رقم ({_escape(case.get('contract_number'))}) والخاص بـ ({_escape(case_title)})، للجهة ({_escape(case.get('entity'))})، وبمبلغ مدخل قدره ({_escape(case.get('amount'))}) {_escape(case.get('currency') or 'IQD')}، وفق {_escape(instruction)} المختارة بناءً على تاريخ العقد ({_escape(_display_date(case.get('contract_date')))}). يعرض هذا التقرير نتائج المدقق والأدلة والمراجع المرتبطة بكل بند.</p>
<p class="body-text">لدينا بشأن ذلك الإيضاحات والملاحظات الآتية:</p>
<section><h2>١ ـ الإيضاحات:</h2>
<p class="body-text">أ ـ {_paragraph(clarifications)}</p>
<p class="body-text">ب ـ اسم المتعاقد: {_escape(case.get('contractor'))}. عدد المستندات المرفوعة: {len(contract_documents)}. عدد بنود الفحص المنجزة: {_escape(readiness.get('completed', sum(c.get('status') != 'pending' for c in checks)))} من أصل {_escape(readiness.get('total', len(checks)))}.</p>
<table class="summary"><tbody><tr><th>رقم العقد</th><td>{_escape(case.get('contract_number'))}</td><th>التعليمات المختارة</th><td>{_escape(instruction_year)}</td></tr><tr><th>المتعاقد</th><td>{_escape(case.get('contractor'))}</td><th>تاريخ العقد</th><td>{_escape(_display_date(case.get('contract_date')))}</td></tr><tr><th>الكلفة التخمينية</th><td>{_escape(quick.get('estimated_cost'))}</td><th>مدة التنفيذ</th><td>{_escape(quick.get('duration'))}</td></tr></tbody></table>
{clarification_table}{blockers_html}</section>
<section><h2>٢ ـ الملاحظات:</h2>{''.join(report_parts)}</section>
<p class="closing">{_paragraph(closing)}</p>
<div class="signature"><p>اسم المدقق / {_escape(quick.get('auditor'))}</p><p>الصفة / {_escape(quick.get('auditor_role'))}</p><p>التاريخ / {_escape(_display_date(quick.get('audit_date')))}</p><p>التوقيع / ____________________</p></div>
<p>نسخة منه إلى / {_paragraph(quick.get('copy_to'))}</p>
<p class="approval-note">أعد النظام هذا المستند من بيانات الحالة ونتائج المراجعة المدخلة. لم ينسخ توقيع أو ختم أو بيانات الحالة النموذجية. اكتمال المراجعة في النظام لا يمثل توقيعاً أو اعتماداً رسمياً؛ يلزم اعتماد الجهة المخولة.</p>
<section class="appendix"><h2>مرفق ١ ـ استمارة الفحص السريع</h2><p>استمارة مرتبطة بملف التدقيق رقم <span dir="ltr">{_escape(case.get('id'))}</span>.</p>{quick_form_html}</section>
<section class="appendix"><h2>مرفق ٢ ـ فهرس الأدلة والمراجع</h2><h3>أ ـ مستندات العقد وأولياته</h3><table><thead><tr><th>ت</th><th>المستند</th><th>الصفحات</th><th>استخراج النص</th><th>SHA-256</th></tr></thead><tbody>{document_rows or '<tr><td colspan="5">لم ترفع مستندات للعقد.</td></tr>'}</tbody></table><h3>ب ـ المراجع المحفوظة</h3><table><thead><tr><th>ت</th><th>المرجع</th><th>الصفحات</th><th>الاستخدام</th></tr></thead><tbody>{''.join(reference_rows) or '<tr><td colspan="4">لم تحفظ مراجع.</td></tr>'}</tbody></table><p class="report-footer">المرفقات الأصلية محفوظة مستقلة للمقارنة والتوثيق. روابط الأدلة تفتح من داخل تطبيق التدقيق المحلي.</p></section>
</main></body></html>'''


def render_pdf(report_html: str) -> bytes:
    """Print self-contained HTML using the installed local Chromium binary.

    Rendering requires no external URLs. The temporary profile and files
    are removed after the subprocess finishes, including on failure.
    """
    chromium = os.environ.get("AUDIT_CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")
    if not chromium:
        raise RuntimeError("تعذر العثور على Chromium لتوليد PDF. يمكن تنزيل نسخة HTML وطباعتها بعد تثبيت Chromium.")
    with tempfile.TemporaryDirectory(prefix="audit-report-") as directory:
        root = Path(directory)
        input_path = root / "report.html"
        output_path = root / "report.pdf"
        input_path.write_text(report_html, encoding="utf-8")
        env = os.environ.copy()
        env["XDG_CACHE_HOME"] = str(root / "cache")
        env["XDG_CONFIG_HOME"] = str(root / "config")
        # A subprocess isolates Playwright's synchronous event loop from
        # FastAPI's event loop and gives the whole print operation a deadline.
        # Browser requests are aborted: the report embeds its own fonts.
        renderer = '''
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(
        executable_path=sys.argv[3], headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-background-networking"],
        timeout=20000,
    )
    try:
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content(Path(sys.argv[1]).read_text(encoding="utf-8"), wait_until="load", timeout=20000)
        page.evaluate("document.fonts.ready")
        page.pdf(path=sys.argv[2], format="A4", print_background=True, prefer_css_page_size=True)
    finally:
        browser.close()
'''
        command = [sys.executable, "-c", renderer, str(input_path), str(output_path), chromium]
        try:
            process = subprocess.run(command, capture_output=True, timeout=75, env=env, check=False)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("انتهت مهلة توليد PDF. أعد المحاولة بمستند أقصر أو استخدم نسخة HTML.") from error
        if process.returncode != 0 or not output_path.is_file():
            raise RuntimeError("تعذر توليد PDF بواسطة محرك الطباعة. يمكن مراجعة نسخة HTML وطباعتها.")
        content = output_path.read_bytes()
        if not content.startswith(b"%PDF-"):
            raise RuntimeError("لم ينتج محرك الطباعة ملف PDF صالحاً.")
        return content
