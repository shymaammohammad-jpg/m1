"""Synthetic automatic-list evidence scenarios; no real Ministry calls."""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import ai_blacklist as lists
from backend.blacklist import validate_official_url
from backend.extraction import create_document
from backend.storage import Store, now


LIVE = "https://mop.gov.iq/القائمة-السوداء-2"
PDF = "https://mop.gov.iq/uploads/blacklist-current.pdf"
NAME = "شركة الأمل للتجارة العامة"


def pdf_page(text="Black list - company name - decision number - Example Trading Company 123"):
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    if text:
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 11 Tf 40 780 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class AutomaticBlacklistTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="raqib-list-test-")
        self.store = Store(Path(self.folder.name))
        self.case_id = "synthetic-case"
        self.store.insert_case({"id": self.case_id, "title": "Synthetic fixture only", "updated_at": now()})
        self.sources = patch.object(lists, "CURRENT_SOURCES", ({"url": LIVE, "title": "Synthetic source"},))
        self.sources.start()
        self.urls = patch.object(lists, "_validate_fetch_url", side_effect=lambda url: validate_official_url(url, resolve_dns=False))
        self.urls.start()

    def tearDown(self):
        self.urls.stop()
        self.sources.stop()
        self.folder.cleanup()

    def run_lookup(self, handler, name=NAME, **kwargs):
        transport = httpx.MockTransport(handler)
        with patch.object(lists, "_new_client", side_effect=lambda: httpx.Client(transport=transport, follow_redirects=False)):
            return lists.run_automatic_blacklist(name, self.store, self.case_id, **kwargs)

    def test_landing_page_is_retained_but_never_negative_evidence(self):
        body = b"<html><script>var noRecords = true;</script><body>Ministry portal - search form. <input name='company'></body></html>"
        result = self.run_lookup(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "text/html"}))
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["human_confirmed"])
        self.assertEqual(len(result["evidence_document_ids"]), 1)
        self.assertEqual(len(self.store.documents(self.case_id)), 2)
        source = result["searched_sources"][0]
        original = self.store.document(source["original_document_id"])
        derived = self.store.document(source["document_id"])
        self.assertEqual(Path(original["_path"]).read_bytes(), body)
        self.assertEqual(original["sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(derived["source_document_id"], original["id"])
        self.assertEqual(derived["source_sha256"], original["sha256"])
        self.assertNotIn("noRecords", derived["_text"])
        self.assertEqual(Path(original["_path"]).suffix, ".txt")
        self.assertTrue(source["live"])

    def test_scripted_name_is_not_visible_match(self):
        body = f"<html><script>const secret = '{NAME}'</script><p>منصة الاستعلام الرسمية يرجى البحث باسم الشركة.</p></html>".encode()
        result = self.run_lookup(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "text/html"}))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["matches"], [])

    def test_live_match_is_candidate_with_original_and_derived_provenance(self):
        body = "<html><table><tr><td>اسم الشركة</td><td>رقم القرار</td></tr><tr><td>شَرِكَة الامل للتجارة العامة</td><td>123</td></tr></table></html>".encode()
        result = self.run_lookup(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "text/html"}))
        self.assertEqual(result["status"], "possible_match")
        self.assertFalse(result["human_confirmed"])
        match = result["matches"][0]
        self.assertEqual(match["page"], 1)
        self.assertTrue(match["live_source"])
        self.assertEqual(match["confidence"], "candidate")
        self.assertIn("شَرِكَة الامل", match["quote"])
        self.assertEqual(result["source_url"], validate_official_url(LIVE, resolve_dns=False))

    def test_complete_list_like_pdf_reports_absence_only_in_its_own_scope(self):
        body = pdf_page()
        visited = []
        def handler(request):
            visited.append(str(request.url))
            if request.url.path.endswith(".pdf"):
                return httpx.Response(200, content=body, headers={"Content-Type": "application/pdf"})
            return httpx.Response(200, content=f"<html><a href='{PDF}'>القائمة السوداء للشركات</a></html>".encode(), headers={"Content-Type": "text/html"})
        result = self.run_lookup(handler)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(len(visited), 2)
        self.assertEqual(result["source_url"], PDF)
        self.assertIn("النسخ المشار إليها فقط", result["note"])
        self.assertNotEqual(result["status"], "cleared")
        self.assertFalse(result["human_confirmed"])
        retained = next(self.store.document(x) for x in result["evidence_document_ids"] if self.store.document(x)["_path"].endswith(".pdf"))
        self.assertEqual(Path(retained["_path"]).read_bytes(), body)

    def test_unrelated_complete_pdf_cannot_prove_absence(self):
        result = self.run_lookup(lambda request: httpx.Response(200, content=pdf_page("Official procurement instruction requires taking account of blacklists."), headers={"Content-Type": "application/pdf"}))
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["searched_sources"][0]["list_like"])

    def test_scanned_or_broken_pdf_never_negative(self):
        for body in (pdf_page(""), b"%PDF-corrupt-synthetic-fixture"):
            with self.subTest(body_size=len(body)):
                result = self.run_lookup(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "application/pdf"}))
                self.assertEqual(result["status"], "unavailable")
                self.assertFalse(result["searched_sources"][0]["complete"])

    def test_redirect_escape_is_rejected_before_foreign_request(self):
        visited = []
        def handler(request):
            visited.append(str(request.url))
            return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})
        result = self.run_lookup(handler)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(len(visited), 1)
        self.assertEqual(self.store.documents(self.case_id), [])

    def test_oversize_and_network_errors_are_explicit_without_raw_exception(self):
        result = self.run_lookup(lambda request: httpx.Response(200, content=b"too large", headers={"Content-Type": "text/plain", "Content-Length": str(lists.MAX_SOURCE_BYTES + 1)}))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.store.documents(self.case_id), [])
        def unavailable(request):
            raise httpx.ConnectError("PROXY_SECRET_DO_NOT_LEAK", request=request)
        result = self.run_lookup(unavailable)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("PROXY_SECRET_DO_NOT_LEAK", str(result))

    def test_uploaded_matching_source_is_not_represented_as_live(self):
        path = self.store.uploads / "synthetic-local.txt"
        path.write_text("قائمة سوداء اختبارية اصطناعية وليست مصدراً قانونياً: " + NAME)
        document = create_document(path, "القائمة المحلية.txt", "blacklist")
        self.store.add_documents([document], self.case_id)
        result = self.run_lookup(lambda request: httpx.Response(503))
        self.assertEqual(result["status"], "possible_match")
        self.assertFalse(result["matches"][0]["live_source"])
        self.assertIn("مرفق محلي", result["note"])
        self.assertIsNone(result["source_url"])

    def test_uploaded_partial_or_complete_nonmatch_is_not_negative(self):
        path = self.store.uploads / "synthetic-local.txt"
        path.write_text("قائمة سوداء اختبارية اصطناعية وليست مصدراً قانونياً: شركة مختلفة محدودة")
        document = create_document(path, "القائمة المحلية.txt", "blacklist")
        self.store.add_documents([document], None)
        result = self.run_lookup(lambda request: httpx.Response(503))
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(any(not source["live"] for source in result["searched_sources"]))

    def test_word_boundaries_do_not_match_a_longer_name(self):
        body = "القائمة السوداء اسم الشركة رقم القرار - شركة الامل للتجارة العامةالخاصة - 123".encode()
        result = self.run_lookup(lambda request: httpx.Response(200, content=body, headers={"Content-Type": "text/plain"}))
        self.assertEqual(result["matches"], [])
        self.assertEqual(result["status"], "unavailable")

    def test_match_quote_is_a_verbatim_window_near_a_late_diacritic_name(self):
        text = ("سجل بيانات اختباري فقط — " * 1000) + " اسم الشركة: شَرِكَة الامل للتجارة العامة، رقم القرار 123."
        found = lists._matching_pages(NAME, [text], {"id": "source"}, PDF, live=True)
        self.assertEqual(len(found), 1)
        quote = found[0]["quote"]
        self.assertIn(quote, text)
        self.assertIn("شَرِكَة الامل للتجارة العامة", quote)
        self.assertLess(len(quote), 500)

    def test_chunked_body_limit_is_enforced_without_content_length(self):
        with patch.object(lists, "MAX_SOURCE_BYTES", 64):
            result = self.run_lookup(lambda request: httpx.Response(200, content=b"x" * 65, headers={"Content-Type": "text/plain"}))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.store.documents(self.case_id), [])

    def test_same_host_redirect_retains_final_provenance_and_bytes(self):
        body = pdf_page()
        def handler(request):
            if not request.url.path.endswith(".pdf"):
                return httpx.Response(302, headers={"Location": "/uploads/blacklist-current.pdf"})
            return httpx.Response(200, content=body, headers={"Content-Type": "application/pdf"})
        result = self.run_lookup(handler)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(result["source_url"], PDF)
        snapshot = self.store.document(result["evidence_document_ids"][0])
        self.assertEqual(snapshot["source_url"], PDF)
        self.assertEqual(Path(snapshot["_path"]).read_bytes(), body)

    def test_insufficient_identity_and_cancelled_job_do_not_contact_network(self):
        visited = []
        def handler(request):
            visited.append(str(request.url))
            return httpx.Response(500)
        for name in ("", "شركة", "شركة للتجارة العامة", "123456", "الأمل"):
            with self.subTest(name=name):
                result = self.run_lookup(handler, name=name)
                self.assertEqual(result["status"], "insufficient_identity")
        result = self.run_lookup(handler, cancelled=lambda: True)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("أُوقف", result["note"])
        self.assertEqual(visited, [])


if __name__ == "__main__":
    unittest.main()
