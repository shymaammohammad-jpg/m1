"""Local Arabic contract audit service. Run with uvicorn backend.app:app."""
from __future__ import annotations

# Explorer and `python backend/app.py` do not establish a package context.
# Delegate before importing application dependencies or creating any data files.
if __name__ == "__main__" and not __package__:
    import runpy
    from pathlib import Path as _Path
    _launcher = _Path(__file__).resolve().parents[1] / "run.py"
    if not _launcher.is_file():
        raise SystemExit("Extract the ENTIRE ZIP first, then open start_windows.bat from the extracted folder.")
    runpy.run_path(str(_launcher), run_name="__main__")
    raise SystemExit

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import threading
from typing import Literal
import uuid

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .audit_engine import initial_checks, instruction_policy, readiness, valid_evidence_page
from .blacklist import OFFICIAL_NOTICE, OFFICIAL_SOURCES, check_blacklist, validate_official_url
from .extraction import MAX_EXPANDED, MAX_UPLOAD, create_document, save_upload
from .storage import Store, now
from .ai_provider import AIClient, AIProviderError, AISettingsStore
from .automation import AuditManager, invalidate_ai_audit

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("AUDIT_DATA_DIR", ROOT / "data"))
STORE = Store(DATA_DIR)
FRONTEND = ROOT / "frontend" / "dist"
log = logging.getLogger("audit")
_AI_MANAGER = None
_AI_MANAGER_LOCK = threading.RLock()


def ai_manager() -> AuditManager:
    global _AI_MANAGER
    with _AI_MANAGER_LOCK:
        if _AI_MANAGER is None or _AI_MANAGER.store is not STORE or _AI_MANAGER._closed:
            if _AI_MANAGER is not None:
                _AI_MANAGER.shutdown()
            _AI_MANAGER = AuditManager(STORE, AISettingsStore(STORE.root))
            _AI_MANAGER.recover_interrupted()
        return _AI_MANAGER
CATEGORIES = {"contract", "supporting", "diwan", "cabinet", "structure", "standard", "instructions", "report_template", "blacklist"}
STEPS = [
    {"id": "upload", "title": "رفع العقد والأوليات"},
    {"id": "year", "title": "تحديد التعليمات"},
    {"id": "diwan", "title": "إعمام الديوان"},
    {"id": "cabinet", "title": "إعمام مجلس الوزراء"},
    {"id": "structure", "title": "الهيكلية وبرنامج التدقيق"},
    {"id": "quick", "title": "استمارة الفحص السريع"},
    {"id": "standard", "title": "الوثائق القياسية"},
    {"id": "blacklist", "title": "القوائم السوداء"},
    {"id": "report", "title": "التقرير النهائي"},
]


def public_document(document: dict) -> dict:
    return {k: v for k, v in document.items() if not k.startswith("_")}


def import_references():
    folder = STORE.root / "reference_library"
    manifest = folder / "manifest.json"
    if not manifest.is_file():
        return
    try:
        items = json.loads(manifest.read_text("utf-8"))
        if not isinstance(items, list):
            raise ValueError("manifest must be a list")
        for item in items:
            source = (folder / item["filename"]).resolve()
            if not source.is_relative_to(folder.resolve()) or not source.is_file():
                raise ValueError("Reference source outside library or missing")
            text_source = None
            if item.get("text_filename"):
                text_source = (folder / item["text_filename"]).resolve()
                if not text_source.is_relative_to(folder.resolve()) or not text_source.is_file():
                    raise ValueError("Reference text outside library or missing")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            signature = f"{source.name}:{digest}"
            if STORE.reference_imported(signature):
                continue
            target = STORE.uploads / f"{uuid.uuid4().hex}{source.suffix.lower()}"
            shutil.copyfile(source, target)
            document = create_document(target, source.name, item["category"],
                                       reference_year=item.get("reference_year"), title=item.get("name"))
            if text_source:
                text = text_source.read_text("utf-8")[:2_000_000]
                document.update(_text=text, extracted_characters=len(text),
                                extraction_status=item.get("extraction_status", "partial" if item.get("text_complete") is False else "ocr"),
                                warnings=item.get("warnings", ["نص OCR مرجعي؛ تحقق من الصورة الأصلية عند الاقتباس"]))
            for key in ("effective_date", "issued_date", "source_number", "source_url", "description", "original_name", "extraction_note", "text_complete"):
                if key in item:
                    document[key] = item[key]
            STORE.add_documents([document], None)
            STORE.mark_imported(signature, document["id"])
    except Exception:
        log.exception("Could not import reference library")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import_references()
    ai_manager()
    try:
        yield
    finally:
        if _AI_MANAGER is not None:
            _AI_MANAGER.shutdown()


