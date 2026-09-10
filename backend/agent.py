"""
agent.py
The AI agent's job is limited to two things:
  1. Understand the user's natural-language intent (which analysis/metrics are needed, even from messy, fuzzy, or unstructured prompts).
  2. Turn Python-calculated evidence into a written, evidence-grounded review using LLM providers (Groq, Google Gemini, OpenRouter, OpenAI).
It NEVER performs financial math itself.
"""

import os
import re
import json
import difflib
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

# Standard User-Agent to avoid Cloudflare/WAF block (HTTP 403 / code 1010)
HTTP_HEADERS_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# Dictionary of popular ticker symbols, product names, executive names, and colloquial aliases mapped to canonical company names
COMPANY_ALIASES = {
    "aapl": "Apple", "apple": "Apple", "iphone": "Apple", "ipad": "Apple", "mac": "Apple", "tim cook": "Apple", "steve jobs": "Apple",
    "msft": "Microsoft", "microsoft": "Microsoft", "windows": "Microsoft", "azure": "Microsoft", "satya": "Microsoft", "bill gates": "Microsoft",
    "goog": "Google", "googl": "Google", "google": "Google", "alphabet": "Google", "youtube": "Google", "android": "Google", "sundar": "Google",
    "nvda": "Nvidia", "nvidia": "Nvidia", "geforce": "Nvidia", "jensen": "Nvidia", "rtx": "Nvidia",
    "amzn": "Amazon", "amazon": "Amazon", "aws": "Amazon", "prime": "Amazon", "bezos": "Amazon", "andy jassy": "Amazon",
    "tsla": "Tesla", "tesla": "Tesla", "elon": "Tesla", "musk": "Tesla", "cybertruck": "Tesla",
    "pypl": "PayPal", "paypal": "PayPal", "venmo": "PayPal",
    "mcd": "McDonald's", "mcdonalds": "McDonald's", "mcdonald": "McDonald's", "mc donalds": "McDonald's", "golden arches": "McDonald's",
    "intc": "Intel", "intel": "Intel", "chipzilla": "Intel", "pat gelsinger": "Intel",
    "shldq": "Sears", "sears": "Sears", "sears holdings": "Sears", "eddie lampert": "Sears",
    "bcs": "Barclays", "barclays": "Barclays", "barclay": "Barclays",
    "pcg": "PG&E", "pg&e": "PG&E", "pge": "PG&E", "pacific gas": "PG&E", "pacific gas & electric": "PG&E",
    "aig": "AIG", "american international group": "AIG",
    "meta": "Meta", "facebook": "Meta", "fb": "Meta", "instagram": "Meta", "whatsapp": "Meta", "zuck": "Meta", "zuckerberg": "Meta",
    "nflx": "Netflix", "netflix": "Netflix",
    "wmt": "Walmart", "walmart": "Walmart", "wal-mart": "Walmart",
    "jpm": "JPMorgan Chase", "jpmorgan": "JPMorgan Chase", "jp morgan": "JPMorgan Chase", "chase": "JPMorgan Chase", "dimon": "JPMorgan Chase", "jamie dimon": "JPMorgan Chase",
}

# Word-to-number mapping for informal spoken years
WORD_YEARS = {
    "twenty ten": 2010, "twenty eleven": 2011, "twenty twelve": 2012, "twenty thirteen": 2013,
    "twenty fourteen": 2014, "twenty fifteen": 2015, "twenty sixteen": 2016, "twenty seventeen": 2017,
    "twenty eighteen": 2018, "twenty nineteen": 2019, "twenty twenty": 2020, "twenty twenty-one": 2021,
    "twenty twenty one": 2021, "twenty twenty-two": 2022, "twenty twenty two": 2022,
    "twenty twenty-three": 2023, "twenty twenty three": 2023, "twenty twenty-four": 2024, "twenty twenty four": 2024,
}

