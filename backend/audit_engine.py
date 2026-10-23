"""Source-grounded review workflow; this module never invents legal conclusions."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import json
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
SOURCE = json.loads((ROOT / "reference_structure.json").read_text(encoding="utf-8"))
CIRCULARS = json.loads((ROOT / "reference_circulars.json").read_text(encoding="utf-8"))
SOURCE_GUIDANCE = {
    "notice": "اختيار سنة التعليمات مستقل عن نفاذ إعمامات 2026. حزمة الدليل تتضمن قرارات سابقة وملغاة؛ لا تدمج حدودها المالية ومددها مع قرار 398. وجود وثيقة لا يثبت الامتثال.",
    "rules": CIRCULARS["rules"],
    "document_requirements": CIRCULARS["document_requirements"],
    "bundle_index": CIRCULARS["pm_bundle_index"],
    "models": CIRCULARS["guide_models"],
    "guide_rules": CIRCULARS.get("guide_rules", []),
    "source_warnings": CIRCULARS.get("source_guidance", []),
    "quick_form_notice": SOURCE["quick_form"]["source_note"],
}
STEPS = [
    {"id": "upload", "title": "العقد والأوليات"},
    {"id": "year", "title": "سنة التعليمات"},
    {"id": "diwan", "title": "أعمام الديوان"},
    {"id": "cabinet", "title": "مجلس الوزراء"},
    {"id": "structure", "title": "هيكلية وبرنامج التدقيق"},
    {"id": "quick", "title": "الفحص السريع"},
    {"id": "standard", "title": "الوثائق القياسية"},
    {"id": "blacklist", "title": "القوائم السوداء"},
    {"id": "report", "title": "التقرير النهائي"},
]


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Baghdad")).date()


def instruction_policy(contract_date: str | None, override: int | None = None, override_reason: str = "") -> dict:
    """The selection is the user's explicit rule, not a legislative assertion."""
    try:
        d = date.fromisoformat(contract_date or "")
    except (ValueError, TypeError):
        return {"instruction_year": None, "year_warning": "أدخل تاريخ العقد لتحديد سنة التعليمات."}
    if d > today():
        return {"instruction_year": None, "year_warning": "تاريخ العقد مستقبلي؛ القاعدة المطلوبة تنتهي بالسنة الحالية."}
    default = 2014 if d.year == 2024 else 2025 if 2025 <= d.year <= today().year else None
    if override is not None:
        if override not in {2014, 2025} or not isinstance(override_reason, str) or not override_reason.strip():
            return {"instruction_year": None, "default_instruction_year": default, "year_warning": "تثبيت نسخة مختلفة يتطلب اختيار 2014 أو 2025 وتوثيق السبب القانوني صراحةً."}
        selected = override
        lead = f"ثُبتت تعليمات {selected} بمراجعة بشرية موثقة للحالة: {override_reason.strip()}"
    else:
        selected = default
        lead = "اختيار السنة يتبع القاعدة التي حددها المستخدم؛ يلزم التحقق من السند والنفاذ والاستثناءات."
    effective_warning = " النص الرسمي لتعليمات 2025 (الوقائع العراقية 4849، 17/11/2025، ص56 من PDF، المادتان 41 و42) يربط النفاذ بمرور 90 يوماً من النشر ويقرر استمرار تعليمات 2014 للعقود المبرمة بموجبها. وكتاب وزارة التخطيط 3429 في 3/2/2026 يحدد بدء التطبيق في 15/2/2026؛ سنة العقد وحدها لا تحسم النسخة النافذة."
    if override is not None:
        return {"instruction_year": selected, "default_instruction_year": default, "year_warning": lead + effective_warning}
    if d.year == 2024:
        return {"instruction_year": 2014, "default_instruction_year": default, "year_warning": "اختيرت تعليمات 2014 وفق القاعدة التي حددها المستخدم لعقود 2024. يلزم إرفاق النص الرسمي والتحقق من النفاذ والاستثناءات."}
    if 2025 <= d.year <= today().year:
        return {"instruction_year": 2025, "default_instruction_year": default, "year_warning": "اختيرت تعليمات 2025 وفق قاعدة المستخدم. لا يعني الاختيار الآلي ثبوت انطباق جميع المراجع أو أعمام 2026 على العقد." + effective_warning}
    return {"instruction_year": None, "year_warning": "لم يحدد المستخدم قاعدة للسنوات السابقة لـ2024؛ يلزم تحديد الأساس القانوني لهذه الحالة قبل اعتماد التقرير."}