app = FastAPI(title="نظام تدقيق العقود الحكومية", version="2.1.1", lifespan=lifespan)


@app.middleware("http")
async def response_headers(request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        # This local service intentionally exposes no cross-origin API. Prevent browser drive-by writes.
        origin = request.headers.get("origin")
        if origin:
            from urllib.parse import urlsplit
            origin_host = urlsplit(origin).netloc
            if origin_host != request.headers.get("host") and origin_host not in {"localhost:5173", "127.0.0.1:5173"}:
                return JSONResponse({"detail": "طلب من مصدر غير مسموح"}, status_code=403)
        raw_length = request.headers.get("content-length", "0")
        try:
            if int(raw_length) > MAX_EXPANDED + 1024 * 1024:
                return JSONResponse({"detail": "حجم الطلب يتجاوز 250 ميغابايت"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "ترويسة حجم الطلب غير صالحة"}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if not request.url.path.startswith("/api/") and response.headers.get("content-type", "").startswith("text/html"):
        # The application executes its own local scripts only. Provider API
        # requests are made by the backend, never by browser-side third parties.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; connect-src 'self'; "
            "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
            "font-src 'self'; frame-src 'self' blob:; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


class ContractFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=2, max_length=500)
    contract_number: str = Field(default="", max_length=120)
    contractor: str = Field(default="", max_length=500)
    entity: str = Field(default="", max_length=500)
    contract_date: date | None = None
    amount: str = Field(default="", max_length=80)
    currency: str = Field(default="IQD", max_length=20)
    instruction_year_override: int | None = None
    instruction_override_reason: str = Field(default="", max_length=4000)

    @field_validator("instruction_year_override")
    @classmethod
    def valid_instruction_override(cls, value):
        if value is not None and value not in {2014, 2025}:
            raise ValueError("اختيار التعليمات الاستثنائي يجب أن يكون 2014 أو 2025 فقط")
        return value

    @field_validator("amount", mode="before")
    @classmethod
    def amount_is_numeric(cls, value):
        if value is None or value == "":
            return ""
        value = str(value)
        try:
            number = Decimal(value.replace(",", ""))
        except InvalidOperation:
            raise ValueError("قيمة العقد يجب أن تكون رقماً")
        if not number.is_finite() or number < 0:
            raise ValueError("قيمة العقد يجب أن تكون رقماً موجباً")
        return value

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if value is None:
            return value
        if len(value.strip()) < 2:
            raise ValueError("أدخل اسم العقد")
        return value.strip()


class ContractPatch(ContractFields):
    title: str | None = Field(default=None, min_length=2, max_length=500)
    contract_number: str | None = Field(default=None, max_length=120)
    contractor: str | None = Field(default=None, max_length=500)
    entity: str | None = Field(default=None, max_length=500)
    contract_date: date | None = None
    amount: str | None = Field(default=None, max_length=80)
    currency: str | None = Field(default=None, max_length=20)


class CheckPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "pass", "fail", "not_applicable"]
    note: str = Field(default="", max_length=12000)
    evidence_document_id: str | None = None
    evidence_page: str = Field(default="", max_length=120)
    reference_id: str | None = None
    legal_basis: str = Field(default="", max_length=4000)


class BlacklistRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_url: str | None = Field(default=None, max_length=2000)
    reference_document_id: str | None = None


class BlacklistPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["pending", "possible_match", "confirmed_match", "cleared", "unavailable"]
    note: str = Field(default="", max_length=12000)
    evidence_document_id: str | None = None
    source_url: str = Field(default="", max_length=2000)
    human_confirmed: bool = False
    reviewed_full_document: bool = False


def require_case(case_id: str) -> dict:
    case = STORE.get_case(case_id)
    if case is None:
        raise HTTPException(404, "ملف العقد غير موجود")
    return case


def serialize_case(case: dict) -> dict:
    case = dict(case)
    case["documents"] = STORE.documents(case["id"])
    auto = case.get("automation", {})
    if auto.get("job", {}).get("status") == "completed":
        from .automation import input_fingerprint
        if auto.get("input_fingerprint") != input_fingerprint(case, case["documents"], STORE.documents()):
            auto.update(stale=True, stale_reason="تغيرت بيانات العقد أو مكتبته المرجعية؛ أعد التدقيق الآلي.")
    policy = selected_instruction_policy(case)
    case.update(policy)
    case["readiness"] = readiness(case, STORE.documents())
    return case


