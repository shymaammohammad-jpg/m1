"""Deterministic arithmetic over already source-validated report table cells.

This module does not infer units, select legal thresholds or verify that two
source figures belong to the same transaction. The caller owns that provenance.
Quoted source values remain unchanged; computed cells and disagreements have
separate, explicit records. No binary floating-point arithmetic is used.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import re
from typing import Any

from .ai_documents import normalize_quote


MONEY_PLACES = 3
PERCENT_PLACES = 2
_NUMBER = re.compile(r"[+-]?(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,3}(?: [0-9]{3})+)(?:\.[0-9]+)?")
_TABLES = {
    "estimate_market_comparison", "award_market_comparison", "discount_check",
    "bid_amount_discrepancies", "financial_capacity", "similar_works",
}


def _number(value: Any) -> Decimal | None:
    # Floats may already have lost source digits; do not silently bless them.
    if isinstance(value, bool) or isinstance(value, float) or value is None:
        return None
    if not isinstance(value, (str, int, Decimal)):
        return None
    text = normalize_quote(str(value)).strip()
    if len(text) > 120 or not _NUMBER.fullmatch(text):
        return None
    fraction = text.partition(".")[2]
    if len(fraction) > 30 or sum(char.isdigit() for char in text.partition(".")[0]) > 80:
        return None
    try:
        result = Decimal(text.replace(",", "").replace(" ", ""))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def _missing(value: Any) -> bool:
    return value is None or isinstance(value, str) and not value.strip()


def _display(number: Decimal, places: int) -> str:
    return format(number.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")


def _safe(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:500]


def reconcile_tables(tables: dict) -> tuple[dict, list[dict]]:
    """Copy report tables and return independently inspectable arithmetic checks.

    ``checks`` use one-based rows and statuses ``calculated``, ``match``,
    ``mismatch`` or ``unavailable``. A calculated cell is not quoted source data.
    Threshold checks are numerical comparisons only, never legal conclusions.
    Missing analysis amounts are never fabricated. Currency symbols, mixed
    units, floats, malformed grouping and scientific/non-finite notation are
    refused instead of being guessed.
    """
    if not isinstance(tables, dict):
        return {}, []
    result = deepcopy(tables)
    checks: list[dict] = []

    def check(table_id, number, field, status, formula, inputs, *, actual=None,
              expected=None, note="", kind="arithmetic", places=MONEY_PLACES):
        checks.append({
            "table_id": table_id, "row": number, "field": field, "status": status,
            "formula": formula, "inputs": {key: _safe(value) for key, value in inputs.items()},
            "actual": _safe(actual), "expected": _safe(expected), "note": note,
            "kind": kind, "decimal_places": places, "rounding": "ROUND_HALF_UP",
            "legal_conclusion": False,
        })

    def calculated(table_id, number, row, field, exact, formula, inputs, places=MONEY_PLACES):
        expected = _display(exact, places)
        source = row.get(field)
        if _missing(source):
            row[field] = expected
            check(table_id, number, field, "calculated", formula, inputs, expected=expected,
                  note="قيمة محسوبة آليًا من مدخلات الصف؛ ليست اقتباسًا من المستند.", places=places)
            return exact
        actual = _number(source)
        if actual is None:
            check(table_id, number, field, "unavailable", formula, inputs, actual=source, expected=expected,
                  note="القيمة المصدرية المطلوب مطابقتها غير صالحة للحساب؛ بقيت كما وردت.", places=places)
            return exact
        acceptable = actual == exact or actual == Decimal(expected)
        # A quoted percentage may retain more precision than the display. The
        # source itself is never rounded or rewritten during this comparison.
        if places == PERCENT_PLACES and actual.as_tuple().exponent < -places:
            source_places = min(30, -actual.as_tuple().exponent)
            acceptable |= actual == exact.quantize(Decimal(1).scaleb(-source_places), rounding=ROUND_HALF_UP)
        check(table_id, number, field, "match" if acceptable else "mismatch", formula, inputs,
              actual=source, expected=expected,
              note="القيمة المثبتة تطابق الحساب ضمن التقريب المبين." if acceptable else
                   "القيمة المثبتة تختلف عن الحساب؛ حُفظت القيمة المصدرية ولم تُستبدل.", places=places)
        return exact

    def inputs_for(row, keys):
        inputs = {key: row.get(key) for key in keys}
        parsed = {key: _number(value) for key, value in inputs.items()}
        return inputs, parsed

    with localcontext() as context:
        context.prec = 160
        for table_id, rows in result.items():
            if table_id not in _TABLES or not isinstance(rows, list):
                continue
            for number, row in enumerate(rows[:200], 1):
                if not isinstance(row, dict):
                    check(table_id, number, "row", "unavailable", "", {}, note="صف الجدول ليس مجموعة خلايا صالحة.")
                    continue
                if table_id in {"estimate_market_comparison", "award_market_comparison"}:
                    left, right = (("estimate", "market_price") if table_id == "estimate_market_comparison" else
                                   ("award_amount", "market_amount"))
                    inputs, values = inputs_for(row, (left, right))
                    if any(value is None or value < 0 for value in values.values()):
                        check(table_id, number, "difference", "unavailable", f"{left} - {right}", inputs,
                              note="يلزم مبلغان عدديان غير سالبين وبوحدة موحدة؛ لم يُفترض مبلغ مفقود.")
                        if table_id == "award_market_comparison":
                            check(table_id, number, "difference_percent", "unavailable",
                                  f"({left} - {right}) / {right} * 100", inputs,
                                  note="تعذر حساب نسبة الفرق من المدخلات المتاحة.", places=PERCENT_PLACES)
                        continue
                    difference = values[left] - values[right]
                    calculated(table_id, number, row, "difference", difference, f"{left} - {right}", inputs)
                    if table_id == "award_market_comparison":
                        if values[right] == 0:
                            check(table_id, number, "difference_percent", "unavailable",
                                  f"({left} - {right}) / {right} * 100", inputs,
                                  note="سعر السوق يساوي صفرًا؛ نسبة الفرق غير معرّفة.", places=PERCENT_PLACES)
                        else:
                            calculated(table_id, number, row, "difference_percent", difference / values[right] * 100,
                                       f"({left} - {right}) / {right} * 100; denominator={right}", inputs, PERCENT_PLACES)

                elif table_id in {"discount_check", "bid_amount_discrepancies"}:
                    inputs, values = inputs_for(row, ("opening_amount", "discount_percent"))
                    opening, rate = values["opening_amount"], values["discount_percent"]
                    expected = None
                    if opening is None or opening < 0 or rate is None or not 0 <= rate <= 100:
                        check(table_id, number, "discounted_amount", "unavailable",
                              "opening_amount * (1 - discount_percent / 100)", inputs,
                              note="لم تثبت قيمة افتتاحية صالحة ونسبة تخفيض من صفر إلى مئة؛ لا تُفترض نسبة صفر.")
                    else:
                        expected = opening * (1 - rate / 100)
                        calculated(table_id, number, row, "discounted_amount", expected,
                                   "opening_amount * (1 - discount_percent / 100)", inputs)
                    # The discrepancy table has no canonical discount column.
                    # A quoted after-discount amount still permits a source-to-
                    # source comparison, but does not validate an unknown rate.
                    comparison = expected if expected is not None else _number(row.get("discounted_amount"))
                    actual = _number(row.get("analysis_amount"))
                    comparison_inputs = {"discounted_amount": row.get("discounted_amount"), "analysis_amount": row.get("analysis_amount")}
                    if comparison is None or comparison < 0 or actual is None or actual < 0:
                        check(table_id, number, "analysis_amount", "unavailable",
                              "analysis_amount == expected_discounted_amount", comparison_inputs,
                              note="لم يثبت مبلغان صالحان للمطابقة؛ لم يُختلق مبلغ للتحليل.", kind="amount_comparison")
                    else:
                        expected_text = _display(comparison, MONEY_PLACES)
                        match = actual == comparison or actual == Decimal(expected_text)
                        check(table_id, number, "analysis_amount", "match" if match else "mismatch",
                              "analysis_amount == expected_discounted_amount" if expected is not None else
                              "analysis_amount == source_discounted_amount", comparison_inputs,
                              actual=row["analysis_amount"], expected=expected_text, kind="amount_comparison",
                              note=("مطابقة حسابية للمبلغ بعد تطبيق النسبة المثبتة." if expected is not None else
                                    "مطابقة بين مبلغين مثبتين فقط؛ لا تثبت صحة تطبيق نسبة التخفيض غير المتاحة."))

                else:
                    amount_key = "capacity_amount" if table_id == "financial_capacity" else "similar_amount"
                    inputs, values = inputs_for(row, (amount_key, "estimated_cost"))
                    amount, denominator = values[amount_key], values["estimated_cost"]
                    if amount is None or amount < 0 or denominator is None or denominator <= 0:
                        check(table_id, number, "provided_percent", "unavailable",
                              f"{amount_key} / estimated_cost * 100", inputs,
                              note="تتطلب النسبة مبلغًا غير سالب وكلفة تخمينية أكبر من صفر.", places=PERCENT_PLACES)
                        continue
                    ratio = amount / denominator * 100
                    calculated(table_id, number, row, "provided_percent", ratio,
                               f"{amount_key} / estimated_cost * 100; denominator=estimated_cost", inputs, PERCENT_PLACES)
                    if not _missing(row.get("required_percent")):
                        threshold = _number(row["required_percent"])
                        if threshold is None or threshold < 0:
                            check(table_id, number, "required_percent", "unavailable",
                                  "calculated_provided_percent >= source_required_percent",
                                  {**inputs, "required_percent": row["required_percent"]},
                                  note="النسبة المطلوبة المثبتة غير صالحة للمقارنة؛ لم يُفترض حد قانوني.",
                                  kind="threshold_comparison", places=PERCENT_PLACES)
                        else:
                            meets = ratio >= threshold
                            check(table_id, number, "required_percent", "match" if meets else "mismatch",
                                  "calculated_provided_percent >= source_required_percent",
                                  {**inputs, "required_percent": row["required_percent"]},
                                  actual=_display(ratio, PERCENT_PLACES), expected=format(threshold, "f"),
                                  note=("النسبة المحسوبة لا تقل عدديًا عن النسبة المثبتة." if meets else
                                        "النسبة المحسوبة أقل عدديًا من النسبة المثبتة.") +
                                       " هذه مقارنة عددية فقط؛ لا تثبت انطباق المرجع أو تحقق شرط قانوني.",
                                  kind="threshold_comparison", places=PERCENT_PLACES)
    return result, checks


__all__ = ["reconcile_tables"]