METRIC_KEYWORDS = {
    "Revenue": ["revenue", "revenues", "sales", "top line", "gross sales", "turnover", "income from sales"],
    "Gross Profit": ["gross profit", "gross margin", "gross income"],
    "Net Income": ["net income", "bottom line", "profit", "profits", "earnings", "net profit"],
    "Earning Per Share": ["eps", "earning per share", "earnings per share", "per share earnings"],
    "EBITDA": ["ebitda", "operating earnings", "operating profit"],
    "Shareholder Equity": ["shareholder equity", "stockholder equity", "equity", "book value", "net worth", "total equity"],
    "Cash Flow Operating": ["operating cash", "cash from operations", "operating cash flow", "cash flow operating"],
    "Cash Flow Investing": ["investing cash", "cash from investing", "capital expenditures", "capex", "cash flow investing"],
    "Cash Flow Financial": ["financing cash", "financial cash", "cash from financing", "cash flow financing", "cash flow financial"],
    "Current Ratio": ["current ratio", "liquidity ratio", "working capital ratio", "liquidity"],
    "Debt Equity Ratio": ["debt equity", "debt to equity", "debt/equity", "leverage ratio", "gearing", "debt"],
    "ROE": ["roe", "return on equity"],
    "ROA": ["roa", "return on assets"],
    "ROI": ["roi", "return on investment"],
    "Net Profit Margin": ["net profit margin", "profit margin", "net margin", "margins"],
    "Free Cash Flow Per Share": ["free cash flow", "fcf", "fcf per share", "free cash"],
    "Market Cap": ["market cap", "market capitalization", "company valuation", "market value", "valuation"],
    "Number of Employees": ["employees", "employee", "headcount", "workforce", "staff"],
}


def extract_target_metrics(question: str) -> list:
    """Extract any specific metrics mentioned in the user's query."""
    q = (question or "").lower()
    metrics = []
    for metric_name, aliases in METRIC_KEYWORDS.items():
        if any(re.search(r"\b" + re.escape(alias) + r"\b", q) or alias in q for alias in aliases):
            metrics.append(metric_name)
    return metrics


def detect_intent(question: str) -> str:
    """
    Classifies natural language user queries into a specific intent category.
    Returns one of:
      - 'complete' (default fallback, includes everything)
      - 'revenue'
      - 'profitability'
      - 'cash_flow'
      - 'returns'
      - 'balance_sheet'
      - 'variances'
      - 'market'
      - 'comparison'
    """
    q = (question or "").lower().strip()

    # Comparison intent (comparing multiple companies or explicit cross-entity)
    if any(w in q for w in ["compare", "versus", "vs", "better than", "higher than", "difference between"]):
        if any(c in q for c in ["apple", "microsoft", "amazon", "google", "nvidia", "tesla", "meta", "netflix", "intel"]):
            # If two distinct company indicators exist
            count_comps = sum(1 for k in ["apple", "microsoft", "amazon", "google", "nvidia", "tesla", "meta", "netflix", "intel", "paypal", "mcdonald", "sears", "barclays", "pge", "aig"] if k in q)
            if count_comps >= 2:
                return "comparison"

    # Full / complete overview triggers
    if any(w in q for w in ["complete", "full", "everything", "overview", "all metrics", "complete review", "entire", "financial statement", "how did"]):
        if not any(k in q for k in ["margin", "revenue only", "cash flow only", "balance sheet only", "liquidity", "debt"]):
            return "complete"

    # Specific category keyword matching
    if any(w in q for w in ["revenue", "sales", "top line", "turnover", "gross sales"]):
        if not any(w in q for w in ["net income", "margin", "profit", "cash flow", "equity", "roe"]):
            return "revenue"

    if any(w in q for w in ["profitability", "margin", "margins", "gross profit", "ebitda", "profit", "profits", "net income", "earnings"]):
        return "profitability"

    if any(w in q for w in ["cash flow", "operating cash", "investing cash", "financing cash", "free cash", "fcf"]):
        return "cash_flow"

    if any(w in q for w in ["roe", "roa", "roi", "return on equity", "return on assets", "return on investment", "return rate"]):
        return "returns"

    if any(w in q for w in ["balance sheet", "equity", "shareholder equity", "current ratio", "debt", "leverage", "assets", "liabilities", "liquidity"]):
        return "balance_sheet"

    if any(w in q for w in ["variance", "variances", "yoy", "year over year", "compared", "compare", "previous year", "change", "diff", "difference", "growth"]):
        return "variances"

    if any(w in q for w in ["market cap", "eps", "per share", "employee", "employees", "valuation", "headcount"]):
        return "market"

    return "complete"


# --- AI-Powered Query Parsing with Groq ---------------------------------