def selected_instruction_policy(case: dict) -> dict:
    return instruction_policy(case.get("contract_date"),
                              override=case.get("instruction_year_override"),
                              override_reason=case.get("instruction_override_reason", ""))


def validate_instruction_override(case: dict):
    if case.get("instruction_year_override") is not None and not case.get("instruction_override_reason", "").strip():
        raise HTTPException(422, "اختيار سنة تعليمات استثنائية يتطلب سبباً وسنداً موثقاً من المدقق")


def audit_event(case: dict, action: str):
    case.setdefault("activity", []).append({"at": now(), "action": action})
    case["activity"] = case["activity"][-300:]


def validate_document(document_id: str | None, case_id: str, *, global_ok=False) -> dict | None:
    if not document_id:
        return None
    document = STORE.document(document_id)
    if not document or (document["_case_id"] != case_id and not (global_ok and document["_case_id"] is None)):
        raise HTTPException(422, "المستند المشار إليه غير موجود ضمن ملف العقد أو المراجع المسموحة")
    return document


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/bootstrap")
def bootstrap():
    from . import audit_engine
    return {"steps": STEPS, "checklist_template": initial_checks(), "references": STORE.documents(),
            "quick_form_schema": getattr(audit_engine, "QUICK_FORM_SCHEMA", []),
            "source_guidance": getattr(audit_engine, "SOURCE_GUIDANCE", {}),
            "blacklist_notice": OFFICIAL_NOTICE, "blacklist_sources": OFFICIAL_SOURCES,
            "limits": {"max_upload_mb": 100, "max_expanded_mb": 250, "max_zip_members": 200}}


@app.get("/api/cases")
def list_cases():
    return [serialize_case(case) for case in STORE.list_cases()]


@app.post("/api/cases", status_code=201)
def create_case(fields: ContractFields):
    stamp = now()
    validate_instruction_override(fields.model_dump())
    case = {**fields.model_dump(mode="json"), "id": uuid.uuid4().hex,
            "created_at": stamp, "updated_at": stamp, "checks": initial_checks(),
            "quick_form": {key: getattr(fields, key) for key in ("entity", "title", "contract_number", "amount")},
            "blacklist": {"status": "pending", "checked_at": None, "source_url": "", "note": "",
                          "evidence_document_id": None, "matches": [], "source_notice": OFFICIAL_NOTICE}, "activity": []}
    audit_event(case, "إنشاء ملف العقد")
    STORE.insert_case(case)
    return serialize_case(case)


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    return serialize_case(require_case(case_id))


@app.patch("/api/cases/{case_id}")
def update_case(case_id: str, fields: ContractPatch):
    existing = require_case(case_id)
    values = fields.model_dump(mode="json", exclude_unset=True)
    for key, value in values.items():
        if key not in {"contract_date", "instruction_year_override"} and value is None:
            raise HTTPException(422, "لا يمكن حفظ قيمة فارغة بهذا الحقل")
    validate_instruction_override({**existing, **values})

    def mutate(case):
        validate_instruction_override({**case, **values})
        changed_date = "contract_date" in values and values["contract_date"] != case.get("contract_date")
        changed_contractor = "contractor" in values and values["contractor"] != case.get("contractor")
        material_change = any(case.get(key) != value for key, value in values.items())
        case.update(values)
        for key in ("entity", "title", "contract_number", "amount"):
            if key in values:
                case.setdefault("quick_form", {})[key] = values[key]
        if material_change:
            invalidate_ai_audit(case, "تغيرت بيانات العقد؛ أعد التدقيق الآلي.")
            for check in case["checks"]:
                check["status"] = "pending"
            audit_event(case, "تغيير بيانات جوهرية بالعقد وإعادة فتح نتائج التدقيق")
        if changed_contractor or changed_date:
            case["blacklist"] = {"status": "pending", "checked_at": None, "source_url": "", "note": "تغير اسم الشركة أو تاريخ العقد؛ يجب إعادة التحقق",
                                 "evidence_document_id": None, "matches": [], "source_notice": OFFICIAL_NOTICE}
            for check in case["checks"]:
                if check.get("step") == "blacklist":
                    check["status"] = "pending"
            audit_event(case, "تغيير اسم الشركة وإعادة فتح فحص القوائم السوداء")
        audit_event(case, "تحديث بيانات العقد")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.post("/api/cases/{case_id}/documents")
