"""Arithmetic fixtures are invented data, not contract or statutory evidence."""
from copy import deepcopy
import unittest

from backend.ai_calculations import reconcile_tables


class ArithmeticTests(unittest.TestCase):
    def test_large_amounts_keep_all_digits_without_float(self):
        source = {"estimate_market_comparison": [{"estimate": "99,999,999,999,999.125", "market_price": "11,111,111,111,111.375"}]}
        original = deepcopy(source)
        tables, checks = reconcile_tables(source)
        self.assertEqual(tables["estimate_market_comparison"][0]["difference"], "88888888888887.750")
        self.assertEqual(source, original)
        self.assertEqual(checks[0]["status"], "calculated")
        self.assertFalse(checks[0]["legal_conclusion"])

    def test_source_derived_mismatch_is_preserved(self):
        source = {"estimate_market_comparison": [{"estimate": "100.125", "market_price": "30.025", "difference": "99.000"}]}
        tables, checks = reconcile_tables(source)
        self.assertEqual(tables["estimate_market_comparison"][0]["difference"], "99.000")
        self.assertEqual(checks[0]["status"], "mismatch")
        self.assertEqual(checks[0]["expected"], "70.100")

    def test_arabic_digits_and_separators(self):
        source = {"estimate_market_comparison": [{"estimate": "١٢٬٣٤٥٫٧٥٠", "market_price": "٢٬٣٤٥٫١٢٥"}]}
        tables, checks = reconcile_tables(source)
        self.assertEqual(tables["estimate_market_comparison"][0]["difference"], "10000.625")
        self.assertEqual(tables["estimate_market_comparison"][0]["estimate"], "١٢٬٣٤٥٫٧٥٠")

    def test_award_percentage_uses_explicit_market_denominator(self):
        tables, checks = reconcile_tables({"award_market_comparison": [{"award_amount": "125", "market_amount": "100"}]})
        row = tables["award_market_comparison"][0]
        self.assertEqual(row["difference"], "25.000")
        self.assertEqual(row["difference_percent"], "25.00")
        self.assertIn("denominator=market_amount", checks[1]["formula"])

    def test_negative_difference_is_valid_and_zero_denominator_unknown(self):
        tables, checks = reconcile_tables({"award_market_comparison": [{"award_amount": "0", "market_amount": "0"}, {"award_amount": "80", "market_amount": "100"}]})
        self.assertNotIn("difference_percent", tables["award_market_comparison"][0])
        self.assertEqual(checks[1]["status"], "unavailable")
        self.assertEqual(tables["award_market_comparison"][1]["difference_percent"], "-20.00")

    def test_half_up_percent_rounding(self):
        tables, _ = reconcile_tables({"award_market_comparison": [{"award_amount": "100.025", "market_amount": "100"}]})
        self.assertEqual(tables["award_market_comparison"][0]["difference_percent"], "0.03")

    def test_discount_calculated_amount_and_wrong_analysis(self):
        tables, checks = reconcile_tables({"discount_check": [{"opening_amount": "1000.125", "discount_percent": "12.5", "analysis_amount": "900"}]})
        self.assertEqual(tables["discount_check"][0]["discounted_amount"], "875.109")
        self.assertEqual(checks[-1]["status"], "mismatch")
        self.assertEqual(checks[-1]["expected"], "875.109")

    def test_bad_quoted_discounted_amount_not_used_as_correct_expected(self):
        tables, checks = reconcile_tables({"discount_check": [{"opening_amount": "100", "discount_percent": "10", "discounted_amount": "95", "analysis_amount": "95"}]})
        self.assertEqual(tables["discount_check"][0]["discounted_amount"], "95")
        self.assertEqual([c["status"] for c in checks], ["mismatch", "mismatch"])
        self.assertEqual(checks[-1]["expected"], "90.000")

    def test_missing_rate_never_assumed_zero_and_source_comparison_is_labeled(self):
        tables, checks = reconcile_tables({"bid_amount_discrepancies": [{"opening_amount": "100", "discounted_amount": "90", "analysis_amount": "90"}]})
        self.assertNotIn("discount_percent", tables["bid_amount_discrepancies"][0])
        self.assertEqual(checks[0]["status"], "unavailable")
        self.assertEqual(checks[1]["status"], "match")
        self.assertIn("source_discounted_amount", checks[1]["formula"])

    def test_missing_analysis_is_never_fabricated(self):
        tables, checks = reconcile_tables({"discount_check": [{"opening_amount": "100", "discount_percent": "0"}]})
        self.assertEqual(tables["discount_check"][0]["discounted_amount"], "100.000")
        self.assertNotIn("analysis_amount", tables["discount_check"][0])
        self.assertEqual(checks[-1]["status"], "unavailable")

    def test_out_of_range_discounts_unavailable(self):
        for rate in ("-1", "100.001", "NaN", "Infinity"):
            with self.subTest(rate=rate):
                tables, checks = reconcile_tables({"discount_check": [{"opening_amount": "100", "discount_percent": rate}]})
                self.assertNotIn("discounted_amount", tables["discount_check"][0])
                self.assertEqual(checks[0]["status"], "unavailable")

    def test_capacity_ratio_and_threshold_are_only_numeric(self):
        tables, checks = reconcile_tables({"financial_capacity": [{"estimated_cost": "300", "capacity_amount": "100", "required_percent": "40", "result": "مصدر مقتبس"}]})
        row = tables["financial_capacity"][0]
        self.assertEqual(row["provided_percent"], "33.33")
        self.assertEqual(row["result"], "مصدر مقتبس")
        self.assertEqual(checks[-1]["status"], "mismatch")
        self.assertEqual(checks[-1]["kind"], "threshold_comparison")
        self.assertFalse(checks[-1]["legal_conclusion"])
        self.assertIn("لا تثبت انطباق", checks[-1]["note"])

    def test_similar_works_above_one_hundred_percent_is_valid(self):
        tables, checks = reconcile_tables({"similar_works": [{"estimated_cost": "100", "similar_amount": "200", "provided_percent": "200.000", "required_percent": "150"}]})
        self.assertEqual(tables["similar_works"][0]["provided_percent"], "200.000")
        self.assertEqual([c["status"] for c in checks], ["match", "match"])

    def test_more_precise_quoted_percentage_matches_without_rewrite(self):
        source = {"financial_capacity": [{"estimated_cost": "3", "capacity_amount": "1", "provided_percent": "33.333"}]}
        tables, checks = reconcile_tables(source)
        self.assertEqual(tables["financial_capacity"][0]["provided_percent"], "33.333")
        self.assertEqual(checks[0]["status"], "match")

    def test_invalid_numeric_types_not_guessed(self):
        for value in (float("nan"), float("inf"), 1.25, True, "1e10", "12,34", "1,000 دينار", "1 00", "NaN", None, [], {}):
            with self.subTest(value=value):
                _, checks = reconcile_tables({"estimate_market_comparison": [{"estimate": value, "market_price": "10"}]})
                self.assertEqual(checks[0]["status"], "unavailable")

    def test_unknown_shapes_and_tables_do_not_crash_or_gain_values(self):
        for value in (None, [], "bad", 1):
            self.assertEqual(reconcile_tables(value), ({}, []))
        source = {"not_a_financial_table": [{"amount": "7"}], "discount_check": [None, []]}
        tables, checks = reconcile_tables(source)
        self.assertEqual(tables, source)
        self.assertEqual(len(checks), 2)


if __name__ == "__main__":
    unittest.main()
