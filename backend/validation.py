"""
validation.py
Data quality checks and variance/anomaly detection.
Thresholds are configurable (see VARIANCE_THRESHOLD_PCT).
"""

VARIANCE_THRESHOLD_PCT = 20.0  # a YoY % change beyond this is flagged as "significant"


def detect_missing_values(record: dict, metric_columns: list) -> list:
    """Return list of metric names missing (None/NaN) for this record."""
    missing = []
    for metric in metric_columns:
        value = record.get(metric) if record else None
        if value is None:
            missing.append(metric)
    return missing


def detect_duplicate_records(df) -> list:
    """Return list of (company, year) pairs that appear more than once in the dataset."""
    dupes = df[df.duplicated(subset=["Company", "Year"], keep=False)]
    pairs = (
        dupes[["Company", "Year"]]
        .drop_duplicates()
        .to_dict("records")
    )
    return pairs


def detect_non_numeric_values(raw_df, metric_columns: list) -> list:
    """
    Detect entries in numeric metric columns that could not be parsed as numbers.
    Expects the *raw* (pre-coercion) dataframe values compared against the coerced one
    would be ideal; here we flag NaNs that are not simply "blank" — best-effort check.
    """
    issues = []
    for col in metric_columns:
        if col not in raw_df.columns:
            continue
        for idx, val in raw_df[col].items():
            if isinstance(val, str):
                stripped = val.strip()
                if stripped != "" and not _is_number(stripped):
                    issues.append(
                        {
                            "row": int(idx),
                            "company": raw_df.at[idx, "Company"] if "Company" in raw_df.columns else None,
                            "year": raw_df.at[idx, "Year"] if "Year" in raw_df.columns else None,
                            "column": col,
                            "value": val,
                        }
                    )
    return issues


def _is_number(s: str) -> bool:
    try:
        float(s.replace(",", ""))
        return True
    except ValueError:
        return False


def detect_variances(comparison: dict, threshold_pct: float = VARIANCE_THRESHOLD_PCT) -> list:
    """
    Given a compare_years() style dict of {metric: {current, previous, absolute_change, percent_change}},
    flag metrics whose percent_change magnitude exceeds the threshold.
    Returns a list sorted by absolute percent_change, largest first.
    """
    flagged = []
    for metric, values in comparison.items():
        pct = values.get("percent_change")
        if pct is not None and abs(pct) >= threshold_pct:
            flagged.append(
                {
                    "metric": metric,
                    "percent_change": pct,
                    "absolute_change": values.get("absolute_change"),
                    "direction": "increase" if pct > 0 else "decrease",
                }
            )
    flagged.sort(key=lambda x: abs(x["percent_change"]), reverse=True)
    return flagged


def rank_variances(comparison: dict, top_n: int = 3) -> dict:
    """Return the top N positive and top N negative percent changes."""
    entries = [
        {"metric": m, "percent_change": v["percent_change"]}
        for m, v in comparison.items()
        if v.get("percent_change") is not None
    ]
    positives = sorted(
        [e for e in entries if e["percent_change"] > 0],
        key=lambda x: x["percent_change"],
        reverse=True,
    )[:top_n]
    negatives = sorted(
        [e for e in entries if e["percent_change"] < 0],
        key=lambda x: x["percent_change"],
    )[:top_n]
    return {"top_increases": positives, "top_decreases": negatives}


def detect_anomalies(comparison: dict, overall_trend_metric: str = "Revenue") -> list:
    """
    Flag metrics whose direction (up/down) differs from the overall trend metric's direction.
    E.g. if Revenue is up but Net Income is down, that's an anomaly worth surfacing.
    """
    anomalies = []
    trend = comparison.get(overall_trend_metric)
    if not trend or trend.get("percent_change") is None:
        return anomalies

    trend_direction = "up" if trend["percent_change"] > 0 else "down"

    for metric, values in comparison.items():
        if metric == overall_trend_metric:
            continue
        pct = values.get("percent_change")
        if pct is None:
            continue
        direction = "up" if pct > 0 else "down"
        if direction != trend_direction:
            anomalies.append(
                {
                    "metric": metric,
                    "metric_direction": direction,
                    "trend_metric": overall_trend_metric,
                    "trend_direction": trend_direction,
                    "percent_change": pct,
                }
            )
    return anomalies