def upload_documents(case_id: str, files: list[UploadFile] = File(...), category: str = Form("supporting")):
    require_case(case_id)
    if category not in CATEGORIES:
        raise HTTPException(422, "تصنيف المستند غير صالح")
    if len(files) > 30:
        raise HTTPException(422, "ارفع 30 ملفاً كحد أقصى في الطلب الواحد")
    documents = []
    try:
        for file in files:
            documents.extend(save_upload(file.file, file.filename or "document", STORE.uploads, category))
        if sum(doc["size"] for doc in documents) > MAX_EXPANDED:
            raise ValueError("إجمالي الملفات يتجاوز 250 ميغابايت")
        STORE.add_documents(documents, case_id)
    except (ValueError, OSError, RuntimeError) as exc:
        for doc in documents:
            Path(doc["_path"]).unlink(missing_ok=True)
        raise HTTPException(422, str(exc)) from None
    def mutate(case):
        invalidate_ai_audit(case, "أضيفت مستندات إلى ملف العقد؛ أعد التدقيق الآلي.")
        audit_event(case, f"إضافة {len(documents)} مستند في تصنيف {category}")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.get("/api/documents/{document_id}/file")
def download_document(document_id: str):
    document = STORE.document(document_id)
    if not document or not Path(document["_path"]).is_file():
        raise HTTPException(404, "المستند غير موجود")
    return FileResponse(document["_path"], filename=document.get("original_name", document["name"]),
                        content_disposition_type="inline")


@app.get("/api/documents/{document_id}/text")
def document_text(document_id: str):
    document = STORE.document(document_id)
    if not document:
        raise HTTPException(404, "المستند غير موجود")
    return {"text": document["_text"], "extraction_status": document["extraction_status"],
            "warnings": document["warnings"]}


@app.delete("/api/cases/{case_id}/documents/{document_id}")
def delete_document(case_id: str, document_id: str):
    require_case(case_id)
    document = validate_document(document_id, case_id)
    def mutate(case):
        invalidate_ai_audit(case, "حُذف مستند من ملف العقد؛ أعد التدقيق الآلي.")
        for check in case["checks"]:
            if check.get("evidence_document_id") == document_id or check.get("reference_id") == document_id:
                check.update(status="pending", evidence_document_id=None, reference_id=None)
        if case.get("blacklist", {}).get("evidence_document_id") == document_id:
            case["blacklist"].update(status="pending", evidence_document_id=None,
                                      human_confirmed=False, note="حُذف مستند التحقق؛ يلزم إعادة الفحص")
        audit_event(case, f"حذف المستند {document['name']} وإعادة فتح الفحوص المرتبطة به")
    STORE.mutate_case(case_id, mutate)
    STORE.delete_document(document_id)
    Path(document["_path"]).unlink(missing_ok=True)
    return serialize_case(require_case(case_id))


@app.patch("/api/cases/{case_id}/checks/{check_id}")
def update_check(case_id: str, check_id: str, fields: CheckPatch):
    case = require_case(case_id)
    check = next((c for c in case["checks"] if c["id"] == check_id), None)
    if not check:
        raise HTTPException(404, "بند التدقيق غير موجود")
    evidence = validate_document(fields.evidence_document_id, case_id)
    reference = validate_document(fields.reference_id, case_id, global_ok=True)
    if fields.status != "pending" and not fields.note.strip():
        raise HTTPException(422, "أدخل ملاحظة تسند نتيجة الفحص أو سبب عدم انطباقه")
    if fields.status in {"pass", "fail"}:
        if not evidence:
            raise HTTPException(422, "النتيجة تتطلب مستند إثبات من أوليات العقد")
        if not valid_evidence_page(fields.evidence_page, evidence):
            raise HTTPException(422, "حدد صفحة أو مدى صفحات صالحاً داخل حدود مستند الإثبات")
        if not reference or not fields.legal_basis.strip():
            raise HTTPException(422, "هذا الفحص يتطلب مرجعاً وسنداً قانونياً محدداً")
        required_category = {"diwan": "diwan", "cabinet": "cabinet", "standard": "standard"}.get(check.get("step"))
        if required_category and reference.get("category") != required_category:
            raise HTTPException(422, "تصنيف المرجع لا يطابق هذا البند؛ اختر أعمام الديوان أو مجلس الوزراء أو الوثيقة القياسية المناسبة")
        if check_id == "instructions_basis":
            selected = selected_instruction_policy(case)["instruction_year"]
            if reference.get("category") != "instructions" or not selected or str(reference.get("reference_year")) != str(selected):
                raise HTTPException(422, "يجب إسناد هذا الفحص إلى النص الرسمي لتعليمات السنة المختارة")
    if check_id == "instructions_basis" and fields.status == "not_applicable":
        raise HTTPException(422, "لا يجوز تجاوز تثبيت تعليمات السنة بغير منطبق")
    payload = fields.model_dump()
    def mutate(current):
        target = next(c for c in current["checks"] if c["id"] == check_id)
        target.update(payload, updated_at=now())
        audit_event(current, f"تحديث نتيجة الفحص: {target['title']}")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.patch("/api/cases/{case_id}/quick-form")
