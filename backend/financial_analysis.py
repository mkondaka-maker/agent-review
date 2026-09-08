"""
financial_analysis.py
All financial math lives here. The AI never performs these calculations itself;
it only receives the results as evidence.
"""

import math


def _clean(value):
    """Convert NaN / None to None so JSON serialization is safe."""
    if value is None:
        return None
    try:
        if isinstance(value, float) and math.isnan(value):
            return None
    except TypeError:
        pass
    return value


def calculate_yoy(current_value, previous_value):
    """Absolute year-over-year change."""
    current_value = _clean(current_value)
    previous_value = _clean(previous_value)
    if current_value is None or previous_value is None:
        return None
    return round(current_value - previous_value, 4)


def calculate_growth_rate(current_value, previous_value):
    """Percentage year-over-year change."""
    current_value = _clean(current_value)
    previous_value = _clean(previous_value)
    if current_value is None or previous_value is None or previous_value == 0:
        return None
    return round(((current_value - previous_value) / previous_value) * 100, 2)


def calculate_margin(numerator, denominator):
    """Generic margin = numerator / denominator * 100 (e.g. Gross Profit / Revenue)."""
    numerator = _clean(numerator)
    denominator = _clean(denominator)
    if numerator is None or denominator is None or denominator == 0:
        return None
    return round((numerator / denominator) * 100, 2)


def compute_margins(record: dict) -> dict:
    """Compute Gross/Net/EBITDA margins only when the required fields exist."""
    margins = {}
    revenue = record.get("Revenue")

    if revenue not in (None, 0) and record.get("Gross Profit") is not None:
        margins["Gross Profit Margin"] = calculate_margin(record.get("Gross Profit"), revenue)

    if revenue not in (None, 0) and record.get("Net Income") is not None:
        margins["Net Profit Margin"] = calculate_margin(record.get("Net Income"), revenue)

    if revenue not in (None, 0) and record.get("EBITDA") is not None:
        margins["EBITDA Margin"] = calculate_margin(record.get("EBITDA"), revenue)

    return margins


def compare_years(current_record: dict, previous_record: dict, metric_columns: list) -> dict:
    """Build a per-metric YoY comparison dict for every available metric column."""
    comparison = {}
    for metric in metric_columns:
        current_value = _clean(current_record.get(metric)) if current_record else None
        previous_value = _clean(previous_record.get(metric)) if previous_record else None

        comparison[metric] = {
            "current": current_value,
            "previous": previous_value,
            "absolute_change": calculate_yoy(current_value, previous_value),
            "percent_change": calculate_growth_rate(current_value, previous_value),
        }
    return comparison


def build_kpi_cards(record: dict, metric_columns: list) -> list:
    """Return a clean list of {metric, value} for the KPI card row, skipping missing values."""
    cards = []
    for metric in metric_columns:
        value = _clean(record.get(metric)) if record else None
        if value is not None:
            cards.append({"metric": metric, "value": value})
    return cards
