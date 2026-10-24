"""Regression checks for current-run provenance; all evidence is synthetic."""
import unittest

from backend.ai_reports import render_ai_report
from backend.automation import AuditManager
from tests.test_ai_reports import fixture as report_fixture
from tests import test_ai_workflow as workflow
from tests.test_ai_workflow import FakeAI, FakeSettings, LEGAL_TEXT


class CurrentRunPrecisionTests(unittest.TestCase):
    def setUp(self):
        self.data = workflow.AutomatedAuditWorkflowTests("test_uploaded_documents_run_all_nine_stages_and_preserve_supported_values")
        self.data.setUp()

    def tearDown(self):
        self.data.tearDown()

    def manager(self, client_class=FakeAI, extractor=None):
        manager = AuditManager(self.data.store, FakeSettings(), client_factory=client_class,
            extractor=extractor or self.data.extractor, blacklist_runner=self.data.blacklist, build_pdf=False)
        self.data.managers.append(manager)
        return manager

    def run_manager(self, manager):
        manager.start(self.data.case["id"])
        result = manager.wait(self.data.case["id"], timeout=20)
        self.assertEqual(result["job"]["status"], "completed", result["job"])
        return result

    def test_automatic_report_never_inherits_legacy_metadata_quick_or_tables(self):
        case, refs = report_fixture()
        case.update(title="LEGACY_SUBJECT_NOT_IN_CURRENT_RUN", amount="9999912345", contractor="LEGACY_CONTRACTOR")
        case["quick_form"].update(deep_risks="LEGACY_RISK", report_tables={
            "estimate_market_comparison": [{"details": "LEGACY_TABLE", "estimate": "9999912345"}]})
        case["automation"].update(facts={}, quick_form={}, report_tables={}, conflicts=[])
        html = render_ai_report(case, refs)
        for marker in ("LEGACY_SUBJECT_NOT_IN_CURRENT_RUN", "LEGACY_RISK", "LEGACY_TABLE", "LEGACY_CONTRACTOR", "9999912345"):
            self.assertNotIn(marker, html)
        self.assertIn("لم يثبت موضوع العقد", html)

    def test_later_reference_cannot_support_adverse_finding(self):
        self.data.store.delete_document(self.data.references["diwan"]["id"])
        self.data.document("ref-diwan", "diwan", LEGAL_TEXT, None, issued_date="2026-01-01")

        class AdverseAI(FakeAI):
            def complete(self, system, payload, schema, task="audit", images=None):
                result = super().complete(system, payload, schema, task, images)
                if task == "check_diwan":
                    for finding in result["findings"]:
                        finding["status"] = "fail"
                return result

        result = self.run_manager(self.manager(AdverseAI))
        diwan = [f for f in result["findings"] if f["step"] == "diwan"]
        self.assertTrue(diwan)
        self.assertTrue(all(f["status"] == "uncertain" for f in diwan))
        self.assertTrue(all(any("مؤرخ بعد العقد" in issue for issue in f["validation_issues"]) for f in diwan))

    def test_prior_generated_blacklist_snapshots_are_not_reclassified_as_new_inputs(self):
        snapshot = self.data.document("old-generated-snapshot", "blacklist", "OLD SNAPSHOT - NOT CONTRACT INPUT.",
            self.data.case["id"], automatic_blacklist_snapshot=True)
        visited = []
        def extract(document, cache_dir, **kwargs):
            visited.append(document["id"])
            return self.data.extractor(document, cache_dir, **kwargs)
        self.run_manager(self.manager(extractor=extract))
        self.assertNotIn(snapshot["id"], visited)
        self.assertEqual(self.data.store.document(snapshot["id"])["category"], "blacklist")

    def test_logical_pagination_is_persisted_without_pdf_page_anchor(self):
        self.data.store.update_document(self.data.contract["id"], {"page_count": None})
        def extract(document, cache_dir, **kwargs):
            result = self.data.extractor(document, cache_dir, **kwargs)
            if document["id"] == self.data.contract["id"]:
                result["pagination"] = "logical"
            return result
        self.run_manager(self.manager(extractor=extract))
        document = self.data.store.document(self.data.contract["id"])
        self.assertEqual(document["page_count"], 1)
        self.assertEqual(document["pagination"], "logical")
        case = self.data.store.get_case(self.data.case["id"])
        case["documents"] = self.data.store.documents(case["id"])
        html = render_ai_report(case, self.data.store.documents())
        self.assertIn("وحدة نصية", html)
        self.assertNotIn('/api/documents/contract/file#page=', html)
        self.assertIn('/api/documents/contract/file"', html)

    def test_rejected_metadata_date_does_not_fall_back_to_old_declared_date_for_law(self):
        self.data.store.mutate_case(self.data.case["id"], lambda case: case.update(contract_date="2024-05-01"))
        class RejectDateAI(FakeAI):
            def complete(self, system, payload, schema, task="audit", images=None):
                result = super().complete(system, payload, schema, task, images)
                if task == "review_metadata":
                    for review in result["reviews"]:
                        if review["id"] == "fact:contract_date":
                            review.update(verdict="unsupported", reason="تاريخ غير محسوم في بيانات الاختبار.")
                return result
        result = self.run_manager(self.manager(RejectDateAI))
        self.assertNotIn("contract_date", result["facts"])
        year = next(f for f in result["findings"] if f["id"] == "instructions_basis")
        self.assertEqual(year["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()