def update_quick_form(case_id: str, fields: dict = Body(...)):
    require_case(case_id)
    if len(fields) > 100:
        raise HTTPException(422, "عدد حقول الاستمارة يتجاوز الحد المسموح")
    tables = fields.get("report_tables")
    if tables is not None:
        if not isinstance(tables, dict) or len(json.dumps(tables, ensure_ascii=False)) > 300_000:
            raise HTTPException(422, "جداول التقرير غير صالحة أو تتجاوز الحجم المسموح")
        def validate_table_value(value, depth=0):
            if depth > 5:
                return False
            if isinstance(value, str):
                return len(value) <= 12000
            if value is None or isinstance(value, (int, float, bool)):
                return not isinstance(value, float) or value == value and abs(value) != float("inf")
            if isinstance(value, list):
                return len(value) <= 200 and all(validate_table_value(v, depth + 1) for v in value)
            if isinstance(value, dict):
                return len(value) <= 80 and all(isinstance(k, str) and len(k) <= 120 and validate_table_value(v, depth + 1) for k, v in value.items())
            return False
        if not validate_table_value(tables):
            raise HTTPException(422, "قيم جداول التقرير غير صالحة")
    for key, value in fields.items():
        if key == "report_tables":
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,79}", key) or not isinstance(value, (str, int, float, type(None))) or len(str(value)) > 12000:
            raise HTTPException(422, "حقل الاستمارة غير صالح")
    def mutate(case):
        case.setdefault("quick_form", {}).update({k: v if k == "report_tables" else str(v) if v is not None else "" for k, v in fields.items()})
        for check in case["checks"]:
            if check.get("step") in {"quick", "report"}:
                check["status"] = "pending"
        audit_event(case, "حفظ استمارة الفحص السريع")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.post("/api/cases/{case_id}/blacklist/check")
def run_blacklist_check(case_id: str, fields: BlacklistRequest):
    case = require_case(case_id)
    if not case.get("contractor", "").strip():
        raise HTTPException(422, "أدخل اسم الشركة قبل فحص القوائم السوداء")
    reference = validate_document(fields.reference_document_id, case_id, global_ok=True)
    if reference and reference["category"] != "blacklist":
        raise HTTPException(422, "اختر مستنداً مصنفاً قائمة سوداء")
    try:
        result = check_blacklist(case["contractor"], source_url=fields.source_url,
                                 reference_text=reference["_text"] if reference else None,
                                 reference_id=reference["id"] if reference else None)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if reference and reference.get("extraction_status") in {"ocr_partial", "partial", "needs_ocr", "failed", "unsupported"}:
        result["note"] += " استخراج هذا المستند غير كامل؛ لا يصلح وحده لإثبات عدم الإدراج."
        result["partial_source"] = True
    def mutate(current):
        current["blacklist"] = result
        for check in current["checks"]:
            if check.get("step") == "blacklist":
                check["status"] = "pending"
        audit_event(current, "تنفيذ بحث مرشحات القوائم السوداء؛ النتيجة تحتاج مراجعة بشرية")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.patch("/api/cases/{case_id}/blacklist")
