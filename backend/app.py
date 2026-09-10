"""
app.py
Flask Web Backend for Financial Statement Review Agent.
Connects to Supabase PostgreSQL database (with CSV fallback), computes financial metrics,
generates trend/comparison charts, and produces Gemini AI reviews.
"""

import os
import sys
from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.dirname(__file__))

import data_loader
import financial_analysis as fa
import validation as val
import chart_generator as cg
import agent

load_dotenv()

app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "..", "frontend"),
    template_folder=os.path.join(os.path.dirname(__file__), "..", "frontend"),
)
CORS(app)

# ---------------------------------------------------------------- static/page route

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:filename>")
def static_files(filename):
    return send_from_directory(app.static_folder, filename)


# ---------------------------------------------------------------- data endpoints

@app.route("/api/health", methods=["GET"])
def api_health():
    try:
        source = data_loader.get_data_source()
        companies = data_loader.get_companies()
        df = data_loader.load_dataset()
        db_err = None
        db_url = os.environ.get("DATABASE_URL")
        if source != "postgresql" and db_url:
            try:
                data_loader.load_dataset_from_db(db_url)
            except Exception as e:
                db_err = str(e)
        return jsonify({
            "status": "ok",
            "data_source": source,
            "total_records": len(df),
            "total_companies": len(companies),
            "companies": companies,
            "db_error": db_err
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/db-test", methods=["GET"])
def api_db_test():
    """Diagnostic endpoint: test direct DB connection and return detailed status."""
    db_url = os.environ.get("DATABASE_URL", "")
    result = {
        "database_url_set": bool(db_url),
        "database_url_preview": db_url[:50] + "..." if len(db_url) > 50 else db_url,
        "has_sqlalchemy": data_loader.HAS_SQLALCHEMY,
    }
    if db_url and data_loader.HAS_SQLALCHEMY:
        try:
            df = data_loader.load_dataset_from_db(db_url)
            result["db_connection"] = "SUCCESS"
            result["rows_loaded"] = len(df)
            result["columns"] = list(df.columns)
            if "Company" in df.columns:
                result["companies"] = sorted(df["Company"].dropna().unique().tolist())
        except Exception as e:
            result["db_connection"] = "FAILED"
            result["error"] = str(e)
    else:
        result["db_connection"] = "SKIPPED"
        result["reason"] = "DATABASE_URL not set or sqlalchemy not installed"
    return jsonify(result)


@app.route("/api/companies", methods=["GET"])
def api_companies():
    try:
        return jsonify({"companies": data_loader.get_companies(), "source": data_loader.get_data_source()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/years", methods=["GET"])
def api_years():
    company = request.args.get("company")
    try:
        years = data_loader.get_years(company)
        # Return descending order (most recent first)
        years_sorted = sorted(years, reverse=True)
        return jsonify({"years": years_sorted})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/financials", methods=["GET"])
def api_financials():
    company = request.args.get("company")
    year = request.args.get("year")

    if not company:
        return jsonify({"error": "Please select a company."}), 400
    if not year:
        return jsonify({"error": "Please select a year."}), 400

    try:
        record = data_loader.get_year_data(company, int(year))
        if record is None:
            return jsonify({"error": f"No data found for {company} in {year}."}), 404
        return jsonify({"data": _clean_record(record)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------------------------------------------------------- INTENT MAPPING & SCOPING

INTENT_SECTION_MAP = {
    "revenue": {
        "kpis": ["Revenue"],
        "charts": ["revenue_trend", "current_vs_previous_revenue"],
        "sections": ["hero", "trends", "ai", "evidence"],
    },
    "profitability": {
        "kpis": ["Gross Profit", "Net Income", "EBITDA", "Net Profit Margin"],
        "charts": ["profitability", "net_income_trend"],
        "sections": ["hero", "supporting", "trends", "ai", "evidence"],
    },
    "cash_flow": {
        "kpis": ["Cash Flow Operating", "Cash Flow Investing", "Cash Flow Financial", "Cash Flow Financing", "Free Cash Flow Per Share"],
        "charts": [],
        "sections": ["supporting", "ai", "evidence"],
    },
    "returns": {
        "kpis": ["ROE", "ROA", "ROI"],
        "charts": [],
        "sections": ["supporting", "ai", "evidence"],
    },
    "balance_sheet": {
        "kpis": ["Shareholder Equity", "Current Ratio", "Debt Equity Ratio", "Debt/Equity"],
        "charts": [],
        "sections": ["supporting", "ai", "evidence"],
    },
    "variances": {
        "kpis": [],
        "charts": ["yoy_percent_change", "grouped_comparison"],
        "sections": ["variances", "trends", "ai", "evidence"],
    },
    "market": {
        "kpis": ["Market Cap", "Market Cap (B USD)", "Earning Per Share", "EPS", "Number of Employees"],
        "charts": [],
        "sections": ["hero", "supporting", "ai", "evidence"],
    },
    "complete": {
        "kpis": None,
        "charts": None,
        "sections": ["hero", "supporting", "trends", "variances", "ai", "evidence"],
    },
}


# ---------------------------------------------------------------- main analyze endpoint

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    payload = request.get_json(silent=True) or {}
    raw_question = (payload.get("question") or "").strip()
    req_company = payload.get("company")
    req_year = payload.get("year")

    try:
        df = data_loader.load_dataset()
        available_companies = data_loader.get_companies()

        # 1. Groq-powered / heuristic intelligent query analysis
        parsed = agent.parse_user_query(
            question=raw_question,
            available_companies=available_companies,
            default_company=req_company,
            default_year=int(req_year) if req_year else None,
        )

        company = parsed.get("company")
        if company in ("None", "null", ""):
            company = None
        comparison_company = parsed.get("comparison_company")
        if comparison_company in ("None", "null", ""):
            comparison_company = None
        year = parsed.get("year")
        custom_prev_year = parsed.get("previous_year")
        intent = parsed.get("intent") or "complete"
        target_metrics = parsed.get("target_metrics") or []
        interpreted_query = parsed.get("interpreted_query") or raw_question

        # Smart fallback if company was not identified from query or dropdown
        if not company:
            if available_companies:
                return jsonify({
                    "error": f"Could not identify a company from your query. Available companies in database: {', '.join(available_companies)}."
                }), 400
            else:
                return jsonify({"error": "No database records or companies available."}), 400

        # 2. Search Supabase PostgreSQL Database
        search_res = data_loader.search_financial_database(
            company=company,
            year=int(year) if year else None,
            comparison_year=int(custom_prev_year) if custom_prev_year else None,
            comparison_company=comparison_company,
        )

        resolved_company = search_res["primary_company"]
        actual_year = search_res["target_year"]
        actual_prev_year = search_res["previous_year"]
        current_record = search_res["current_record"]
        previous_record = search_res["previous_record"]
        year_fallback_note = search_res["year_fallback_note"]
        comp_company_data = search_res["comparison_company_data"]

        if current_record is None:
            return jsonify({"error": f"No data found for {resolved_company} in database."}), 404

        question = raw_question or f"Give me a complete financial review for {resolved_company} in {actual_year}."
        metric_columns = data_loader.get_available_metric_columns(df)
        intent_config = INTENT_SECTION_MAP.get(intent, INTENT_SECTION_MAP["complete"])

        # 3. Core Python Mathematical Calculations
        comparison = {}
        if previous_record is not None:
            comparison = fa.compare_years(current_record, previous_record, metric_columns)
        margins_current = fa.compute_margins(current_record)
        margins_previous = fa.compute_margins(previous_record) if previous_record else {}
        all_kpi_cards = fa.build_kpi_cards(current_record, metric_columns)

        # Cross-company calculations if comparison company is present
        comp_company_summary = None
        if comp_company_data and comp_company_data.get("record"):
            comp_rec = comp_company_data["record"]
            comp_margins = fa.compute_margins(comp_rec)
            comp_company_summary = {
                "company": comp_company_data["company"],
                "year": comp_company_data["year"],
                "record": _clean_record(comp_rec),
                "margins": comp_margins,
                "kpi_cards": fa.build_kpi_cards(comp_rec, metric_columns),
            }

        # 4. Validation / variance detection
        missing = val.detect_missing_values(current_record, metric_columns)
        duplicates = val.detect_duplicate_records(df)
        variances = val.detect_variances(comparison) if comparison else []
        ranked = val.rank_variances(comparison) if comparison else {"top_increases": [], "top_decreases": []}
        anomalies = val.detect_anomalies(comparison) if comparison else []

        # 5. Filter & Prioritize KPI Cards
        if target_metrics:
            target_lower = [t.lower() for t in target_metrics]
            prioritized_cards = [
                card for card in all_kpi_cards
                if any(t in card["metric"].lower() or card["metric"].lower() in t for t in target_lower)
            ]
            remaining_cards = [card for card in all_kpi_cards if card not in prioritized_cards]
            kpi_cards = prioritized_cards + remaining_cards
        elif intent_config["kpis"] is None:
            kpi_cards = all_kpi_cards
        else:
            target_kpis_lower = [k.lower() for k in intent_config["kpis"]]
            kpi_cards = [
                card for card in all_kpi_cards
                if any(t in card["metric"].lower() or card["metric"].lower() in t for t in target_kpis_lower)
            ]

        # 6. Build Charts conditionally
        company_df = data_loader.get_company_data(resolved_company)
        allowed_charts = intent_config["charts"]

        charts = {}
        
        # Revenue trend
        if allowed_charts is None or "revenue_trend" in allowed_charts or "revenue" in question.lower() or "sales" in question.lower():
            charts["revenue_trend"] = cg.generate_trend_chart_data(company_df, "Revenue")
        else:
            charts["revenue_trend"] = {"available": False}

        # Net income trend
        if allowed_charts is None or "net_income_trend" in allowed_charts or "income" in question.lower() or "profit" in question.lower():
            charts["net_income_trend"] = cg.generate_trend_chart_data(company_df, "Net Income")
        else:
            charts["net_income_trend"] = {"available": False}

        # Current vs previous revenue
        if allowed_charts is None or "current_vs_previous_revenue" in allowed_charts:
            charts["current_vs_previous_revenue"] = cg.generate_current_vs_previous_chart(
                "Revenue",
                comparison.get("Revenue", {}).get("current"),
                comparison.get("Revenue", {}).get("previous"),
                actual_year,
                actual_prev_year,
            ) if comparison else {"available": False}
        else:
            charts["current_vs_previous_revenue"] = {"available": False}

        # Grouped comparison
        if allowed_charts is None or "grouped_comparison" in allowed_charts:
            charts["grouped_comparison"] = cg.generate_grouped_bar_chart(comparison, metric_columns) if comparison else {}
        else:
            charts["grouped_comparison"] = {}

        # YoY percent change
        if allowed_charts is None or "yoy_percent_change" in allowed_charts:
            charts["yoy_percent_change"] = cg.generate_yoy_bar_chart(comparison) if comparison else {}
        else:
            charts["yoy_percent_change"] = {}

        # Profitability
        if allowed_charts is None or "profitability" in allowed_charts or "margin" in question.lower():
            charts["profitability"] = cg.generate_profitability_chart(company_df)
        else:
            charts["profitability"] = {"available": False}

        # 7. Assemble scoped evidence package for AI
        full_evidence = {
            "company": resolved_company,
            "year": actual_year,
            "previous_year": actual_prev_year,
            "question": question,
            "intent": intent,
            "interpreted_query": interpreted_query,
            "target_metrics_requested": target_metrics,
            "year_fallback_note": year_fallback_note,
            "current_year_values": _clean_record(current_record),
            "previous_year_values": _clean_record(previous_record) if previous_record else None,
            "comparison": comparison,
            "margins_current_year": margins_current,
            "margins_previous_year": margins_previous,
            "comparison_company_data": comp_company_summary,
            "variances": variances,
            "ranked_variances": ranked,
            "anomalies": anomalies,
            "missing_metrics": missing,
        }

        ai_review = None
        ai_error = None
        try:
            ai_review = agent.generate_financial_review(full_evidence, user_question=question)
        except Exception as e:
            ai_error = str(e)

        key_observations = agent.generate_key_observations(full_evidence)

        return jsonify({
            "company": resolved_company,
            "comparison_company": comparison_company,
            "comparison_company_data": comp_company_summary,
            "year": actual_year,
            "previous_year": actual_prev_year,
            "year_fallback_note": year_fallback_note,
            "intent": intent,
            "interpreted_query": interpreted_query,
            "sections_to_show": intent_config["sections"],
            "kpi_cards": kpi_cards,
            "comparison": comparison,
            "margins": {"current": margins_current, "previous": margins_previous},
            "validation": {
                "missing_metrics": missing,
                "duplicate_records": duplicates,
            },
            "variances": variances,
            "ranked_variances": ranked,
            "anomalies": anomalies,
            "charts": charts,
            "ai_review": ai_review,
            "ai_error": ai_error,
            "key_observations": key_observations,
            "evidence": full_evidence,
            "data_source": data_loader.get_data_source(),
        })

    except Exception as e:
        return jsonify({"error": f"Analysis failed: {str(e)}"}), 500


def _clean_record(record: dict) -> dict:
    """Make a dataset record JSON-safe (convert NaN to None, numpy types to native)."""
    if record is None:
        return None
    clean = {}
    for k, v in record.items():
        try:
            if v != v:  # NaN check
                clean[k] = None
                continue
        except Exception:
            pass
        if hasattr(v, "item"):  # numpy scalar
            v = v.item()
        clean[k] = v
    return clean


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