QUERY_PARSER_SYSTEM_PROMPT = """You are an intelligent financial query understanding parser.
Your task is to analyze unstructured, informal, or messy natural-language user queries about financial statements and extract structured search parameters to query a Supabase PostgreSQL database.

You are given:
1. Available Companies in Database: {available_companies}
2. Available Metric Names: {available_metrics}

Rules:
- Identify the primary company from the user's text. Map tickers (e.g. AAPL -> Apple, MSFT -> Microsoft, NVDA -> Nvidia), product names (iPhone -> Apple, Azure -> Microsoft), executive names (Tim Cook -> Apple, Elon Musk -> Tesla, Satya -> Microsoft), or common typos/nicknames to the EXACT canonical company name from the Available Companies list.
- If the user is comparing two companies (e.g., "Apple vs Microsoft in 2022"), set "company" to the first company and "comparison_company" to the second. Otherwise "comparison_company" should be null.
- Identify the target fiscal year as an integer (e.g., 2022, 2021). Handle 2-digit years like '22' -> 2022, words like 'twenty twenty-two' -> 2022, 'last year' -> 2023 or null if unspecified.
- Identify explicit comparison year if mentioned (e.g., "vs 2021", "compared to 2020", "over 2019").
- Identify intent: choose from ["complete", "revenue", "profitability", "cash_flow", "returns", "balance_sheet", "variances", "market", "comparison"].
- Identify target_metrics from the Available Metrics list that match the user's interest.
- Provide a brief 1-sentence "interpreted_query" summarizing the intent.

Return ONLY a valid, raw JSON object in this exact format (no markdown fences, no text outside JSON):
{{
  "company": "Apple",
  "comparison_company": null,
  "year": 2022,
  "previous_year": 2021,
  "intent": "revenue",
  "target_metrics": ["Revenue", "Gross Profit"],
  "interpreted_query": "Analyzing Apple's revenue and gross profit in FY2022 compared to FY2021"
}}
"""