def review_blacklist(case_id: str, fields: BlacklistPatch):
    require_case(case_id)
    document = validate_document(fields.evidence_document_id, case_id, global_ok=True)
    if fields.source_url:
        try:
            validate_official_url(fields.source_url, resolve_dns=False)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
    if fields.status in {"cleared", "confirmed_match"}:
        if not fields.human_confirmed or not fields.note.strip() or not document or not fields.source_url:
            raise HTTPException(422, "النتيجة النهائية تتطلب تأكيد المدقق وملاحظة ومستند إثبات ورابط المصدر الرسمي")
        if document["category"] != "blacklist":
            raise HTTPException(422, "مستند الإثبات يجب أن يكون مصنفاً قائمة سوداء")
        if fields.status == "cleared":
            if document.get("extraction_status") in {"failed", "unsupported"}:
                raise HTTPException(422, "تعذر قراءة مستند الإثبات؛ ارفع نسخة رسمية صالحة للمراجعة")
            if document.get("extraction_status") in {"ocr_partial", "partial", "needs_ocr"} and not fields.reviewed_full_document:
                raise HTTPException(422, "النص المستخرج غير كامل؛ أكد صراحة مراجعة أصل الوثيقة كاملاً أو ارفع نسخة نصية مكتملة")
    def mutate(case):
        case["blacklist"].update(fields.model_dump(), checked_at=now(), source_notice=OFFICIAL_NOTICE)
        audit_event(case, "حفظ مراجعة المدقق للقوائم السوداء")
    return serialize_case(STORE.mutate_case(case_id, mutate))


@app.get("/api/references")
def references():
    return STORE.documents()


