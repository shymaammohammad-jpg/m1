"""Synthetic orchestration tests; fixture text is not legal authority.

No real provider, Ministry endpoint, user contract or secret is used. These
tests verify persistence, sequencing and evidence gates, not legal accuracy.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.ai_provider import AIProviderError
from backend.audit_engine import initial_checks
from backend.automation import AuditManager, STAGES, invalidate_ai_audit
from backend.storage import Store, now


CONTRACT_TEXT = """مستند اصطناعي للاختبار فقط وليس عقداً حقيقياً.
موضوع العقد: تجهيز معدات اختبارية.
رقم العقد: SYNTH-001.
الطرف المتعاقد: شركة الاختبار الاصطناعية.
الجهة المتعاقدة: جهة الاختبار الاصطناعية.
تاريخ العقد: 01/05/2024.
مبلغ العقد: 1,250,000 دينار عراقي.
الدليل الاصطناعي يؤيد استلام الوثائق المطلوبة في حالة الاختبار.
"""
SUPPORT_TEXT = "مرفق اصطناعي لاختبار نظام التدقيق، لا يمثل حقيقة أو مستنداً معتمداً."
LEGAL_TEXT = "مرجع اصطناعي للاختبار فقط وليس سنداً قانونياً. يتطلب سيناريو الاختبار توثيق الإجراءات بالمستندات."
EVIDENCE_QUOTE = "الدليل الاصطناعي يؤيد استلام الوثائق المطلوبة في حالة الاختبار."
REFERENCE_QUOTE = "مرجع اصطناعي للاختبار فقط وليس سنداً قانونياً."


def citation(document_id, quote=EVIDENCE_QUOTE, page=1):
    return {"document_id": document_id, "page": page, "quote": quote}


class FakeSettings:
    def settings_snapshot(self):
        return {"provider": "openai", "model": "synthetic-fixture-model", "api_key": "synthetic-never-sent"}


class FakeAI:
    """Rich, deterministic protocol fixture with injectable adverse responses."""

    def __init__(self, snapshot, *, bad_check=None, reject_review=None, failure_task=None,
                 map_started=None, map_release=None, metadata_conflict=False):
        self.settings = deepcopy(snapshot)
        self.bad_check = bad_check
        self.reject_review = reject_review
        self.failure_task = failure_task
        self.map_started, self.map_release = map_started, map_release
        self.metadata_conflict = metadata_conflict
        self.tasks = []

    def complete(self, system, payload, schema, task="audit", images=None):
        self.tasks.append(task)
        if task == self.failure_task:
            raise AIProviderError("تعذر الاتصال الاصطناعي بالخدمة.", "network")
        if task == "extract_contract":
            if self.map_started:
                self.map_started.set()
            if self.map_release:
                if not self.map_release.wait(10):
                    raise RuntimeError("Fixture release timeout")
            pages = payload["pages"]
            contract = next(page for page in pages if "SYNTH-001" in page["text"])
            doc_id = contract["document_id"]
            pairs = [
                ("title", "تجهيز معدات اختبارية", "موضوع العقد: تجهيز معدات اختبارية."),
                ("contract_number", "SYNTH-001", "رقم العقد: SYNTH-001."),
                ("contractor", "شركة الاختبار الاصطناعية", "الطرف المتعاقد: شركة الاختبار الاصطناعية."),
                ("entity", "جهة الاختبار الاصطناعية", "الجهة المتعاقدة: جهة الاختبار الاصطناعية."),
                ("contract_date", "2024-05-01", "تاريخ العقد: 01/05/2024."),
                ("amount", "1250000", "مبلغ العقد: 1,250,000 دينار عراقي."),
                ("currency", "IQD", "مبلغ العقد: 1,250,000 دينار عراقي."),
                ("contract_type", "goods", "موضوع العقد: تجهيز معدات اختبارية."),
            ]
            facts = [{"key": key, "value": value, "confidence": .97,
                      "citations": [citation(doc_id, quote)]} for key, value, quote in pairs]
            if self.metadata_conflict:
                facts.append({"key": "title", "value": "معدات اختبارية", "confidence": .96,
                              "citations": [citation(doc_id, "موضوع العقد: تجهيز معدات اختبارية.")]})
            documents = [{"document_id": page["document_id"],
                          "category": "contract" if page["document_id"] == doc_id else "supporting",
                          "reason": "تصنيف بيانات اصطناعية للفحص فقط.",
                          "citations": [citation(page["document_id"], page["text"].strip())]}
                         for page in pages]
            return {"facts": facts, "documents": documents}
        if task.startswith("check_"):
            contract = next(page for page in payload["pages"] if "SYNTH-001" in page["text"])
            references = payload["references"]
            results = []
            for check in payload["requirements"]:
                kind = "instructions" if check["id"] == "instructions_basis" else check["step"]
                if kind not in {"instructions", "diwan", "cabinet", "standard"}:
                    kind = "structure"
                reference = next(item for item in references if item["category"] == kind)
                proof = citation(contract["document_id"])
                if check["id"] == self.bad_check:
                    proof["page"] = 999
                results.append({"id": check["id"], "status": "pass",
                                "note": "نتيجة اصطناعية مسندة إلى بيانات الاختبار فقط.", "confidence": .95,
                                "evidence": [proof], "references": [citation(reference["id"], REFERENCE_QUOTE)],
                                "missing_documents": []})
            return {"findings": results}
        if task == "quick_form":
            contract = next(page for page in payload["pages"] if "SYNTH-001" in page["text"])
            fields = []
            for field in payload["fields"]:
                if field["key"] in {"auditor", "team_lead"}:
                    value = "اسم بشري مختلق يجب ألا يحفظه النظام"
                elif field["type"] == "select":
                    value = field["options"][0]["value"]
                else:
                    value = "بيان اصطناعي لاختبار انتقال البيانات فقط"
                fields.append({"key": field["key"], "value": value,
                               "note": "بيان اصطناعي لاختبار الاستمارة فقط.", "confidence": .95,
                               "citations": [citation(contract["document_id"])]})
            return {"fields": fields, "deep_risks": "فحص اصطناعي متعمق لا يمثل نتيجة عقد حقيقي.",
                    "clarification_requests": "طلبات اصطناعية فقط."}
        if task in {"review_metadata", "review_quick"}:
            items = payload.get("items") or payload.get("fields") or payload.get("facts") or []
            prefix = "fact:" if task == "review_metadata" else "quick:"
            if isinstance(items, dict):
                items = [{"id": prefix + key, **value} for key, value in items.items()]
            return {"reviews": [{"id": item.get("id") or prefix + item["key"],
                                 "verdict": "supported", "reason": "مراجعة مستقلة لبيانات اصطناعية فقط."}
                                for item in items]}
        if task == "independent_review":
            return {"reviews": [{"id": finding["id"],
                                  "verdict": "unsupported" if finding["id"] == self.reject_review else "supported",
                                  "reason": "لا يثبت الاقتباس هذا الحكم." if finding["id"] == self.reject_review else "مراجعة ثانية لبيانات اصطناعية فقط."}
                                 for finding in payload["findings"]]}
        if task == "report_summary":
            return {"summary": "اكتمل تحليل حالة الاختبار الاصطناعية؛ لا تمثل تدقيق عقد حقيقي أو موافقة عليه.",
                    "recommendations": ["توصية اصطناعية للاختبار."], "tables": []}
        if task == "vision_ocr":
            return {"text": CONTRACT_TEXT, "uncertain_fragments": []}
        raise AssertionError("Unexpected fixture task: " + task)


class AutomatedAuditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-ai-workflow-")
        self.root = Path(self.temp.name)
        self.store = Store(self.root)
        self.managers = []
        self.releases = []
        stamp = now()
        self.case = {"id": "synthetic-case", "title": "ملف مرفوع", "contract_number": "", "contractor": "",
                     "entity": "", "contract_date": None, "amount": "", "currency": "", "created_at": stamp,
                     "updated_at": stamp, "checks": initial_checks(), "quick_form": {}, "activity": [],
                     "blacklist": {"status": "pending"}}
        self.store.insert_case(self.case)
        self.contract = self.document("contract", "supporting", CONTRACT_TEXT, self.case["id"])
        self.support = self.document("support", "supporting", SUPPORT_TEXT, self.case["id"])
        self.references = {}
        for category in ("instructions", "diwan", "cabinet", "structure", "standard"):
            self.references[category] = self.document("ref-" + category, category, LEGAL_TEXT, None,
                                                     reference_year=2014 if category == "instructions" else None)

    def tearDown(self):
        for release in self.releases:
            release.set()
        for manager in self.managers:
            for event in list(manager._events.values()):
                event.set()
            manager._pool.shutdown(wait=True, cancel_futures=True)
        self.temp.cleanup()

    def document(self, doc_id, category, text, case_id, **metadata):
        path = self.store.uploads / (doc_id + ".txt")
        path.write_text(text, "utf-8")
        document = {"id": doc_id, "name": "وثيقة اختبار " + doc_id, "original_name": path.name,
                    "category": category, "size": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "page_count": 1,
                    "extraction_status": "text", "extracted_characters": len(text), "warnings": [],
                    "created_at": now(), "_text": text, "_path": str(path), **metadata}
        self.store.add_documents([document], case_id)
        return document

    def extractor(self, document, cache_dir, *, cancelled=None, progress=None, **kwargs):
        if progress:
            progress({"document_id": document["id"], "page": 1, "page_count": 1, "method": "text"})
        return {"document_id": document["id"], "name": document["name"], "category": document["category"],
                "sha256": document["sha256"], "page_count": 1,
                "pages": [{"page": 1, "text": document["_text"], "method": "text", "quality": 1}],
                "complete": True, "warnings": [], "unreadable_pages": [], "truncated": False,
                "pagination": "physical"}

    def blacklist(self, contractor, store, case_id, *, cancelled=None):
        return {"status": "unavailable", "note": "فشل اتصال اصطناعي؛ لا يعني خلو الشركة.",
                "source_url": "https://mop.gov.iq/", "checked_at": now(), "matches": [],
                "evidence_document_ids": [], "searched_sources": [], "limitations": [], "human_confirmed": False}

    def manager(self, **fake_options):
        clients = []
        def factory(settings):
            client = FakeAI(settings, **fake_options)
            clients.append(client)
            return client
        manager = AuditManager(self.store, FakeSettings(), client_factory=factory,
                               extractor=self.extractor, blacklist_runner=self.blacklist, build_pdf=False)
        manager.fixture_clients = clients
        self.managers.append(manager)
        return manager

    def run_case(self, **fake_options):
        manager = self.manager(**fake_options)
        manager.start(self.case["id"])
        result = manager.wait(self.case["id"], timeout=20)
        return manager, result, self.store.get_case(self.case["id"])

    def test_uploaded_documents_run_all_nine_stages_and_preserve_supported_values(self):
        manager, result, saved = self.run_case()
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        self.assertEqual(result["job"]["progress"], 100)
        self.assertEqual([s["id"] for s in result["job"]["stages"]], [key for key, title in STAGES])
        self.assertTrue(all(s["status"] in {"completed", "warning"} for s in result["job"]["stages"]))
        self.assertEqual(saved["contract_number"], "SYNTH-001")
        self.assertEqual(saved["amount"], "1250000")
        self.assertEqual(saved["contract_date"], "2024-05-01")
        self.assertEqual(saved["currency"], "IQD")
        self.assertEqual(self.store.document(self.contract["id"])["category"], "contract")
        self.assertEqual(len(result["findings"]), len(initial_checks()))
        self.assertTrue(all(f["evidence"] and f["references"] for f in result["findings"]))
        self.assertTrue(all(f.get("review") for f in result["findings"]))
        self.assertNotIn("auditor", result["quick_form"])
        self.assertNotIn("team_lead", result["quick_form"])
        self.assertEqual(result["blacklist"]["status"], "unavailable")
        self.assertFalse(result["blacklist"]["human_confirmed"])
        self.assertNotIn("synthetic-never-sent", str(result))
        tasks = manager.fixture_clients[0].tasks
        self.assertEqual(tasks[0], "extract_contract")
        self.assertIn("independent_review", tasks)
        self.assertEqual(tasks[-1], "report_summary")

    def test_nonexistent_evidence_page_cannot_be_promoted_by_supportive_second_model(self):
        _, result, saved = self.run_case(bad_check="program_04")
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        finding = next(f for f in result["findings"] if f["id"] == "program_04")
        self.assertEqual(finding["status"], "uncertain")
        self.assertTrue(finding["validation_issues"])
        self.assertEqual(finding["evidence"], [])
        self.assertEqual(next(c for c in saved["checks"] if c["id"] == "program_04")["status"], "pending")

    def test_independent_reviewer_can_reject_structurally_valid_claim(self):
        _, result, _ = self.run_case(reject_review="program_04")
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        finding = next(f for f in result["findings"] if f["id"] == "program_04")
        self.assertTrue(finding["evidence"] and finding["references"])
        self.assertEqual(finding["status"], "uncertain")
        self.assertEqual(finding["review"]["verdict"], "unsupported")
        self.assertIn("المراجعة الثانية", " ".join(finding["validation_issues"]))

    def test_provider_failure_is_persisted_as_failed_not_successful_audit(self):
        _, result, _ = self.run_case(failure_task="check_year")
        self.assertEqual(result["job"]["status"], "failed")
        self.assertEqual(result["job"]["stage"], "year")
        self.assertIn("اصطناعي", result["job"]["error"])
        self.assertLess(result["job"]["progress"], 100)
        self.assertFalse((self.root / "ai_reports").exists())

    def test_duplicate_start_is_rejected_and_cancellation_is_persisted(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        manager = self.manager(map_started=started, map_release=release)
        manager.start(self.case["id"])
        self.assertTrue(started.wait(5))
        with self.assertRaisesRegex(ValueError, "جار"):
            manager.start(self.case["id"])
        manager.cancel(self.case["id"])
        release.set()
        result = manager.wait(self.case["id"], timeout=10)
        self.assertEqual(result["job"]["status"], "cancelled")
        self.assertEqual(result["findings"], [])

    def test_material_edit_invalidates_active_job_before_it_can_complete(self):
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        manager = self.manager(map_started=started, map_release=release)
        manager.start(self.case["id"])
        self.assertTrue(started.wait(5))
        def edit(case):
            case["contract_number"] = "USER-EDIT"
            invalidate_ai_audit(case, "تغيير بيانات جوهرية")
        self.store.mutate_case(self.case["id"], edit)
        release.set()
        result = manager.wait(self.case["id"], timeout=10)
        self.assertTrue(result["stale"])
        self.assertEqual(result["job"]["status"], "cancelled")
        self.assertEqual(self.store.get_case(self.case["id"])["contract_number"], "USER-EDIT")

    def test_restart_marks_old_queued_job_interrupted_without_network_work(self):
        self.store.mutate_case(self.case["id"], lambda c: c.update(automation={"job": {"id": "old-job", "status": "queued"}}))
        manager = self.manager()
        manager.recover_interrupted()
        job = self.store.get_case(self.case["id"])["automation"]["job"]
        self.assertEqual(job["status"], "interrupted")
        self.assertTrue(job["finished_at"])
        self.assertEqual(manager.fixture_clients, [])

    def test_conflicting_source_supported_facts_are_reported_not_arbitrarily_chosen(self):
        _, result, saved = self.run_case(metadata_conflict=True)
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        self.assertNotIn("title", result["facts"])
        self.assertEqual(saved["title"], self.case["title"])
        self.assertEqual(result["conflicts"][0]["field"], "title")


class AutomaticAuditAPITests(unittest.TestCase):
    document = AutomatedAuditWorkflowTests.document
    extractor = AutomatedAuditWorkflowTests.extractor
    blacklist = AutomatedAuditWorkflowTests.blacklist
    manager = AutomatedAuditWorkflowTests.manager

    def setUp(self):
        AutomatedAuditWorkflowTests.setUp(self)
        self.environment = patch.dict(os.environ, {"OPENAI_API_KEY": "", "OPENAI_BASE_URL": "", "OPENAI_MODEL": "",
                                                   "AUDIT_DATA_DIR": str(self.root), "AUDIT_OCR_ON_UPLOAD": "0"})
        self.environment.start()
        self.api = importlib.import_module("backend.app")
        self.old_store, self.old_manager = self.api.STORE, self.api._AI_MANAGER
        self.api.STORE = self.store
        self.engine = self.manager()
        self.api._AI_MANAGER = self.engine
        self.context = TestClient(self.api.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.context.__exit__(None, None, None)
        self.api.STORE, self.api._AI_MANAGER = self.old_store, self.old_manager
        self.environment.stop()
        AutomatedAuditWorkflowTests.tearDown(self)

    def configure(self):
        response = self.client.put("/api/ai/settings", json={"provider": "openai", "model": "gpt-5.2",
                                                             "api_key": "synthetic-private-api-token"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["configured"])
        self.assertNotIn("synthetic-private-api-token", response.text)
        self.assertNotIn("api_key", response.json())

    def upload_and_finish(self):
        self.configure()
        response = self.client.post("/api/ai/audits", files=[
            ("files", ("synthetic-contract.txt", CONTRACT_TEXT.encode(), "text/plain")),
            ("files", ("synthetic-support.txt", SUPPORT_TEXT.encode(), "text/plain")),
        ])
        self.assertEqual(response.status_code, 202, response.text)
        case_id = response.json()["case_id"]
        result = self.engine.wait(case_id, timeout=20)
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        return case_id

    def test_one_multipart_upload_runs_audit_without_manual_metadata_and_exports_html(self):
        case_id = self.upload_and_finish()
        response = self.client.get(f"/api/cases/{case_id}")
        self.assertEqual(response.status_code, 200)
        case = response.json()
        self.assertEqual(case["contract_number"], "SYNTH-001")
        self.assertEqual(case["contract_date"], "2024-05-01")
        self.assertEqual(len(case["automation"]["job"]["stages"]), 9)
        self.assertFalse(case["readiness"]["ready"], "Manual final-approval rules must remain distinct")
        report = self.client.get(f"/api/cases/{case_id}/ai-report.html")
        self.assertEqual(report.status_code, 200, report.text[:1000])
        self.assertIn("text/html", report.headers["content-type"])
        self.assertIn("SYNTH-001", report.text)
        self.assertIn("اصطناعي", report.text)
        self.assertNotIn("synthetic-private-api-token", report.text)
        status = self.client.get(f"/api/cases/{case_id}/ai-audit")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "completed")

    def test_settings_are_write_only_and_unconfigured_upload_has_no_side_effects(self):
        # Local processing is configured without a key; this regression concerns
        # an explicitly selected cloud provider that still requires credentials.
        self.client.put("/api/ai/settings", json={"provider": "openai", "model": "gpt-5.2",
                         "base_url": "https://api.openai.com/v1", "clear_api_key": True})
        before = len(self.store.list_cases())
        response = self.client.post("/api/ai/audits", files={"files": ("contract.txt", CONTRACT_TEXT.encode())})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(len(self.store.list_cases()), before)
        self.configure()
        response = self.client.get("/api/ai/settings")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["key_configured"])
        self.assertNotIn("api_key", response.json())
        self.assertNotIn("synthetic-private-api-token", response.text)
        response = self.client.put("/api/ai/settings", json={"unknown": "value"})
        self.assertEqual(response.status_code, 422)
        response = self.client.put("/api/ai/settings", json={"api_key": "x" * 1001})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("x" * 100, response.text)

    def test_pdf_export_uses_ai_report_route_after_completed_job(self):
        case_id = self.upload_and_finish()
        content = b"%PDF-1.7\nSYNTHETIC PDF TRANSPORT FIXTURE\n%%EOF"
        with patch("backend.ai_reports.render_pdf", return_value=content) as render:
            response = self.client.get(f"/api/cases/{case_id}/ai-report.pdf")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.content, content)
        self.assertIn("application/pdf", response.headers["content-type"])
        self.assertIn("attachment", response.headers["content-disposition"])
        render.assert_called_once()

    def test_material_edit_invalidates_old_automatic_report(self):
        case_id = self.upload_and_finish()
        response = self.client.patch(f"/api/cases/{case_id}", json={"contract_number": "USER-REVISION"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["automation"]["stale"])
        response = self.client.get(f"/api/cases/{case_id}/ai-report.html")
        self.assertEqual(response.status_code, 409, response.text)
        response = self.client.get(f"/api/cases/{case_id}/ai-report.pdf")
        self.assertEqual(response.status_code, 409, response.text)

    def test_tampered_original_file_blocks_export_even_when_metadata_is_unchanged(self):
        case_id = self.upload_and_finish()
        document = self.store.document(self.store.documents(case_id)[0]["id"])
        Path(document["_path"]).write_text("ALTERED SYNTHETIC DOCUMENT", "utf-8")
        response = self.client.get(f"/api/cases/{case_id}/ai-report.html")
        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("بصمة", response.text)

    def test_new_reference_invalidates_previously_generated_automatic_report(self):
        case_id = self.upload_and_finish()
        response = self.client.post("/api/references", data={"category": "standard", "title": "مرجع اختباري مضاف"},
                                    files={"file": ("additional-standard.txt", LEGAL_TEXT.encode())})
        self.assertEqual(response.status_code, 201, response.text)
        response = self.client.get(f"/api/cases/{case_id}/ai-report.html")
        self.assertEqual(response.status_code, 409, response.text[:2000])

    def test_cross_origin_write_cannot_replace_ai_configuration(self):
        response = self.client.put("/api/ai/settings", headers={"Origin": "https://untrusted.invalid"},
                                   json={"provider": "openai", "model": "gpt-5.2", "api_key": "foreign-token"})
        self.assertEqual(response.status_code, 403, response.text)

    def test_rerun_duplicate_and_cancel_routes_operate_on_persisted_job(self):
        self.configure()
        started, release = threading.Event(), threading.Event()
        self.releases.append(release)
        self.engine = self.manager(map_started=started, map_release=release)
        self.api._AI_MANAGER = self.engine
        response = self.client.post(f"/api/cases/{self.case['id']}/ai-audit")
        self.assertEqual(response.status_code, 202, response.text)
        self.assertTrue(started.wait(5))
        duplicate = self.client.post(f"/api/cases/{self.case['id']}/ai-audit")
        self.assertEqual(duplicate.status_code, 409, duplicate.text)
        response = self.client.post(f"/api/cases/{self.case['id']}/ai-audit/cancel")
        self.assertEqual(response.status_code, 200, response.text)
        release.set()
        self.engine.wait(self.case["id"], timeout=10)
        status = self.client.get(f"/api/cases/{self.case['id']}/ai-audit")
        self.assertEqual(status.json()["status"], "cancelled")
        blocked = self.client.get(f"/api/cases/{self.case['id']}/ai-report.html")
        self.assertEqual(blocked.status_code, 409)


if __name__ == "__main__":
    unittest.main()
