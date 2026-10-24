"""Automatic report rendering uses synthetic evidence and cannot sign a case."""
from __future__ import annotations

import copy
from io import BytesIO
import unittest

from backend.ai_reports import render_ai_report, render_pdf
from backend.reports import SECTIONS
from pypdf import PdfReader


def fixture():
    evidence = {"id": "case-evidence", "name": "عقد اصطناعي.pdf", "category": "contract", "page_count": 3, "sha256": "a" * 64}
    reference = {"id": "instruction-reference", "name": "مرجع اختباري فقط", "category": "instructions", "page_count": 8, "sha256": "b" * 64}
    cite = {"document_id": evidence["id"], "page": 2, "quote": "نص اصطناعي من ملف الاختبار ولا يمثل عقدًا حقيقيًا"}
    ref_cite = {"document_id": reference["id"], "page": 5, "quote": "مرجع اصطناعي لا يمثل نصًا تشريعيًا أو تعليمات نافذة"}
    case = {
        "id": "synthetic-case", "title": "عقد اختباري اصطناعي", "contract_number": "TEST-001",
        "contractor": "شركة اختبار اصطناعية", "entity": "جهة اختبار اصطناعية",
        "contract_date": "2026-03-01", "amount": "1250000.125", "currency": "IQD",
        "instruction_year": 2025, "documents": [evidence],
        "quick_form": {"auditor": "اسم بشري قديم لا ينسب للتشغيل", "team_lead": "مسؤول سابق", "report_tables": {}},
        "automation": {
            "job": {"id": "synthetic-job", "status": "completed", "provider": "synthetic", "model": "test-model",
                    "started_at": "2026-04-02T06:00:00+00:00", "finished_at": "2026-04-02T06:01:00+00:00",
                    "stages": [{"id": "year", "title": "سنة التعليمات", "status": "warning", "message": "السند يحتاج استكمالًا"}]},
            "summary": "النتيجة الاصطناعية تتضمن نقصًا لا يسمح بحسم الامتثال.",
            "findings": [{"id": "estimate-test", "step": "structure", "title": "مراجعة الكلفة التخمينية", "status": "uncertain",
                          "note": "لم يتوفر سند مكتمل لهذا الاختبار.", "confidence": .3,
                          "evidence": [cite], "references": [ref_cite], "validation_issues": ["المستند الداعم جزئي"]}],
            "facts": {"contract_number": {"value": "TEST-001", "citations": [cite]}},
            "missing_documents": ["أصل دراسة الأسعار"], "conflicts": [{"field": "مبلغ العقد", "expected": "1250000.125", "actual": "1250000"}],
            "quick_form": {}, "report_tables": {"estimate_market_comparison": [{"details": "مادة اختبار", "estimate": "1250000.125", "market_price": "غير مثبت"}]},
            "coverage": [{"document_id": evidence["id"], "name": evidence["name"], "page_count": 3, "read_pages": [1, 2], "complete": False, "warnings": ["تعذرت قراءة الصفحة 3"]}],
            "limitations": ["بيانات اصطناعية للاختبار فقط"], "blacklist": {"status": "unavailable", "note": "المصدر غير متاح"},
        },
    }
    return case, [reference]


