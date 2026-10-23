# Government contract audit application

Arabic RTL React UI with FastAPI/SQLite, no cloud AI credentials required. Uploaded documents are untrusted source data. Legal findings are reviewed by a human and linked to source evidence. Do not invent statutory provisions or successful blacklist checks.

## Shared API (JSON)

All IDs are strings. Errors use `{detail: "Arabic explanation"}`. Base URL `/api`.

- `GET /health` returns `{status:"ok"}`.
- `GET /bootstrap` returns `{steps:[{id,title}], checklist_template:[...], references:[Document], limits:{max_upload_mb:100}}`.
- `GET /cases` returns `Case[]` (full Case objects acceptable).
- `POST /cases` accepts `{title,contract_number,contractor,entity,contract_date,amount,currency}` and returns Case. Currency defaults IQD. Date is ISO date.
- `GET /cases/{id}` and `PATCH /cases/{id}` return Case.
- `POST /cases/{id}/documents` multipart `files` (multiple), `category` string. Supports PDF, DOCX, TXT, images, ZIP. Returns updated Case. All contained ZIP files are categorized using supplied category. Apply safe ZIP limits and reject dangerous entries.
- `GET /documents/{id}/file` serves original document with safe content disposition.
- `GET /documents/{id}/text` returns `{text,extraction_status,warnings}`.
- `DELETE /cases/{id}/documents/{document_id}` returns Case; clear affected evidence links and invalidate check decisions.
- `PATCH /cases/{id}/checks/{check_id}` accepts `{status,note,evidence_document_id,evidence_page,reference_id,legal_basis}` and returns Case. Status is pending/pass/fail/not_applicable. Definitive decisions must require supporting notes and source evidence as appropriate.
- `PATCH /cases/{id}/quick-form` accepts object fields (see below) and returns Case.
- `POST /cases/{id}/blacklist/check` accepts `{source_url?,reference_document_id?}` and returns Case. Implement exact official evidence matching or manual verification as available; never mark cleared when source unavailable or incomplete.
- `PATCH /cases/{id}/blacklist` accepts `{status,note,evidence_document_id,source_url}` for reviewed evidence. Status is pending/possible_match/confirmed_match/cleared/unavailable. Cleared requires evidence and explicit human confirmation field `human_confirmed:true`.
- `GET /references` returns Document[]. `POST /references` multipart `file`, `category`, `title?`, `reference_year?` returns Document.
- `GET /cases/{id}/report?format=html&final=false` generates printable report preview. `format=pdf` generates downloadable PDF if renderer available. `final=true` must enforce readiness; `final=false` clearly watermarks draft.

`Case`: metadata above plus `{id,created_at,updated_at,instruction_year,default_instruction_year,year_warning,instruction_year_override:null|2014|2025,instruction_override_reason,documents:Document[],checks:Check[],quick_form:{...},blacklist:{status,checked_at,source_url,note,evidence_document_id,matches:[],human_confirmed,reviewed_full_document,source_notice},readiness:{ready:boolean,blockers:string[],completed:number,total:number},activity:[{at,action}]}`. Instruction override fields are accepted by POST/PATCH; a nonempty reason is mandatory for an override. This is needed because actual 2025 instructions Article42 binds effectiveness to90days after publication17Nov2025, and Article41 preserves2014 instructions for contracts concluded under them. The user's year rule remains the default and is not asserted to determine legal applicability by itself.

`Document`: `{id,name,category,size,sha256,page_count,extraction_status,extracted_characters,warnings:[],reference_year?,created_at}`. Status `text`, `ocr`, `needs_ocr`, `unsupported`, `failed` etc. No automatic approval for mere presence of files.

`Check`: `{id,step,title,description,source_name?,source_page?,status,note,evidence_document_id,evidence_page,reference_id,legal_basis}`. Steps in order: upload,year,diwan,cabinet,structure,quick,standard,blacklist,report.

Quick form initially includes `project_name`, `location`, `funding`, `procurement_method`, `estimated_cost`, `contract_amount`, `duration`, `announcement_date`, `award_date`, `signature_date`, `guarantee`, `committee`, `notes`, `auditor`, `audit_date`. Add real source form fields when PDF analysis arrives.

## Module ownership

- Backend agent: `backend/app.py`, storage/extraction/blacklist modules, Python dependency file; app creates/updates cases, serves built frontend, lifespan initializes reference library. Import audit engine from `backend.audit_engine` with `initial_checks()`, `instruction_policy(date)`, `readiness(case, references)`; report from `backend.reports` with `render_report(case, references, final=False) -> str` and `render_pdf(html) -> bytes`.
- Root: `backend/audit_engine.py`, tests, README, configuration, reference import, integration.
- Frontend agent: `frontend/` only, Vite React, Arabic polished RTL interface; package/lock/build. Use API contract without inventing functionality.
- Report specialist: reference analysis first, then `backend/reports.py` after follow-up.

Data directory defaults `/workspace/m1/data`, overridable by `AUDIT_DATA_DIR` for isolated tests. References supplied by user will be copied to `data/reference_library` with a manifest by root. Do not modify or delete user supplied originals.