def _check(key: str, step: str, title: str, description: str, **extra) -> dict:
    return {"id": key, "step": step, "title": title, "description": description,
            "status": "pending", "note": "", "evidence_document_id": None,
            "evidence_page": "", "reference_id": None, "legal_basis": "", **extra}


def initial_checks() -> list[dict]:
    checks = [
        _check("file_scope", "upload", "اكتمال ملف العقد وتحديد نطاق الفحص", "تحقق من مسودة العقد والأوليات والجهة المختصة ونوع العقد، دون اعتبار مجرد رفع الملفات دليلاً على استيفائها."),
        _check("instructions_basis", "year", "تثبيت التعليمات النافذة والسند القانوني", "اربط النص الرسمي لتعليمات السنة المختارة وحدد المادة والصفحة والاستثناءات. اختيار السنة يتبع طلب المستخدم ويحتاج تحققاً قانونياً."),
        _check("diwan_applicability", "diwan", "ملاءمة أعمام الديوان للعقد زمنياً وموضوعياً", "الأعمام المرفق مؤرخ في 17/8/2026. بيّن سبب الانطباق أو عدمه ونطاق الجهة والعقد؛ لا يطبق تلقائياً بأثر رجعي.", source_name="اعمام الديوان.pdf", source_page=1),
        _check("diwan_attachments", "diwan", "مطابقة آلية الاستلام والأوليات الواردة بأعمام الديوان", "راجع أصل الكتاب وملاحقه وتوثيق إرسال الأوليات ورقياً وإلكترونياً عند الانطباق.", source_name="اعمام الديوان.pdf", source_page=1),
        _check("cabinet_applicability", "cabinet", "ملاءمة قرار مجلس الوزراء والكتب المبلغة", "الدليل المرفق يتضمن قرار 398 لسنة 2026 وكتاب الأمانة العامة 32693 في 10/8/2026. افحص التاريخ والنطاق والاستثناءات دون افتراض سريان عام.", source_name="دليل مكتب رئيس الوزراء.pdf", source_page=3),
        _check("cabinet_conditions", "cabinet", "فحص المتطلبات والموافقات والنماذج المرتبطة بالقرار", "سجل المتطلبات المنطبقة وحساب المدد وموافقات الاستثناء استناداً إلى الصفحات الأصلية، بعد ثبوت ملاءمة القرار.", source_name="دليل مكتب رئيس الوزراء.pdf", source_page=4),
        _check("program_temporal", "structure", "ملاءمة برنامج التدقيق للتعليمات المختارة", "البرنامج المرفق يذكر تعليمات 2025 صراحة في ص4؛ تستخدم أسئلته للفحص مع الرجوع إلى السند الصحيح، ولا تنقل إحالاته إلى عقود 2024 تلقائياً.", source_name=SOURCE["source"]["filename"], source_page=4),
    ]
    for item in SOURCE["program"]["items"]:
        if item["id"] == "program_35":
            # This source requirement is implemented by the dedicated blacklist evidence workflow.
            continue
        step = "standard" if item["id"] in {"program_28", "program_29", "program_36"} else "structure"
        checks.append(_check(item["id"], step, item["label"],
            "سؤال تدقيقي مستخلص من البرنامج؛ لا يمثل نتيجة فحص أو حكماً قانونياً آلياً. وثّق الإجراء والدليل والسند النافذ أو سبب عدم الانطباق.",
            source_name=SOURCE["source"]["filename"], source_page=item["page"], source_section=item["section"]))
    return checks