def _clean_think_tags(text: str) -> str:
    """Remove any <think>...</think> reasoning traces emitted by reasoning models."""
    if not text:
        return ""
    # Strip complete <think>...</think> blocks
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    # Strip unclosed or orphaned <think> tags
    if "<think>" in text.lower():
        if "</think>" in text.lower():
            text = re.sub(r"[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
        else:
            text = re.sub(r"<think>[\s\S]*?(?=\n\n|\n#|\n\*\*|\n[A-Z]|$)", "", text, flags=re.IGNORECASE)
    return text.strip()


def _fetch_groq_models(groq_key: str) -> list:
    """Dynamically query Groq API to discover active chat completion models."""
    try:
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": HTTP_HEADERS_USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=6) as res:
            data = json.loads(res.read().decode("utf-8"))
            model_ids = [m["id"] for m in data.get("data", [])]
            chat_models = [
                m for m in model_ids
                if not any(x in m for x in ["whisper", "guard", "safeguard", "orpheus"])
            ]
            return chat_models
    except Exception as e:
        return []


def extract_query_with_groq(
    question: str,
    available_companies: list = None,
    default_company: str = None,
    default_year: int = None,
) -> dict:
    """
    Uses Groq LLM with low-latency chat completion to parse messy or fuzzy user queries into structured search parameters.
    """
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    if not groq_key or not question:
        return None

    available_companies = available_companies or list(COMPANY_ALIASES.values())
    available_metrics = list(METRIC_KEYWORDS.keys())

    system_prompt = QUERY_PARSER_SYSTEM_PROMPT.format(
        available_companies=", ".join(sorted(list(set(available_companies)))),
        available_metrics=", ".join(available_metrics),
    )

    candidate_models = [
        os.environ.get("GROQ_MODEL", "qwen/qwen3.6-27b"),
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-120b",
        "groq/compound-mini",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
        "allam-2-7b",
    ]
    candidate_models = list(dict.fromkeys([m for m in candidate_models if m]))

    for model in candidate_models:
        try:
            req_data = json.dumps({
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"User Query: {question}\nDefaults if unspecified: Company='{default_company}', Year='{default_year}'"}
                ],
                "temperature": 0.0,
                "max_tokens": 400,
                "response_format": {"type": "json_object"}
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": HTTP_HEADERS_USER_AGENT,
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=6) as res:
                body = json.loads(res.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                cleaned = _clean_think_tags(content)
                # Parse JSON
                parsed_json = json.loads(cleaned)
                if isinstance(parsed_json, dict) and (parsed_json.get("company") or parsed_json.get("year")):
                    return parsed_json
        except Exception as e:
            # Continue to next model or fallback
            continue

    return None


def _heuristic_parse_user_query(
    question: str,
    available_companies: list = None,
    default_company: str = None,
    default_year: int = None,
) -> dict:
    """
    Robust heuristic / regex / fuzzy fallback parser for user queries when LLM is unavailable.
    """
    q = (question or "").lower().strip()
    available_companies = available_companies or []

    # 1. Company Extraction
    detected_company = None
    comparison_company = None

    # Replace spoken words for years first so they don't interfere
    for word_yr, num_yr in WORD_YEARS.items():
        if word_yr in q:
            q = q.replace(word_yr, str(num_yr))

    clean_words = re.findall(r"[a-zA-Z0-9&']+", q)

    # Check for alias matches
    found_comps = []
    for w in clean_words:
        if w in COMPANY_ALIASES:
            c = COMPANY_ALIASES[w]
            if c not in found_comps:
                found_comps.append(c)

    for alias, comp in sorted(COMPANY_ALIASES.items(), key=lambda x: -len(x[0])):
        if alias in q and comp not in found_comps:
            found_comps.append(comp)

    if available_companies:
        for comp in available_companies:
            if comp.lower() in q and comp not in found_comps:
                found_comps.append(comp)

    if found_comps:
        detected_company = found_comps[0]
        if len(found_comps) > 1:
            comparison_company = found_comps[1]
    elif available_companies:
        for w in clean_words:
            matches = difflib.get_close_matches(w.capitalize(), available_companies, n=1, cutoff=0.7)
            if matches:
                detected_company = matches[0]
                break

    final_company = detected_company or default_company

    # 2. Fiscal Year & Comparison Year Extraction
    # Handles 4-digit years 1990-2029, or 2-digit years with apostrophe / context like '22 or in 22
    years_found = [int(y) for y in re.findall(r"\b(20[0-2][0-9]|199[0-9])\b", q)]
    if not years_found:
        # Check for 2-digit shorthand like '22 or in 22
        two_digit = re.findall(r"(?:in|for|fy|'|’)[\s]*([12][0-9])\b", q)
        if two_digit:
            years_found = [2000 + int(two_digit[0])]

    comp_year_match = re.search(r"(?:vs\.?|versus|compared to|against|over|from)\s*(?:year\s*|fiscal\s*|fy\s*)?(20[0-2][0-9]|199[0-9])\b", q)
    previous_year_explicit = int(comp_year_match.group(1)) if comp_year_match else None

    target_year = None
    if years_found:
        if previous_year_explicit and len(years_found) > 1:
            candidates = [y for y in years_found if y != previous_year_explicit]
            target_year = candidates[0] if candidates else years_found[0]
        else:
            if len(years_found) > 1 and not previous_year_explicit:
                sorted_years = sorted(years_found, reverse=True)
                target_year = sorted_years[0]
                previous_year_explicit = sorted_years[1]
            else:
                target_year = years_found[0]

    final_year = target_year or default_year

    intent = detect_intent(q)
    target_metrics = extract_target_metrics(q)

    # Human-friendly interpreted query
    comp_str = final_company or "Company"
    yr_str = f"FY{final_year}" if final_year else "Latest Fiscal Period"
    prev_str = f" vs FY{previous_year_explicit}" if previous_year_explicit else ""
    metric_str = f" focusing on {', '.join(target_metrics)}" if target_metrics else ""
    interpreted = f"Analyzing {comp_str} ({yr_str}{prev_str}){metric_str}"

    return {
        "company": final_company,
        "comparison_company": comparison_company,
        "year": final_year,
        "previous_year": previous_year_explicit,
        "intent": intent,
        "target_metrics": target_metrics,
        "interpreted_query": interpreted,
    }


def parse_user_query(
    question: str,
    available_companies: list = None,
    default_company: str = None,
    default_year: int = None,
) -> dict:
    """
    Orchestrates Groq-powered natural language analysis for messy queries with instant fallback to heuristic parsing.
    """
    q_str = (question or "").strip()
    available_companies = available_companies or []

    # Try Groq AI extraction if query is present
    if q_str:
        groq_result = extract_query_with_groq(
            question=q_str,
            available_companies=available_companies,
            default_company=default_company,
            default_year=default_year,
        )
        if groq_result and isinstance(groq_result, dict):
            # Normalize fields
            company = groq_result.get("company") or default_company
            comparison_company = groq_result.get("comparison_company")
            year = groq_result.get("year") or default_year
            prev_year = groq_result.get("previous_year")
            intent = groq_result.get("intent") or "complete"
            target_metrics = groq_result.get("target_metrics") or []
            interpreted = groq_result.get("interpreted_query") or f"Analyzing {company or 'Company'} for FY{year or 'latest'}"

            # Make sure year is int if present
            if year is not None:
                try:
                    year = int(year)
                except Exception:
                    year = default_year
            if prev_year is not None:
                try:
                    prev_year = int(prev_year)
                except Exception:
                    prev_year = None

            return {
                "company": company,
                "comparison_company": comparison_company,
                "year": year,
                "previous_year": prev_year,
                "intent": intent,
                "target_metrics": target_metrics,
                "interpreted_query": interpreted,
            }

    # Fallback to local heuristic parser
    return _heuristic_parse_user_query(
        question=q_str,
        available_companies=available_companies,
        default_company=default_company,
        default_year=default_year,
    )


# --- AI-generated review -----------------------------------------------

REVIEW_SYSTEM_PROMPT = """You are a senior financial analyst and executive review assistant.

YOUR MISSION:
Directly answer the user's specific financial question using ONLY the provided pre-calculated evidence derived from the Supabase PostgreSQL database.

STRICT OPERATIONAL RULES:
1. DIRECT ANSWER FIRST: Begin immediately with a direct, comprehensive executive answer to the user's prompt using exact numbers from the evidence.
2. EVIDENCE GROUNDING: Only discuss metrics and figures provided in the JSON evidence. Do NOT invent, speculate, or project values that are omitted.
3. PRE-CALCULATED FIGURES: You are provided with exact numbers already calculated by Python. Do NOT recalculate or recompute math; reference the given numbers, margins, growth percentages, and ratios directly.
4. STRUCTURE & CLARITY: Format your response with clean markdown headings, structured bullet points, and concise summaries.
   - **Executive Takeaway**: 1-2 sentence direct answer to the user's question.
   - **Financial Performance & Movements**: Exact revenue, profit, margins, cash flow, and YoY % changes.
   - **Operational Insights & Balance Sheet Health**: Liquidity (Current Ratio), Leverage (Debt/Equity), and Capital Efficiency (ROE/ROA/ROI) if relevant.
   - **Noteworthy Variances & Anomalies**: Flag any significant variances (>20%) or trend anomalies.
5. IF MULTI-COMPANY OR COMPARISON IS REQUESTED: Provide a side-by-side comparison highlighting key advantages and differences in revenue, margins, and valuation.
6. IF A METRIC OR REASON IS NOT IN THE DATA: Explicitly state that the database record does not contain operational commentary or omitted metrics.
"""


def generate_financial_review(evidence: dict, user_question: str = None) -> str:
    """
    Sends structured, Python-calculated evidence to LLM API (Groq as primary, Gemini/OpenRouter/OpenAI as fallbacks)
    and produces an evidence-grounded review answering the user's prompt.
    """
    q_str = user_question or evidence.get("question", "Provide a financial analysis.")
    user_prompt = (
        f"User Query: {q_str}\n\n"
        "Here is the verified financial evidence queried from the Supabase PostgreSQL database and calculated in Python. "
        "Directly answer the user's query referencing the provided evidence numbers:\n\n"
        + json.dumps(evidence, indent=2, default=str)
    )

    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    gemini_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    openrouter_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    # 1. Groq Cloud API integration
    if groq_key:
        configured_model = (os.environ.get("GROQ_MODEL") or "").strip()
        dynamic_models = _fetch_groq_models(groq_key)
        
        preferred_models = [
            "qwen/qwen3.6-27b",
            "openai/gpt-oss-120b",
            "groq/compound-mini",
            "openai/gpt-oss-20b",
            "qwen/qwen3.8-27b",
            "groq/compound",
            "llama-3.3-70b-versatile",
            "allam-2-7b",
        ]

        candidate_models = []
        if configured_model:
            candidate_models.append(configured_model)
        
        for m in preferred_models:
            if m in dynamic_models and m not in candidate_models:
                candidate_models.append(m)
        for m in dynamic_models:
            if m not in candidate_models:
                candidate_models.append(m)
        for m in preferred_models:
            if m not in candidate_models:
                candidate_models.append(m)

        for model in candidate_models:
            try:
                req_data = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": HTTP_HEADERS_USER_AGENT,
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=25) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    text = body["choices"][0]["message"]["content"]
                    cleaned = _clean_think_tags(text)
                    if cleaned:
                        return cleaned
            except urllib.error.HTTPError as err:
                err_msg = ""
                try:
                    err_msg = err.read().decode("utf-8")
                except Exception:
                    pass
                print(f"[agent] Groq model '{model}' HTTP {err.code}: {err_msg or err}")
            except Exception as err:
                print(f"[agent] Groq model '{model}' failed: {err}")

    # 2. Google Gemini API integration
    if gemini_key:
        gemini_models = [
            os.environ.get("GEMINI_MODEL", "gemini-1.5-flash"),
            "gemini-1.5-flash",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
        ]
        gemini_models = list(dict.fromkeys([m for m in gemini_models if m]))
        
        for model in gemini_models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
                req_data = json.dumps({
                    "system_instruction": {"parts": [{"text": REVIEW_SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": user_prompt}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}
                }).encode("utf-8")
                
                req = urllib.request.Request(
                    url,
                    data=req_data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": HTTP_HEADERS_USER_AGENT,
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=25) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    candidates = body.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "")
                            cleaned = _clean_think_tags(text)
                            if cleaned:
                                return cleaned
            except Exception as err:
                print(f"[agent] Gemini model '{model}' failed: {err}")

    # 3. OpenRouter API integration
    if openrouter_key:
        openrouter_models = [
            os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-7b-instruct:free",
        ]
        openrouter_models = list(dict.fromkeys([m for m in openrouter_models if m]))

        for model in openrouter_models:
            try:
                req_data = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://openrouter.ai/api/v1/chat/completions",
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "User-Agent": HTTP_HEADERS_USER_AGENT,
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=25) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    text = body["choices"][0]["message"]["content"]
                    cleaned = _clean_think_tags(text)
                    if cleaned:
                        return cleaned
            except Exception as err:
                print(f"[agent] OpenRouter model '{model}' failed: {err}")

    # 4. OpenAI API integration
    if openai_key:
        openai_models = [
            os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            "gpt-4o-mini",
            "gpt-4o",
            "gpt-3.5-turbo",
        ]
        openai_models = list(dict.fromkeys([m for m in openai_models if m]))

        for model in openai_models:
            try:
                req_data = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1500
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://api.openai.com/v1/chat/completions",
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                        "User-Agent": HTTP_HEADERS_USER_AGENT,
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=25) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    text = body["choices"][0]["message"]["content"]
                    cleaned = _clean_think_tags(text)
                    if cleaned:
                        return cleaned
            except Exception as err:
                print(f"[agent] OpenAI model '{model}' failed: {err}")

    raise RuntimeError("AI narrative generation failed: Please configure a valid GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or OPENAI_API_KEY.")


