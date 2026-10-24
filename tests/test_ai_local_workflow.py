"""Local-model orchestration regressions using inert synthetic fixtures.

No Ollama model is downloaded or evaluated here. The budget fixture checks the
actual wire-message byte bound; it does not claim model or legal accuracy.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
import unittest
from unittest.mock import patch

import test_ai_workflow as workflow

from backend.ai_documents import cached_extract_document
from backend.ai_provider import AIProviderError, _DOCUMENT_BOUNDARY
from backend.ai_reports import render_ai_report
from backend.automation import AuditManager, STAGES


class LocalSettings:
    def settings_snapshot(self):
        return {"provider": "ollama", "model": "qwen2.5:3b",
                "base_url": "http://127.0.0.1:11434", "api_key": ""}


class BudgetFakeAI(workflow.FakeAI):
    """A protocol fixture that refuses the real local provider's byte overflow."""

    def __init__(self, settings, **kwargs):
        super().__init__(settings, **kwargs)
        self.byte_sizes = []
        self.mapped_document_ids = set()

    def complete(self, system, payload, schema, task="audit", images=None):
        wire = json.dumps({"task": str(task)[:100], "data": payload}, ensure_ascii=False,
                          allow_nan=False)
        size = len((system + _DOCUMENT_BOUNDARY).encode("utf-8")) + len(wire.encode("utf-8"))
        self.byte_sizes.append((task, size))
        if size > 10000:
            raise AIProviderError("Synthetic local context exceeded: " + task + ": " + str(size),
                                  "local_context_limit")
        if task == "extract_contract":
            self.mapped_document_ids.update(p["document_id"] for p in payload["pages"])
        return super().complete(system, payload, schema, task=task, images=images)


class LocalWorkflowPrecisionTests(unittest.TestCase):
    setUp = workflow.AutomatedAuditWorkflowTests.setUp
    tearDown = workflow.AutomatedAuditWorkflowTests.tearDown
    document = workflow.AutomatedAuditWorkflowTests.document
    extractor = workflow.AutomatedAuditWorkflowTests.extractor
    blacklist = workflow.AutomatedAuditWorkflowTests.blacklist

    def local_manager(self, *, client_type=BudgetFakeAI, extractor=None):
        clients = []
        def factory(settings):
            client = client_type(settings)
            clients.append(client)
            return client
        manager = AuditManager(self.store, LocalSettings(), client_factory=factory,
                               extractor=extractor or self.extractor,
                               blacklist_runner=self.blacklist, build_pdf=False)
        manager.fixture_clients = clients
        self.managers.append(manager)
        return manager

    def finish(self, **kwargs):
        manager = self.local_manager(**kwargs)
        manager.start(self.case["id"])
        result = manager.wait(self.case["id"], timeout=30)
        return manager, result

    def test_local_nine_stage_run_stays_within_actual_8gb_message_budget(self):
        manager, result = self.finish()
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        self.assertEqual([s["id"] for s in result["job"]["stages"]], [s[0] for s in STAGES])
        self.assertEqual(result["job"]["provider"], "ollama")
        self.assertEqual(result["job"]["model"], "qwen2.5:3b")
        sizes = manager.fixture_clients[0].byte_sizes
        self.assertTrue(sizes)
        self.assertLessEqual(max(size for _, size in sizes), 10000, sizes)
        self.assertLessEqual(result["job"]["requests"], 180)
        self.assertNotIn("api_key", str(result))
        self.assertEqual(result["facts"]["contract_number"]["value"], "SYNTH-001")

    def test_unconfirmed_previous_values_never_reappear_in_current_automatic_report(self):
        old = "LEGACY_UNSUPPORTED_SENTINEL"
        case = {**deepcopy(self.case), "title": old, "entity": old, "contractor": old,
                "amount": "987654321", "documents": [],
                "quick_form": {"quick_req_01": "fulfilled", "quick_req_01_note": old,
                               "report_tables": {"evaluation_notes": [{"company": old, "observation": old}]}},
                "automation": {"job": {"status": "completed", "id": "current-synthetic"},
                               "facts": {}, "quick_form": {}, "report_tables": {}, "findings": []}}
        report = render_ai_report(case, [])
        self.assertNotIn(old, report)
        self.assertNotIn("987654321", report)
        self.assertIn("لم يثبت موضوع العقد", report)

    def test_native_text_extraction_persists_logical_citation_addresses(self):
        # Original text uploads have no physical PDF page count. The real page
        # extractor must persist a logical address before the renderer uses it.
        self.store.update_document(self.contract["id"], {"page_count": None})
        manager, result = self.finish(extractor=cached_extract_document)
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        original = self.store.document(self.contract["id"])
        self.assertEqual(original["pagination"], "logical")
        self.assertEqual(original["page_count"], 1)
        saved = self.store.get_case(self.case["id"])
        saved["documents"] = self.store.documents(self.case["id"])
        report = render_ai_report(saved, self.store.documents())
        self.assertIn("وحدة نصية", report)
        self.assertIn('/api/documents/contract/file"', report)
        self.assertNotIn('/api/documents/contract/file#page=', report)

    def test_prior_automatic_blacklist_snapshots_are_not_contract_input(self):
        self.document("prior-blacklist", "blacklist", workflow.CONTRACT_TEXT,
                      self.case["id"], automatic_blacklist_snapshot=True)
        manager, result = self.finish()
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        mapped = manager.fixture_clients[0].mapped_document_ids
        self.assertIn(self.contract["id"], mapped)
        self.assertNotIn("prior-blacklist", mapped)
        coverage = {d["document_id"] for d in result["coverage"]}
        self.assertNotIn("prior-blacklist", coverage)

    def test_malformed_request_limit_cannot_leave_a_job_running(self):
        with patch.dict(os.environ, {"AUDIT_AI_MAX_REQUESTS": "not-a-number"}):
            _, result = self.finish()
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        self.assertTrue(result["job"]["finished_at"])

    def test_large_local_dossier_discloses_map_limit_without_blanket_passes(self):
        # A fully extracted source can still exceed the model's per-run reading
        # allowance. That distinction must be visible, not reported as all-clear.
        self.store.delete_document(self.contract["id"])
        self.contract = self.document("contract", "supporting", workflow.CONTRACT_TEXT * 300,
                                      self.case["id"])
        manager, result = self.finish()
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        self.assertTrue(any("حد القراءة التفصيلية" in note for note in result["limitations"]))
        self.assertTrue(all(f["status"] == "uncertain" for f in result["findings"]))
        self.assertLessEqual(result["job"]["requests"], 180)
        self.assertLessEqual(max(size for _, size in manager.fixture_clients[0].byte_sizes), 10000)

    def test_future_circular_cannot_support_a_legal_failure_for_an_older_contract(self):
        self.store.delete_document(self.references["diwan"]["id"])
        self.document("future-diwan", "diwan", workflow.LEGAL_TEXT, None,
                      issued_date="2026-08-17")
        class AdverseFake(BudgetFakeAI):
            def complete(self, system, payload, schema, task="audit", images=None):
                result = super().complete(system, payload, schema, task, images)
                if task == "check_diwan":
                    for finding in result["findings"]:
                        finding["status"] = "fail"
                return result
        _, result = self.finish(client_type=AdverseFake)
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        findings = [f for f in result["findings"] if f["step"] == "diwan"]
        self.assertTrue(findings)
        self.assertTrue(all(f["status"] == "uncertain" for f in findings))
        self.assertTrue(all(any("مؤرخ بعد العقد" in issue for issue in f["validation_issues"])
                            for f in findings))


if __name__ == "__main__":
    unittest.main()