@app.post("/api/references", status_code=201)
def upload_reference(file: UploadFile = File(...), category: str = Form(...), title: str = Form(""),
                     reference_year: int | None = Form(None), effective_date: str = Form(""),
                     source_number: str = Form("")):
    if category not in CATEGORIES - {"contract", "supporting"}:
        raise HTTPException(422, "تصنيف المرجع غير صالح")
    if reference_year is not None and not (1900 <= reference_year <= 2200):
        raise HTTPException(422, "سنة المرجع غير صالحة")
    if effective_date:
        try:
            date.fromisoformat(effective_date)
        except ValueError:
            raise HTTPException(422, "تاريخ نفاذ المرجع غير صالح") from None
    if (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(422, "ارفع المرجع كملف منفرد؛ أرشيف ZIP متاح ضمن أوليات العقد")
    try:
        documents = save_upload(file.file, file.filename or "reference", STORE.uploads, category)
        document = documents[0]
        document.update(reference_year=reference_year, effective_date=effective_date, source_number=source_number)
        if title.strip():
            document["name"] = title.strip()[:500]
        STORE.add_documents(documents, None)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(422, str(exc)) from None
    return public_document(document)


@app.get("/api/cases/{case_id}/report")
def report(case_id: str, format: Literal["html", "pdf"] = "html", final: bool = False):
    case = serialize_case(require_case(case_id))
    if final and not case["readiness"]["ready"]:
        raise HTTPException(409, {"message": "لا يمكن إصدار تقرير نهائي قبل استكمال الفحص", "blockers": case["readiness"]["blockers"]})
    from .reports import render_report, render_pdf
    html = render_report(case, STORE.documents(), final=final)
    if format == "html":
        return HTMLResponse(html)
    try:
        content = render_pdf(html)
    except RuntimeError as exc:
        log.exception("PDF rendering failed")
        raise HTTPException(503, str(exc)) from None
    except Exception:
        log.exception("PDF rendering failed")
        raise HTTPException(503, "تعذر إنشاء PDF حالياً؛ افتح نسخة HTML واطبعها إلى PDF") from None
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="audit-{case_id[:8]}.pdf"'})


@app.get("/api/ai/settings")
def get_ai_settings():
    try:
        return AISettingsStore(STORE.root).public_settings()
    except AIProviderError as exc:
        raise HTTPException(422, str(exc)) from None


@app.put("/api/ai/settings")
def put_ai_settings(values: dict = Body(...)):
    try:
        return AISettingsStore(STORE.root).update_settings(values)
    except AIProviderError as exc:
        raise HTTPException(422, str(exc)) from None


@app.post("/api/ai/test")
def test_ai_connection():
    try:
        return AIClient(AISettingsStore(STORE.root).settings_snapshot()).test_connection()
    except AIProviderError as exc:
        raise HTTPException(409 if exc.code == "not_configured" else 502, str(exc)) from None


@app.post("/api/ai/audits", status_code=202)
def create_automatic_audit(files: list[UploadFile] = File(...)):
    if not get_ai_settings()["configured"]:
        raise HTTPException(409, "أكمل إعداد مفتاح المزوّد السحابي المختار من إعداد الذكاء الاصطناعي أولاً.")
    if not 1 <= len(files) <= 30:
        raise HTTPException(422, "ارفع العقد والأوليات؛ الحد الأقصى 30 ملفًا أو أرشيف ZIP مدعوم.")
    documents, case_id = [], None
    try:
        for file in files:
            documents.extend(save_upload(file.file, file.filename or "document", STORE.uploads, "supporting"))
        if sum(d["size"] for d in documents) > MAX_EXPANDED:
            raise ValueError("إجمالي الملفات يتجاوز 250 ميغابايت")
        created = create_case(ContractFields(title="عقد قيد القراءة الآلية", currency=""))
        case_id = created["id"]
        STORE.add_documents(documents, case_id)
        job = ai_manager().start(case_id)
        return {"case_id": case_id, "job": job}
    except AIProviderError as exc:
        raise HTTPException(409 if exc.code == "not_configured" else 502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    finally:
        if case_id is None:
            for document in documents:
                Path(document["_path"]).unlink(missing_ok=True)


@app.get("/api/cases/{case_id}/ai-audit")
def get_automatic_audit(case_id: str):
    case = serialize_case(require_case(case_id))
    auto = case.get("automation", {})
    if not auto.get("job"):
        raise HTTPException(404, "لم يبدأ تدقيق آلي لهذا الملف بعد.")
    return {**auto["job"], "stale": auto.get("stale", False)}


@app.post("/api/cases/{case_id}/ai-audit", status_code=202)
def start_automatic_audit(case_id: str):
    require_case(case_id)
    try:
        return ai_manager().start(case_id)
    except AIProviderError as exc:
        raise HTTPException(409 if exc.code == "not_configured" else 502, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post("/api/cases/{case_id}/ai-audit/cancel")
def cancel_automatic_audit(case_id: str):
    require_case(case_id)
    return ai_manager().cancel(case_id)


def automatic_report_content(case_id: str, pdf=False):
    case = serialize_case(require_case(case_id))
    auto = case.get("automation", {})
    if auto.get("job", {}).get("status") != "completed":
        raise HTTPException(409, "التقرير الآلي متاح بعد اكتمال المعالجة فقط.")
    if auto.get("stale"):
        raise HTTPException(409, "تغيرت المدخلات؛ أعد التدقيق قبل إخراج تقرير النسخة الحالية.")
    for doc in [*case["documents"], *STORE.documents()]:
        original = STORE.document(doc["id"])
        path = Path(original["_path"])
        if not path.is_file() or path.is_symlink():
            raise HTTPException(409, "أصل أحد المستندات غير متاح؛ أعد رفعه والتدقيق.")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != original["sha256"]:
                raise HTTPException(409, "تغيرت بصمة مستند أصلي؛ أعد التدقيق على الأصل الحالي.")
    from .ai_reports import render_ai_report, render_pdf
    html = render_ai_report(case, STORE.documents())
    if not pdf:
        return HTMLResponse(html)
    cached = STORE.root / "ai_reports" / f"{auto['job']['id']}.pdf"
    if cached.is_file():
        content = cached.read_bytes()
    else:
        try:
            content = render_pdf(html)
        except Exception:
            raise HTTPException(503, "تعذر إنشاء PDF؛ افتح عرض التقرير واطبعه إلى PDF من المتصفح.") from None
    return Response(content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="raqib-ai-{case_id[:8]}.pdf"'})


@app.get("/api/cases/{case_id}/ai-report.html")
def automatic_report_html(case_id: str):
    return automatic_report_content(case_id)


@app.get("/api/cases/{case_id}/ai-report.pdf")
def automatic_report_pdf(case_id: str):
    return automatic_report_content(case_id, pdf=True)


@app.get("/api/{unmatched:path}")
def unknown_api(unmatched: str):
    raise HTTPException(404, "المسار المطلوب غير موجود")


@app.get("/{path:path}")
def frontend(path: str):
    resolved = (FRONTEND / path).resolve()
    if path and resolved.is_relative_to(FRONTEND.resolve()) and resolved.is_file():
        return FileResponse(resolved)
    index = FRONTEND / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<html lang='ar' dir='rtl'><meta charset='utf-8'><p>الواجهة قيد البناء. نفذ npm run build داخل frontend ثم أعد فتح الصفحة.</p></html>", status_code=503)
