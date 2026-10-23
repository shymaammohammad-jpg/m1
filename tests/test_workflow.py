"""Isolated API scenarios using synthetic evidence, never the user's originals.

Run from the repository root with ``python -m unittest discover -s tests -v``.
The fixture documents below are invented test data and carry no legal authority.
"""
from __future__ import annotations

from datetime import date, timedelta
from html import escape
import importlib
from io import BytesIO
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient
import httpx
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


ROOT = Path(__file__).resolve().parents[1]
STRUCTURE = json.loads((ROOT / "reference_structure.json").read_text("utf-8"))
OFFICIAL_FIXTURE_URL = "https://mop.gov.iq/synthetic-test-fixture-not-a-real-list.pdf"
CONTRACTOR = "شركة الأمل للتجارة العامة"


def synthetic_pdf(pages=2, text="SYNTHETIC TEST EVIDENCE - NOT AN ACTUAL CONTRACT"):
    writer = PdfWriter()
    for number in range(1, pages + 1):
        page = writer.add_blank_page(width=595, height=842)
        if text:
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 11 Tf 40 780 Td ({text} - page {number}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def synthetic_zip(entries, *, compression=zipfile.ZIP_STORED):
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=compression) as archive:
        for name, contents in entries:
            archive.writestr(name, contents)
    return output.getvalue()


class AuditWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="synthetic-audit-test-")
        self.data = Path(self.directory.name)
        self.environ = patch.dict(os.environ, {"AUDIT_DATA_DIR": str(self.data), "AUDIT_OCR_ON_UPLOAD": "0"})
        self.environ.start()
        self.api = importlib.import_module("backend.app")
        self.old_store = self.api.STORE
        from backend.storage import Store
        self.api.STORE = Store(self.data)
        self.client_context = TestClient(self.api.app)
        self.client = self.client_context.__enter__()

    def tearDown(self):
        self.client_context.__exit__(None, None, None)
        self.api.STORE = self.old_store
        self.environ.stop()
        self.directory.cleanup()

    def request_json(self, method, path, expected=200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, expected, response.text[:3000])
        return response.json()

    def create_case(self, **changes):
        fields = dict(title="عقد اختباري اصطناعي", contract_number="SYNTHETIC-001",
                      contractor=CONTRACTOR, entity="جهة اختبار اصطناعية", contract_date="2025-06-01",
                      amount="1250000", currency="IQD")
        fields.update(changes)
        return self.request_json("POST", "/api/cases", expected=201, json=fields)

    def get_case(self, case_id):
        return self.request_json("GET", f"/api/cases/{case_id}")

    def upload(self, case_id, category="supporting", name="synthetic-evidence.pdf", content=None):
        if content is None:
            content = synthetic_pdf()
        result = self.request_json("POST", f"/api/cases/{case_id}/documents",
                                   files={"files": (name, content)}, data={"category": category})
        return next(d for d in reversed(result["documents"]) if d["original_name"] == name)

    def reference(self, category, *, year=None, name=None, content=None, suffix=".txt"):
        name = name or f"synthetic-{category}{suffix}"
        content = content if content is not None else ("SYNTHETIC TEST REFERENCE - NOT LEGAL AUTHORITY. " * 4).encode()
        fields = {"category": category, "title": name}
        if year is not None:
            fields["reference_year"] = str(year)
        return self.request_json("POST", "/api/references", expected=201,
                                 files={"file": (name, content)}, data=fields)

    def decision(self, case_id, check_id, evidence, reference, **changes):
        fields = dict(status="pass", note="نتيجة اصطناعية لا تمثل تدقيق عقد حقيقي",
                      evidence_document_id=evidence["id"], evidence_page="1",
                      reference_id=reference["id"], legal_basis="Synthetic fixture only, paragraph 1, page 1")
        fields.update(changes)
        return self.request_json("PATCH", f"/api/cases/{case_id}/checks/{check_id}", json=fields)

    def complete_quick_form(self, case):
        schema = self.request_json("GET", "/api/bootstrap")["quick_form_schema"]
        fields = {}
        for section in schema:
            for field in section["fields"]:
                if not field["required"]:
                    continue
                if field["key"] in {"title", "entity", "contract_number", "amount"}:
                    fields[field["key"]] = case[field["key"]]
                elif field["type"] == "select":
                    fields[field["key"]] = field["options"][0]["value"]
                elif field["type"] == "date":
                    fields[field["key"]] = "2025-06-02"
                else:
                    fields[field["key"]] = "بيان اختباري اصطناعي"
        return fields

    def reviewed_blacklist(self, case_id, document, **changes):
        fields = dict(status="cleared", note="مراجعة بشرية اصطناعية لبيانات الاختبار فقط",
                      evidence_document_id=document["id"], source_url=OFFICIAL_FIXTURE_URL,
                      human_confirmed=True)
        fields.update(changes)
        return self.request_json("PATCH", f"/api/cases/{case_id}/blacklist", json=fields)

    def complete_reviewed_case(self):
        """A documented *test* review, with an adverse finding, is not approval."""
        case = self.create_case(title='عقد اصطناعي <script>alert("title")</script>')
        case_id = case["id"]
        evidence = self.upload(case_id, "contract")
        self.upload(case_id, "supporting", name="synthetic-support.txt", content=b"Synthetic supporting record only.")
        references = {category: self.reference(category, year=2025 if category == "instructions" else None)
                      for category in ("instructions", "diwan", "cabinet", "structure", "standard", "blacklist")}
        self.request_json("PATCH", f"/api/cases/{case_id}/quick-form", json={
            **self.complete_quick_form(case),
            "report_tables": {"evaluation_notes": [{"company": CONTRACTOR, "observation": '<img src=x onerror=alert("table")>'}]},
        })
        self.reviewed_blacklist(case_id, references["blacklist"])
        for check in case["checks"]:
            category = "instructions" if check["id"] == "instructions_basis" else check["step"]
            reference = references.get(category, references["structure"])
            self.decision(case_id, check["id"], evidence, reference,
                          status="fail" if check["id"] == "program_04" else "pass",
                          note='SYNTHETIC ADVERSE FINDING <script>alert("finding")</script>'
                          if check["id"] == "program_04" else "مراجعة اختبارية موثقة؛ ليست نتيجة عقد حقيقي")
        return self.get_case(case_id)

    def test_bootstrap_preserves_source_form_and_step_order(self):
        self.assertEqual(self.request_json("GET", "/api/health"), {"status": "ok"})
        bootstrap = self.request_json("GET", "/api/bootstrap")
        self.assertEqual([x["id"] for x in bootstrap["steps"]],
                         ["upload", "year", "diwan", "cabinet", "structure", "quick", "standard", "blacklist", "report"])
        fields = [f for section in bootstrap["quick_form_schema"] for f in section["fields"]]
        req = [f for f in fields if f["key"].startswith("quick_req_") and f["type"] == "select"]
        risk = [f for f in fields if f["key"].startswith("quick_risk_") and f["type"] == "select"]
        self.assertEqual(len(req), 14)
        self.assertEqual(len(risk), 17)
        self.assertEqual({x["key"] for x in req}, {x["id"] for x in STRUCTURE["quick_form"]["requirements"]})
        self.assertEqual({x["key"] for x in risk}, {x["id"] for x in STRUCTURE["quick_form"]["risks"]})
        self.assertFalse(any(x["label"].startswith("5.") for x in risk), "The source omits risk number five")
        self.assertEqual(bootstrap["references"], [], "Tests must not import the user's actual references")

    def test_metadata_validation_year_selection_and_persistence(self):
        for fields in ({"amount": "NaN"}, {"amount": "-1"}, {"title": "  "}, {"contract_date": "2025-02-30"}):
            with self.subTest(fields=fields):
                response = self.client.post("/api/cases", json={"title": "عقد اختباري", **fields})
                self.assertEqual(response.status_code, 422)
        for stamp, year in (("2024-12-31", 2014), ("2025-01-01", 2025), ("2023-12-31", None),
                            ((date.today() + timedelta(days=366)).isoformat(), None), (None, None)):
            with self.subTest(contract_date=stamp):
                case = self.create_case(contract_date=stamp)
                self.assertEqual(case["instruction_year"], year)
                self.assertEqual(self.get_case(case["id"])["instruction_year"], year)
                self.assertTrue(case["year_warning"])
        case = self.create_case(amount="1,250,000")
        cases = self.request_json("GET", "/api/cases")
        self.assertIn(case["id"], [item["id"] for item in cases])
        self.assertEqual(self.get_case(case["id"])["amount"], "1,250,000")

    def test_upload_preserves_original_and_safe_zip_documents(self):
        case = self.create_case()
        body = synthetic_pdf()
        document = self.upload(case["id"], "contract", content=body)
        self.assertEqual(document["page_count"], 2)
        self.assertEqual(len(document["sha256"]), 64)
        original = self.client.get(f"/api/documents/{document['id']}/file")
        self.assertEqual(original.content, body)
        self.assertIn("inline", original.headers["content-disposition"])
        extracted = self.request_json("GET", f"/api/documents/{document['id']}/text")
        self.assertEqual(extracted["extraction_status"], "text")
        self.assertIn("SYNTHETIC TEST EVIDENCE", extracted["text"])
        archive = synthetic_zip([("folder/one.txt", b"Synthetic supporting record one."),
                                 ("folder/two.txt", b"Synthetic supporting record two.")])
        uploaded = self.request_json("POST", f"/api/cases/{case['id']}/documents",
                                     files={"files": ("synthetic-safe.zip", archive)}, data={"category": "supporting"})
        support = [d for d in uploaded["documents"] if d["category"] == "supporting"]
        self.assertEqual({d["name"] for d in support}, {"one.txt", "two.txt"})
        self.assertTrue(all(c["status"] == "pending" for c in uploaded["checks"]))

    def test_unsafe_archives_rejected_atomically(self):
        case = self.create_case()
        link = zipfile.ZipInfo("synthetic-link.txt")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archives = {
            "traversal": synthetic_zip([("valid.txt", b"safe first file"), ("../outside.txt", b"unsafe")]),
            "absolute": synthetic_zip([("/tmp/synthetic-outside.txt", b"unsafe")]),
            "windows": synthetic_zip([("C:\\outside.txt", b"unsafe")]),
            "symlink": synthetic_zip([(link, b"/etc/passwd")]),
            "nested": synthetic_zip([("nested.zip", b"not allowed")]),
            "member_limit": synthetic_zip([(f"synthetic-{i}.txt", b"x") for i in range(201)]),
            "compression_bomb": synthetic_zip([("bomb.txt", b"A" * 400000)], compression=zipfile.ZIP_DEFLATED),
        }
        for label, archive in archives.items():
            with self.subTest(label=label):
                response = self.client.post(f"/api/cases/{case['id']}/documents",
                                            files={"files": ("synthetic-unsafe.zip", archive)}, data={"category": "supporting"})
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(self.get_case(case["id"])["documents"], [])
                self.assertEqual(list((self.data / "uploads").iterdir()), [], "Rejected archives must leave no extracted files")

    def test_definitive_checks_require_scoped_evidence_page_and_correct_reference(self):
        case = self.create_case()
        other_case = self.create_case()
        evidence = self.upload(case["id"], "contract")
        foreign_evidence = self.upload(other_case["id"], "contract")
        diwan = self.reference("diwan")
        standard = self.reference("standard")
        base = dict(status="pass", note="ملاحظة اختبارية موثقة", evidence_document_id=evidence["id"],
                    evidence_page="1", reference_id=diwan["id"], legal_basis="Synthetic fixture, page 1")
        invalid = [{"note": ""}, {"evidence_document_id": None}, {"reference_id": None}, {"legal_basis": ""},
                   {"evidence_document_id": foreign_evidence["id"]}, {"reference_id": standard["id"]}]
        invalid += [{"evidence_page": page} for page in ("0", "3", "2-1", "1-3", "page one", "")]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = self.client.patch(f"/api/cases/{case['id']}/checks/diwan_applicability", json={**base, **changes})
                self.assertEqual(response.status_code, 422, response.text)
        saved = self.decision(case["id"], "diwan_applicability", evidence, diwan, evidence_page="1-2")
        check = next(c for c in saved["checks"] if c["id"] == "diwan_applicability")
        self.assertEqual((check["status"], check["evidence_page"]), ("pass", "1-2"))
        self.assertEqual(next(c for c in self.get_case(case["id"])["checks"] if c["id"] == check["id"])["reference_id"], diwan["id"])

    def test_instruction_basis_cannot_use_wrong_year_or_be_waived(self):
        case = self.create_case(contract_date="2024-09-01")
        evidence = self.upload(case["id"], "contract")
        wrong = self.reference("instructions", year=2025)
        correct = self.reference("instructions", year=2014)
        for fields in ({"status": "not_applicable", "note": "اختبار عدم الانطباق"},
                       {"status": "pass", "note": "اختبار سنة خاطئة", "evidence_document_id": evidence["id"],
                        "evidence_page": "1", "reference_id": wrong["id"], "legal_basis": "Synthetic reference"}):
            response = self.client.patch(f"/api/cases/{case['id']}/checks/instructions_basis", json=fields)
            self.assertEqual(response.status_code, 422, response.text)
        saved = self.decision(case["id"], "instructions_basis", evidence, correct)
        self.assertEqual(next(c for c in saved["checks"] if c["id"] == "instructions_basis")["status"], "pass")

    def test_material_metadata_change_reopens_checks_and_contractor_change_reopens_blacklist(self):
        case = self.create_case()
        evidence = self.upload(case["id"], "contract")
        reference = self.reference("structure")
        blacklist = self.reference("blacklist")
        self.decision(case["id"], "file_scope", evidence, reference)
        self.reviewed_blacklist(case["id"], blacklist)
        updated = self.request_json("PATCH", f"/api/cases/{case['id']}", json={"amount": "1500000"})
        self.assertTrue(all(c["status"] == "pending" for c in updated["checks"]))
        self.assertEqual(updated["quick_form"]["amount"], "1500000")
        updated = self.request_json("PATCH", f"/api/cases/{case['id']}", json={"contractor": "شركة اختبار أخرى"})
        self.assertEqual(updated["blacklist"]["status"], "pending")
        self.assertIsNone(updated["blacklist"]["evidence_document_id"])
        self.assertIsNone(updated["blacklist"]["checked_at"])

    def test_deleting_evidence_invalidates_decisions_and_blacklist_confirmation(self):
        case = self.create_case()
        evidence = self.upload(case["id"], "contract")
        reference = self.reference("structure")
        self.decision(case["id"], "file_scope", evidence, reference)
        updated = self.request_json("DELETE", f"/api/cases/{case['id']}/documents/{evidence['id']}")
        check = next(c for c in updated["checks"] if c["id"] == "file_scope")
        self.assertEqual(check["status"], "pending")
        self.assertIsNone(check["evidence_document_id"])
        self.assertEqual(self.client.get(f"/api/documents/{evidence['id']}/file").status_code, 404)
        blacklist = self.upload(case["id"], "blacklist", name="synthetic-blacklist.txt", content=b"Synthetic full blacklist fixture; no actual legal authority.")
        self.reviewed_blacklist(case["id"], blacklist)
        updated = self.request_json("DELETE", f"/api/cases/{case['id']}/documents/{blacklist['id']}")
        self.assertEqual(updated["blacklist"]["status"], "pending")
        self.assertFalse(updated["blacklist"]["human_confirmed"])

    def test_quick_form_conflicts_missing_explanations_and_high_risk_block_readiness(self):
        case = self.create_case()
        fields = self.complete_quick_form(case)
        saved = self.request_json("PATCH", f"/api/cases/{case['id']}/quick-form", json=fields)
        self.assertEqual(saved["readiness"]["quick_missing"], [])
        scenarios = [({"title": "موضوع مختلف"}, "تختلف"),
                     ({"amount": "999"}, "يختلف"),
                     ({"quick_req_01": "missing", "quick_req_01_note": ""}, "سبب"),
                     ({"quick_req_02": "not_applicable", "quick_req_02_note": ""}, "سبب"),
                     ({"quick_risk_need": "high", "deep_risks": ""}, "المتعمق"),
                     ({"quick_risk_need": "invented"}, "الحاجة"),
                     ({"audit_date": "not-a-date"}, "تاريخ"),
                     ({"audit_date": (date.today() + timedelta(days=366)).isoformat()}, "تاريخ")]
        for changes, expected in scenarios:
            with self.subTest(changes=changes):
                saved = self.request_json("PATCH", f"/api/cases/{case['id']}/quick-form", json={**fields, **changes})
                self.assertFalse(saved["readiness"]["ready"])
                self.assertTrue(any(expected in msg for msg in saved["readiness"]["quick_missing"]), saved["readiness"])
        fixed = self.request_json("PATCH", f"/api/cases/{case['id']}/quick-form", json={
            **fields, "quick_req_01": "missing", "quick_req_01_note": "نقص اختباري موثق",
            "quick_risk_need": "high", "deep_risks": "خطة اختبارية للفحص المتعمق"})
        self.assertEqual(fixed["readiness"]["quick_missing"], [])
        self.assertEqual(self.get_case(case["id"])["quick_form"]["deep_risks"], "خطة اختبارية للفحص المتعمق")

    def test_blacklist_absence_of_match_or_source_never_clears_a_company(self):
        case = self.create_case()
        no_source = self.request_json("POST", f"/api/cases/{case['id']}/blacklist/check", json={})["blacklist"]
        self.assertEqual(no_source["status"], "unavailable")
        unrelated = self.reference("blacklist", content="قائمة اختبارية اصطناعية تتضمن شركة مختلفة تماماً ولا تثبت أي موقف قانوني حقيقي".encode())
        result = self.request_json("POST", f"/api/cases/{case['id']}/blacklist/check", json={
            "reference_document_id": unrelated["id"], "source_url": OFFICIAL_FIXTURE_URL})["blacklist"]
        self.assertEqual(result["status"], "pending")
        self.assertFalse(result["human_confirmed"])
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["evidence_document_id"], unrelated["id"])
        self.assertEqual(result["source_url"], OFFICIAL_FIXTURE_URL)
        self.assertIn("الوثيقة المرفقة", result["note"])
        matching = self.reference("blacklist", name="synthetic-matching-list.txt", content=(
            "قائمة اختبار اصطناعية فقط: شركة الامل للتجارة العامة؛ يجب التحقق من هوية الشركة ومن قرار الإدراج.".encode()))
        result = self.request_json("POST", f"/api/cases/{case['id']}/blacklist/check", json={"reference_document_id": matching["id"]})["blacklist"]
        self.assertEqual(result["status"], "possible_match")
        self.assertTrue(result["matches"])
        self.assertFalse(result["human_confirmed"])
        self.assertIsNone(result["source_url"], "Local files must not fabricate a successful live website lookup")

    def test_blacklist_network_failure_or_html_absence_is_unavailable(self):
        case = self.create_case()
        with patch("backend.blacklist._fetch_official_source", side_effect=httpx.ConnectError("Synthetic network failure")):
            result = self.request_json("POST", f"/api/cases/{case['id']}/blacklist/check", json={"source_url": OFFICIAL_FIXTURE_URL})["blacklist"]
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["human_confirmed"])
        with patch("backend.blacklist._fetch_official_source", return_value=(
                "Synthetic Ministry homepage with navigation only and no complete blacklist evidence.", OFFICIAL_FIXTURE_URL, False)):
            result = self.request_json("POST", f"/api/cases/{case['id']}/blacklist/check", json={"source_url": OFFICIAL_FIXTURE_URL})["blacklist"]
        self.assertEqual(result["status"], "unavailable")
        self.assertNotEqual(result["status"], "cleared")

    def test_blacklist_confirmation_requires_evidence_human_attestation_and_official_provenance(self):
        case = self.create_case()
        document = self.reference("blacklist")
        wrong_category = self.reference("structure")
        base = dict(status="cleared", note="مراجعة اختبارية فقط", evidence_document_id=document["id"],
                    source_url=OFFICIAL_FIXTURE_URL, human_confirmed=True)
        invalid = [{"human_confirmed": False}, {"note": ""}, {"evidence_document_id": None},
                   {"evidence_document_id": wrong_category["id"]}, {"source_url": ""}]
        invalid += [{"source_url": value} for value in ("http://mop.gov.iq/list", "https://mop.gov.iq.evil.example/list",
                    "https://example.com/list", "https://user@mop.gov.iq/list", "https://mop.gov.iq:8443/list", "https://127.0.0.1/list")]
        for changes in invalid:
            with self.subTest(changes=changes):
                response = self.client.patch(f"/api/cases/{case['id']}/blacklist", json={**base, **changes})
                self.assertEqual(response.status_code, 422, response.text)
        confirmed = self.reviewed_blacklist(case["id"], document)["blacklist"]
        self.assertEqual(confirmed["status"], "cleared")
        self.assertTrue(confirmed["human_confirmed"])
        self.assertTrue(confirmed["checked_at"])
        self.assertEqual(confirmed["evidence_document_id"], document["id"])
        self.assertEqual(confirmed["source_url"], OFFICIAL_FIXTURE_URL)
        self.assertEqual(self.get_case(case["id"])["blacklist"], confirmed)

    def test_partial_blacklist_requires_full_original_review_and_unreadable_source_cannot_clear(self):
        case = self.create_case()
        partial = self.reference("blacklist", name="synthetic-scanned-list.pdf", content=synthetic_pdf(text=""))
        self.assertEqual(partial["extraction_status"], "needs_ocr")
        fields = dict(status="cleared", note="مراجعة اصطناعية", evidence_document_id=partial["id"],
                      source_url=OFFICIAL_FIXTURE_URL, human_confirmed=True)
        response = self.client.patch(f"/api/cases/{case['id']}/blacklist", json=fields)
        self.assertEqual(response.status_code, 422)
        saved = self.reviewed_blacklist(case["id"], partial, reviewed_full_document=True)
        self.assertTrue(saved["blacklist"]["reviewed_full_document"])
        invalid = self.reference("blacklist", name="synthetic-broken-list.pdf", content=b"Synthetic invalid PDF")
        self.assertEqual(invalid["extraction_status"], "failed")
        response = self.client.patch(f"/api/cases/{case['id']}/blacklist", json={
            **fields, "evidence_document_id": invalid["id"], "reviewed_full_document": True})
        self.assertEqual(response.status_code, 422)

    def test_incomplete_case_only_gets_watermarked_draft_and_final_is_blocked(self):
        case = self.create_case()
        final = self.client.get(f"/api/cases/{case['id']}/report", params={"final": "true"})
        self.assertEqual(final.status_code, 409)
        self.assertTrue(final.json()["detail"]["blockers"])
        draft = self.client.get(f"/api/cases/{case['id']}/report")
        self.assertEqual(draft.status_code, 200)
        self.assertIn("مسودة للمراجعة", draft.text)
        self.assertIn('class="watermark"', draft.text)
        self.assertFalse(self.get_case(case["id"])["readiness"]["ready"])

    def test_documented_adverse_case_gets_unsigned_final_with_escaped_data_and_pdf(self):
        case = self.complete_reviewed_case()
        self.assertTrue(case["readiness"]["ready"], case["readiness"]["blockers"])
        self.assertEqual(case["readiness"]["failed"], 1, "Documented failure remains visible; readiness is not compliance")
        result = self.client.get(f"/api/cases/{case['id']}/report", params={"final": "true"})
        self.assertEqual(result.status_code, 200)
        html = result.text
        self.assertIn("تقرير مكتمل المراجعة ـ غير موقع", html)
        self.assertNotIn('class="watermark"', html)
        self.assertIn("SYNTHETIC ADVERSE FINDING", html)
        self.assertIn("ملاحظة تدقيقية", html)
        self.assertIn(escape(case["title"]), html)
        self.assertIn('&lt;script&gt;alert(&quot;finding&quot;)&lt;/script&gt;', html)
        self.assertIn('&lt;img src=x onerror=alert(&quot;table&quot;)&gt;', html)
        self.assertNotIn("<script", html.lower())
        self.assertNotIn("<img", html.lower(), "The example's signature or seal must not be embedded")
        self.assertIn("التوقيع / ____________________", html)
        self.assertIn("لم ينسخ توقيع أو ختم أو بيانات الحالة النموذجية", html)
        self.assertIn("/api/documents/", html)
        appendix = html.split("مرفق ١ ـ استمارة الفحص السريع", 1)[1].split("مرفق ٢ ـ فهرس الأدلة والمراجع", 1)[0]
        for section in STRUCTURE["quick_form"]["sections"]:
            self.assertTrue(escape(section["label"]) in appendix,
                            f"Report omits actual quick-form section: {section['label']}")
        for item in [*STRUCTURE["quick_form"]["requirements"], *STRUCTURE["quick_form"]["risks"]]:
            self.assertTrue(escape(item["label"]) in appendix,
                            f"Report omits reviewed quick-form item: {item['label']}")
        for selected_label in ("مستوفي", "منخفض", STRUCTURE["quick_form"]["decisions"][0]):
            self.assertTrue(escape(selected_label) in appendix,
                            f"Report must display the selected Arabic option: {selected_label}")
        if not (os.environ.get("AUDIT_CHROMIUM_PATH") or shutil.which("chromium") or shutil.which("chromium-browser")):
            self.skipTest("HTML checks passed; Chromium is unavailable for the optional PDF renderer check")
        pdf = self.client.get(f"/api/cases/{case['id']}/report", params={"final": "true", "format": "pdf"})
        self.assertEqual(pdf.status_code, 200, pdf.text[:1000] if pdf.status_code != 200 else "")
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF-"))
        reader = PdfReader(BytesIO(pdf.content))
        self.assertGreaterEqual(len(reader.pages), 3)
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        # PDF text extraction can add spaces around individual shaped glyphs.
        self.assertIn("SYNTHETICADVERSEFINDING", "".join(extracted.split()),
                      "The rendered PDF must preserve the actual adverse finding")
        self.assertGreater(len(extracted), 1000, "A nonempty file or blank pages alone do not validate report rendering")


if __name__ == "__main__":
    unittest.main()