def _field(key, label, kind="text", required=False, **extra):
    return {"key": key, "label": label, "type": kind, "required": required, **extra}


def _quick_schema():
    q = SOURCE["quick_form"]
    data = []
    for f in q["data_fields"]:
        kind = "date" if f["id"].endswith("_at") else "text"
        data.append(_field(f["id"], f["label"], kind, True, source_page=f["page"]))
    req, risks = [], []
    for item in q["requirements"]:
        req += [_field(item["id"], item["label"], "select", True,
                       options=[{"value": a, "label": b} for a, b in [("fulfilled", "مستوفي"), ("missing", "غير مستوفي"), ("not_applicable", "غير منطبق")]],
                       source_page=item["page"], description=item.get("effective_date_warning", "")),
                _field(item["id"] + "_note", "ملاحظات ودليل المتطلب", "textarea", False, source_page=item["page"])]
    for item in q["risks"]:
        risks += [_field(item["id"], f'{item["source_number"]}. {item["label"]}', "select", True,
                         options=[{"value": a, "label": b} for a, b in [("low", "منخفض"), ("medium", "متوسط"), ("high", "مرتفع")]],
                         source_page=item["page"], description=item["indicator"]),
                  _field(item["id"] + "_note", "مؤشرات الخطر والأدلة", "textarea", False, source_page=item["page"])]
    return [
        {"id": "data", "title": q["sections"][0]["label"], "fields": data},
        {"id": "requirements", "title": q["sections"][1]["label"], "fields": req},
        {"id": "risks", "title": q["sections"][2]["label"], "fields": risks},
        {"id": "deep_risks", "title": q["sections"][3]["label"], "fields": [_field("deep_risks", "مواطن المخاطر وخطة الفحص المتعمق", "textarea")]},
        {"id": "requests", "title": q["sections"][4]["label"], "fields": [_field("clarification_requests", "الوثيقة / الجهة / تاريخ المذكرة / تاريخ الاستلام — سطر لكل طلب", "textarea")]},
        {"id": "decision", "title": q["sections"][5]["label"], "description": q["source_note"], "fields": [
            _field("quick_decision", "قرار الفحص الأولي", "select", True, options=[{"value": str(i + 1), "label": v} for i, v in enumerate(q["decisions"])]),
            _field("quick_decision_note", "أسباب القرار ونطاق الفحص اللاحق", "textarea", True),
            _field("auditor", "اسم المدقق", required=True), _field("audit_date", "تاريخ الفحص", "date", True),
            _field("team_lead", "اسم مسؤول فريق التدقيق", required=True),
        ]},
    ]


QUICK_FORM_SCHEMA = _quick_schema()