class AutomaticReportTests(unittest.TestCase):
    def test_arithmetic_appendix_preserves_source_amount_and_labels_computation(self):
        case, refs = fixture()
        case["automation"]["calculations"] = [{"table_id": "estimate_market_comparison", "row": 1,
            "field": "difference", "status": "mismatch", "formula": "estimate - market_price",
            "actual": "100.125", "expected": "99.125", "note": "اختلاف حسابي اصطناعي فقط",
            "source_row_id": "table:estimate_market_comparison:1"}]
        case["automation"]["table_evidence"] = {"table:estimate_market_comparison:1": {
            "estimate": [case["automation"]["findings"][0]["evidence"][0]]}}
        report = render_ai_report(case, refs)
        self.assertIn("مرفق ٤ ـ التحقق الحسابي", report)
        self.assertIn("100.125", report)
        self.assertIn("99.125", report)
        self.assertIn("لا تثبت وحدها مخالفة قانونية", report)

    def test_preserves_human_section_order_and_actual_tables(self):
        case, refs = fixture()
        report = render_ai_report(case, refs)
        headings = ["١ ـ الإيضاحات:", "٢ ـ الملاحظات:"] + [f"{letter} ـ {title}:" for _, letter, title in SECTIONS]
        positions = [report.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("مقارنة الكلفة التخمينية بأسعار السوق السائدة", report)
        self.assertIn("1250000.125", report)
        self.assertIn("مرفق ١ ـ استمارة الفحص السريع", report)

    def test_uncertain_output_does_not_require_or_invent_human_signoff(self):
        case, refs = fixture()
        original = copy.deepcopy(case)
        report = render_ai_report(case, refs)
        self.assertIn("تعذّر الحسم من الأدلة المتاحة", report)
        self.assertIn("تعذرت قراءة الصفحة 3", report)
        self.assertNotIn("اسم بشري قديم", report)
        self.assertNotIn("مسؤول سابق", report)
        self.assertNotIn("التوقيع /", report)
        self.assertNotIn("تقرير مكتمل المراجعة", report)
        self.assertNotIn("تطابق مثبت بمراجعة المدقق", report)
        self.assertEqual(case, original)

    def test_quotes_link_to_known_original_pages(self):
        case, refs = fixture()
        report = render_ai_report(case, refs)
        self.assertIn('/api/documents/case-evidence/file#page=2', report)
        self.assertIn('/api/documents/instruction-reference/file#page=5', report)
        self.assertIn("نص اصطناعي من ملف الاختبار", report)
        self.assertIn("المستند الداعم جزئي", report)

    def test_unknown_and_out_of_bounds_citations_are_not_linked(self):
        case, refs = fixture()
        case["automation"]["findings"][0]["evidence"] = [
            {"document_id": "unknown-doc", "page": 1, "quote": "دليل غير متاح"},
            {"document_id": "case-evidence", "page": 30, "quote": "رقم صفحة غير صحيح"},
        ]
        report = render_ai_report(case, refs)
        self.assertNotIn('/api/documents/unknown-doc/file', report)
        self.assertNotIn('file#page=30', report)
        self.assertIn("صفحة خارج حدود المستند", report)
        self.assertIn("مستند غير متاح ضمن ملف التدقيق", report)

    def test_untrusted_content_is_escaped_in_all_dynamic_sections(self):
        case, refs = fixture()
        attack = '<script>alert("attack")</script><img src=x onerror=alert(1)>'
        case["title"] = attack
        case["automation"]["summary"] = attack
        case["automation"]["findings"][0].update(title=attack, note=attack, validation_issues=[attack])
        case["automation"]["findings"][0]["evidence"][0]["quote"] = attack
        case["automation"]["report_tables"]["estimate_market_comparison"][0]["details"] = attack
        case["automation"]["conflicts"] = [{"note": attack}]
        case["automation"]["coverage"][0]["warnings"] = [attack]
        case["automation"]["blacklist"]["source_url"] = attack
        refs[0]["name"] = attack
        report = render_ai_report(case, refs)
        self.assertNotIn("<script>", report)
        self.assertNotIn("<img src=x", report)
        self.assertIn("&lt;script&gt;", report)
        self.assertIn('default-src \'none\'', report)

    def test_unsupported_pass_is_displayed_as_uncertain(self):
        case, refs = fixture()
        finding = case["automation"]["findings"][0]
        finding.update(status="pass", validation_issues=[], references=[])
        report = render_ai_report(case, refs)
        self.assertIn("غير محسوم (1)", report)
        self.assertIn("لم يثبت عنوان صفحة واقتباس صالحان لـالسند المرجعي", report)
        self.assertIn('class="finding status-uncertain"', report)
        self.assertNotIn('class="finding status-pass"', report)

    def test_missing_facts_and_coverage_remain_explicit(self):
        report = render_ai_report({"id": "missing", "automation": {"job": {"status": "completed"}}}, [])
        self.assertIn("لم يثبت موضوع العقد من المستندات", report)
        self.assertIn("لم تتوفر معلومات تثبت اكتمال قراءة المستندات", report)
        self.assertIn("لم تتوفر نتيجة أو بيانات مسندة", report)
        self.assertNotIn("دقة 100%", report)

    def test_flat_run_and_stale_run_are_described_without_promoting_status(self):
        case, refs = fixture()
        job = case["automation"].pop("job")
        case["automation"].update(job, stale=True)
        report = render_ai_report(case, refs)
        self.assertIn("تغيرت المدخلات ويلزم إعادة التشغيل", report)
        self.assertIn("هذا التقرير تاريخي", report)

    def test_pdf_renders_real_arabic_report(self):
        case, refs = fixture()
        content = render_pdf(render_ai_report(case, refs))
        self.assertTrue(content.startswith(b"%PDF-"))
        pdf = PdfReader(BytesIO(content))
        self.assertGreater(len(pdf.pages), 1)
        self.assertTrue(all(page.mediabox.width > 500 for page in pdf.pages))
        self.assertTrue(any("1250000.125" in (page.extract_text() or "") for page in pdf.pages))


if __name__ == "__main__":
    unittest.main()