def generate_key_observations(evidence: dict) -> list:
    """
    Derives concise, evidence-backed observation strings directly from the calculated evidence.
    """
    observations = []
    comparison = evidence.get("comparison", {})

    for metric, values in comparison.items():
        pct = values.get("percent_change")
        current = values.get("current")
        previous = values.get("previous")
        if pct is None or current is None or previous is None:
            continue
        direction = "increased" if pct > 0 else "decreased"
        observations.append(
            f"{metric} {direction} by {abs(pct)}% year-over-year, from {previous:,.2f} to {current:,.2f}." if isinstance(current, (int, float)) and isinstance(previous, (int, float)) else f"{metric} {direction} by {abs(pct)}% YoY."
        )

    variances = evidence.get("variances", [])
    for v in variances:
        observations.append(
            f"Significant {v['direction']} in {v['metric']}: {v['percent_change']}% change, exceeding the configured 20% variance threshold."
        )

    anomalies = evidence.get("anomalies", [])
    for a in anomalies:
        observations.append(
            f"Trend Anomaly: {a['metric']} moved {a['metric_direction']} ({a['percent_change']}%) contrary to overall {a['trend_metric']} {a['trend_direction']} trend."
        )

    # Comparison company observations
    comp_comp = evidence.get("comparison_company_data")
    if comp_comp and comp_comp.get("company"):
        observations.append(
            f"Cross-company comparison retrieved for {comp_comp['company']} ({comp_comp.get('year')})."
        )

    return observations