def _nonempty(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def valid_evidence_page(value, doc: dict) -> bool:
    """Page citation supports one page or a bounded page range, never arbitrary text."""
    match = re.fullmatch(r"\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*", str(value or ""))
    if not match:
        return False
    start, end = int(match[1]), int(match[2] or match[1])
    count = doc.get("page_count")
    return 1 <= start <= end and (not count or end <= int(count))


def reference_matches(check: dict, reference: dict, instruction_year: int | None) -> bool:
    if check.get("id") == "instructions_basis":
        return reference.get("category") == "instructions" and str(reference.get("reference_year")) == str(instruction_year)
    category = {"diwan": "diwan", "cabinet": "cabinet", "standard": "standard"}.get(check.get("step"))
    return category is None or reference.get("category") == category


def readiness(case: dict, references: list[dict]) -> dict:
    blockers: list[str] = []
    documents = case.get("documents", [])
    all_documents = {d["id"]: d for d in [*references, *documents] if d.get("id")}
    evidence_documents = {d["id"]: d for d in documents if d.get("id")}
    policy = instruction_policy(case.get("contract_date"), override=case.get("instruction_year_override"), override_reason=case.get("instruction_override_reason", ""))
    if policy["instruction_year"] is None:
        blockers.append(policy["year_warning"])
    for key, label in [("title", "موضوع العقد"), ("contract_number", "رقم العقد"), ("contractor", "الطرف المتعاقد"), ("entity", "الجهة المتعاقدة")]:
        if not _nonempty(case.get(key)):
            blockers.append(f"أكمل {label}.")
    try:
        amount = Decimal(str(case.get("amount", "")).replace(",", ""))
        if not amount.is_finite() or amount <= 0:
            raise InvalidOperation
    except InvalidOperation:
        blockers.append("أدخل مبلغ العقد الصحيح الأكبر من صفر.")
    if not any(d.get("category") == "contract" for d in documents):
        blockers.append("ارفع مسودة العقد ضمن تصنيف العقد.")
    if not any(d.get("category") == "supporting" for d in documents):
        blockers.append("ارفع الأوليات المؤيدة للعقد ضمن تصنيف الأوليات.")
    year = policy["instruction_year"]
    instruction_refs = [d for d in all_documents.values() if d.get("category") == "instructions" and str(d.get("reference_year")) == str(year)] if year else []
    if year and not instruction_refs:
        blockers.append(f"أرفق النص الرسمي لتعليمات {year} وصنّفه تعليمات مع تحديد سنة المرجع؛ المراجع المرفقة لا تغني عن النص الكامل.")
    canonical = {c["id"]: c for c in initial_checks()}
    actual = {c.get("id"): c for c in case.get("checks", [])}
    completed = 0
    for key, expected in canonical.items():
        c = actual.get(key, {})
        status = c.get("status", "pending")
        if status not in {"pass", "fail", "not_applicable"}:
            blockers.append("لم يُستكمل: " + expected["title"])
            continue
        if not _nonempty(c.get("note")):
            blockers.append("أضف نتيجة الإجراء أو سبب عدم الانطباق: " + expected["title"])
            continue
        if status in {"pass", "fail"}:
            evidence = evidence_documents.get(c.get("evidence_document_id"))
            if not evidence or not valid_evidence_page(c.get("evidence_page"), evidence):
                blockers.append("دليل وصفحة صالحان مطلوبان: " + expected["title"])
                continue
            if c.get("reference_id") not in all_documents or not _nonempty(c.get("legal_basis")):
                blockers.append("أكمل المرجع والمادة أو الفقرة والصفحة: " + expected["title"])
                continue
            if not reference_matches(expected, all_documents[c["reference_id"]], year):
                blockers.append("تصنيف المرجع لا يطابق الفحص: " + expected["title"])
                continue
        if key == "instructions_basis":
            if status == "not_applicable" or c.get("reference_id") not in {d["id"] for d in instruction_refs}:
                blockers.append("يجب تثبيت سند تعليمات السنة المختارة من النص الرسمي، ولا يجوز تجاوزه بغير منطبق.")
                continue
        completed += 1
    q = case.get("quick_form") or {}
    quick_missing = []
    for key, label in [("entity", "الجهة"), ("title", "موضوع العقد"), ("contract_number", "رقم العقد")]:
        if _nonempty(q.get(key)) and q[key].strip() != str(case.get(key, "")).strip():
            quick_missing.append(f"بيانات {label} في الاستمارة تختلف عن ملف العقد")
    if _nonempty(q.get("amount")):
        try:
            if Decimal(q["amount"].replace(",", "")) != Decimal(str(case.get("amount", "")).replace(",", "")):
                quick_missing.append("مبلغ الاستمارة يختلف عن مبلغ العقد")
        except InvalidOperation:
            quick_missing.append("مبلغ الاستمارة غير صالح")
    for section in QUICK_FORM_SCHEMA:
        for f in section["fields"]:
            value = q.get(f["key"])
            if f["required"] and not _nonempty(value):
                quick_missing.append(f["label"])
            elif value and f["type"] == "select" and value not in {x["value"] for x in f["options"]}:
                quick_missing.append(f["label"])
            elif value and f["type"] == "date":
                try:
                    if date.fromisoformat(value) > today():
                        quick_missing.append(f["label"])
                except (TypeError, ValueError):
                    quick_missing.append(f["label"])
    for item in SOURCE["quick_form"]["requirements"]:
        if q.get(item["id"]) in {"missing", "not_applicable"} and not _nonempty(q.get(item["id"] + "_note")):
            quick_missing.append("سبب عدم الاستيفاء أو عدم الانطباق: " + item["label"])
    high_risks = [r for r in SOURCE["quick_form"]["risks"] if q.get(r["id"]) == "high"]
    if high_risks and not _nonempty(q.get("deep_risks")):
        quick_missing.append("خطة الفحص المتعمق للمخاطر المرتفعة")
    if quick_missing:
        blockers.append(f"استمارة الفحص السريع غير مكتملة ({len(quick_missing)} حقلاً): " + "، ".join(quick_missing[:5]) + (" …" if len(quick_missing) > 5 else ""))
    blacklist = case.get("blacklist") or {}
    if blacklist.get("status") not in {"cleared", "confirmed_match"}:
        blockers.append("أكمل المراجعة البشرية للقائمة السوداء الرسمية؛ تعذر الاتصال أو عدم العثور الآلي لا يعني الخلو.")
    else:
        doc = all_documents.get(blacklist.get("evidence_document_id"))
        if not doc or doc.get("category") != "blacklist" or not _nonempty(blacklist.get("note")):
            blockers.append("أرفق نسخة القائمة السوداء الرسمية ووثق نتيجة مراجعتها.")
        if not blacklist.get("human_confirmed"):
            blockers.append("أكد المراجعة البشرية لنتيجة القائمة السوداء صراحةً.")
        if not blacklist.get("checked_at"):
            blockers.append("لم يوثق وقت فحص القائمة السوداء.")
        try:
            url = urlsplit(blacklist.get("source_url") or "")
            official = url.scheme == "https" and url.hostname in {"mop.gov.iq", "www.mop.gov.iq", "blacklist.mop.gov.iq"} and not url.username and not url.password and url.port in {None, 443}
        except ValueError:
            official = False
        if not official:
            blockers.append("وثق رابط مصدر القائمة السوداء من موقع وزارة التخطيط الرسمي عبر HTTPS.")
        if doc and doc.get("extraction_status") in {"failed", "unsupported"}:
            blockers.append("مستند القائمة السوداء غير صالح للقراءة؛ يلزم إرفاق أصل صالح.")
        if blacklist.get("status") == "cleared" and doc and doc.get("extraction_status") in {"partial", "ocr_partial", "needs_ocr"} and not blacklist.get("reviewed_full_document"):
            blockers.append("النص المستخرج من القائمة جزئي؛ أكد مراجعة أصل الوثيقة كاملاً قبل تقرير عدم الإدراج.")
    total = len(canonical) + 4
    completed += int(bool(any(d.get("category") == "contract" for d in documents) and any(d.get("category") == "supporting" for d in documents)))
    completed += int(bool(year and instruction_refs))
    completed += int(not quick_missing)
    completed += int(blacklist.get("status") in {"cleared", "confirmed_match"} and bool(blacklist.get("human_confirmed")))
    warnings = []
    try:
        contract_date = date.fromisoformat(case.get("contract_date", ""))
        for d in references:
            issued = d.get("issued_date") or d.get("effective_date")
            if issued and date.fromisoformat(issued) > contract_date:
                warnings.append(f'المرجع «{d.get("name", "")}» مؤرخ بعد تاريخ العقد ({issued})؛ يجب توثيق ملاءمته قبل تطبيقه.')
    except (ValueError, TypeError):
        pass
    return {"ready": not blockers, "blockers": blockers, "completed": min(completed, total), "total": total,
            "warnings": warnings, "quick_missing": quick_missing,
            "failed": sum(c.get("status") == "fail" for c in actual.values()),
            "meaning": "اكتمال التوثيق والمراجعة لا يعني سلامة العقد أو صدور اعتماد رسمي؛ تُظهر المخالفات المؤشرة في التقرير."}
