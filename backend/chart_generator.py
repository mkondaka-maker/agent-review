"""
chart_generator.py
Turns dataframes / calculation results into chart-ready JSON structures
consumed by Chart.js on the frontend.
"""


def generate_trend_chart_data(company_df, metric: str) -> dict:
    """Line chart data: metric value across every available year for a company."""
    if metric not in company_df.columns:
        return {"labels": [], "values": [], "metric": metric, "available": False}

    trimmed = company_df[["Year", metric]].dropna()
    return {
        "labels": [int(y) for y in trimmed["Year"].tolist()],
        "values": [float(v) for v in trimmed[metric].tolist()],
        "metric": metric,
        "available": not trimmed.empty,
    }


def generate_current_vs_previous_chart(metric: str, current_value, previous_value, current_year, previous_year) -> dict:
    return {
        "metric": metric,
        "labels": [str(previous_year) if previous_year is not None else "Previous", str(current_year)],
        "values": [previous_value, current_value],
        "available": current_value is not None and previous_value is not None,
    }


def generate_grouped_bar_chart(comparison: dict, metrics: list) -> dict:
    """Grouped bar chart: current vs previous for several metrics at once."""
    labels = [m for m in metrics if m in comparison]
    current_values = [comparison[m]["current"] for m in labels]
    previous_values = [comparison[m]["previous"] for m in labels]
    return {
        "labels": labels,
        "series": [
            {"name": "Previous Year", "values": previous_values},
            {"name": "Current Year", "values": current_values},
        ],
    }


def generate_yoy_bar_chart(comparison: dict) -> dict:
    """Horizontal bar chart of percentage changes per metric."""
    items = [
        {"metric": m, "percent_change": v["percent_change"]}
        for m, v in comparison.items()
        if v.get("percent_change") is not None
    ]
    items.sort(key=lambda x: abs(x["percent_change"]), reverse=True)
    return {
        "labels": [i["metric"] for i in items],
        "values": [i["percent_change"] for i in items],
    }


def generate_profitability_chart(company_df) -> dict:
    """Line chart of Gross/Net/EBITDA margin across years, where derivable."""
    years = []
    gross_margin, net_margin, ebitda_margin = [], [], []

    has_gp = "Gross Profit" in company_df.columns
    has_ni = "Net Income" in company_df.columns
    has_ebitda = "EBITDA" in company_df.columns
    has_rev = "Revenue" in company_df.columns

    if not has_rev:
        return {"labels": [], "series": [], "available": False}

    for _, row in company_df.iterrows():
        revenue = row.get("Revenue")
        if revenue in (None, 0) or (isinstance(revenue, float) and revenue != revenue):
            continue
        years.append(int(row["Year"]))
        gross_margin.append(round((row["Gross Profit"] / revenue) * 100, 2) if has_gp and row.get("Gross Profit") is not None else None)
        net_margin.append(round((row["Net Income"] / revenue) * 100, 2) if has_ni and row.get("Net Income") is not None else None)
        ebitda_margin.append(round((row["EBITDA"] / revenue) * 100, 2) if has_ebitda and row.get("EBITDA") is not None else None)

    series = []
    if has_gp:
        series.append({"name": "Gross Margin %", "values": gross_margin})
    if has_ni:
        series.append({"name": "Net Margin %", "values": net_margin})
    if has_ebitda:
        series.append({"name": "EBITDA Margin %", "values": ebitda_margin})

    return {"labels": years, "series": series, "available": bool(series)}
