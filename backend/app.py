"""
app.py
Flask Web Backend for Financial Statement Review Agent.
Connects to Supabase PostgreSQL database (with CSV fallback), computes financial metrics,
generates trend/comparison charts, and produces Gemini AI reviews.
"""

import os
from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

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
    if not company:
        return jsonify({"error": "Please select a company."}), 400
    try:
        return jsonify({"years": data_loader.get_years(company)})
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
    company = payload.get("company")
    year = payload.get("year")
    question = payload.get("question", "")

    if not company:
        return jsonify({"error": "No company selected. Please select a company."}), 400
    if not year:
        return jsonify({"error": "No year selected. Please select a year."}), 400
    if not question or not question.strip():
        return jsonify({"error": "Please enter a financial question."}), 400

    try:
        year = int(year)
        df = data_loader.load_dataset()
        metric_columns = data_loader.get_available_metric_columns(df)

        current_record = data_loader.get_year_data(company, year)
        if current_record is None:
            return jsonify({"error": f"No data found for {company} in {year}."}), 404

        previous_record = data_loader.get_previous_year_data(company, year)
        previous_year = int(previous_record["Year"]) if previous_record is not None else None

        # 1. Detect Intent
        intent = agent.detect_intent(question)
        intent_config = INTENT_SECTION_MAP.get(intent, INTENT_SECTION_MAP["complete"])

        # 2. Core calculations
        comparison = {}
        if previous_record is not None:
            comparison = fa.compare_years(current_record, previous_record, metric_columns)
        margins_current = fa.compute_margins(current_record)
        margins_previous = fa.compute_margins(previous_record) if previous_record else {}
        all_kpi_cards = fa.build_kpi_cards(current_record, metric_columns)

        # 3. Validation / variance detection
        missing = val.detect_missing_values(current_record, metric_columns)
        duplicates = val.detect_duplicate_records(df)
        variances = val.detect_variances(comparison) if comparison else []
        ranked = val.rank_variances(comparison) if comparison else {"top_increases": [], "top_decreases": []}
        anomalies = val.detect_anomalies(comparison) if comparison else []

        # 4. Filter KPI Cards based on intent
        if intent_config["kpis"] is None:
            kpi_cards = all_kpi_cards
        else:
            target_kpis_lower = [k.lower() for k in intent_config["kpis"]]
            kpi_cards = [
                card for card in all_kpi_cards
                if any(t in card["metric"].lower() or card["metric"].lower() in t for t in target_kpis_lower)
            ]

        # 5. Build Charts conditionally based on intent
        company_df = data_loader.get_company_data(company)
        allowed_charts = intent_config["charts"]

        charts = {}
        
        # Revenue trend
        if allowed_charts is None or "revenue_trend" in allowed_charts:
            charts["revenue_trend"] = cg.generate_trend_chart_data(company_df, "Revenue")
        else:
            charts["revenue_trend"] = {"available": False}

        # Net income trend
        if allowed_charts is None or "net_income_trend" in allowed_charts:
            charts["net_income_trend"] = cg.generate_trend_chart_data(company_df, "Net Income")
        else:
            charts["net_income_trend"] = {"available": False}

        # Current vs previous revenue
        if allowed_charts is None or "current_vs_previous_revenue" in allowed_charts:
            charts["current_vs_previous_revenue"] = cg.generate_current_vs_previous_chart(
                "Revenue",
                comparison.get("Revenue", {}).get("current"),
                comparison.get("Revenue", {}).get("previous"),
                year,
                previous_year,
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
        if allowed_charts is None or "profitability" in allowed_charts:
            charts["profitability"] = cg.generate_profitability_chart(company_df)
        else:
            charts["profitability"] = {"available": False}

        # 6. Assemble scoped evidence package for AI (and response evidence block)
        full_evidence = {
            "company": company,
            "year": year,
            "previous_year": previous_year,
            "question": question,
            "intent": intent,
            "current_year_values": _clean_record(current_record),
            "previous_year_values": _clean_record(previous_record) if previous_record else None,
            "comparison": comparison,
            "margins_current_year": margins_current,
            "margins_previous_year": margins_previous,
            "variances": variances,
            "ranked_variances": ranked,
            "anomalies": anomalies,
            "missing_metrics": missing,
        }

        if intent == "complete" or intent_config["kpis"] is None:
            scoped_evidence = full_evidence
        else:
            target_kpis_lower = [k.lower() for k in intent_config["kpis"]]
            
            # Filter current and previous values
            scoped_current = {
                k: v for k, v in _clean_record(current_record).items()
                if k in ["Year", "Company", "Ticker"] or any(t in k.lower() or k.lower() in t for t in target_kpis_lower)
            }
            scoped_previous = (
                {
                    k: v for k, v in _clean_record(previous_record).items()
                    if k in ["Year", "Company", "Ticker"] or any(t in k.lower() or k.lower() in t for t in target_kpis_lower)
                }
                if previous_record else None
            )
            scoped_comp = {
                k: v for k, v in comparison.items()
                if any(t in k.lower() or k.lower() in t for t in target_kpis_lower)
            }
            
            scoped_evidence = {
                "company": company,
                "year": year,
                "previous_year": previous_year,
                "question": question,
                "intent": intent,
                "current_year_values": scoped_current,
                "previous_year_values": scoped_previous,
                "comparison": scoped_comp,
                "margins_current_year": margins_current if intent == "profitability" else {},
                "margins_previous_year": margins_previous if intent == "profitability" else {},
                "variances": variances if intent == "variances" else [],
            }

        # 7. AI interpretation using scoped evidence
        ai_review = None
        ai_error = None
        try:
            ai_review = agent.generate_financial_review(scoped_evidence)
        except Exception as e:
            ai_error = str(e)

        key_observations = agent.generate_key_observations(scoped_evidence)

        # Return payload with sections_to_show
        return jsonify({
            "company": company,
            "year": year,
            "previous_year": previous_year,
            "intent": intent,
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
            "evidence": scoped_evidence,
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
