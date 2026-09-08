"""
agent.py
The AI agent's job is limited to two things:
  1. Understand the user's natural-language intent (which analysis/metrics are needed).
  2. Turn Python-calculated evidence into a written, evidence-grounded review using Google Gemini AI or Anthropic Claude.
It NEVER performs financial math itself.
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

# --- Intent classification --------------------------------------------

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
    """
    q = (question or "").lower().strip()

    # HARD REQUIREMENT: Check for complete/full review triggers FIRST before keyword overlap
    if any(w in q for w in ["complete", "full", "everything", "overview", "all metrics", "complete review"]):
        return "complete"

    # Category Keyword Matching
    if any(w in q for w in ["revenue", "sales", "top line"]):
        return "revenue"

    if any(w in q for w in ["profitability", "margin", "margins", "gross profit", "ebitda", "profit"]):
        return "profitability"

    if any(w in q for w in ["cash flow", "operating cash", "investing cash", "financing cash", "free cash"]):
        return "cash_flow"

    if any(w in q for w in ["roe", "roa", "roi", "return on equity", "return on assets", "return on investment"]):
        return "returns"

    if any(w in q for w in ["balance sheet", "equity", "shareholder equity", "current ratio", "debt"]):
        return "balance_sheet"

    if any(w in q for w in ["variance", "variances", "yoy", "year over year", "compared", "compare", "previous year", "change"]):
        return "variances"

    if any(w in q for w in ["market cap", "eps", "per share", "employee", "employees"]):
        return "market"

    # Fallback to complete review if no specific intent matches
    return "complete"


# --- AI-generated review -----------------------------------------------

REVIEW_SYSTEM_PROMPT = """You are a financial statement review assistant.

STRICT RULES:
- Only discuss the financial metrics provided in the evidence below. Do not reference, infer, or speculate on any other financial metric that is omitted from the evidence.
- You will be given ONLY pre-calculated evidence (numbers already computed by Python). Do not perform or recompute any math yourself; use the given numbers exactly as provided.
- Never invent financial values, metrics, or years that are not present in the evidence.
- Never invent business causes (e.g. "due to increased competition" or "due to a new product launch") unless such context is explicitly present in the evidence. If a cause is not established by the data, explicitly say the dataset does not establish the specific cause.
- Structure your response focusing strictly on the provided financial metrics and evidence.
- Keep it concise, professional, and grounded. Reference exact numbers from the evidence when making a claim.
- If a metric or section has no relevant evidence, state briefly that data is not available instead of inventing values.
"""


def generate_financial_review(evidence: dict) -> str:
    """
    Send structured, Python-calculated evidence to Groq API
    and ask it to explain only what's supplied.
    """
    groq_key = os.environ.get("GROQ_API_KEY")

    user_prompt = (
        "Here is the evidence calculated by Python for this financial review. "
        "Only discuss the metrics provided below. Do not reference any other financial metric:\n\n"
        + json.dumps(evidence, indent=2, default=str)
    )

    # Groq Cloud API integration (ONLY provider used)
    groq_key = (os.environ.get("GROQ_API_KEY") or "").strip()
    openrouter_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    openai_key = (os.environ.get("OPENAI_API_KEY") or "").strip()

    import urllib.request

    # 1. Groq Cloud API integration
    if groq_key:
        models_to_try = [
            os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama3-70b-8192",
            "mixtral-8x7b-32768",
        ]
        models_to_try = list(dict.fromkeys([m for m in models_to_try if m]))

        for model in models_to_try:
            try:
                req_data = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 1200
                }).encode("utf-8")

                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=req_data,
                    headers={
                        "Authorization": f"Bearer {groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    },
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as res:
                    body = json.loads(res.read().decode("utf-8"))
                    text = body["choices"][0]["message"]["content"]
                    if text:
                        return text.strip()
            except Exception as err:
                print(f"[agent] Groq model '{model}' failed: {err}")

    # 2. OpenRouter API integration
    if openrouter_key:
        try:
            req_data = json.dumps({
                "model": os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                "messages": [
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 1200
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {openrouter_key}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                body = json.loads(res.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"]
                if text:
                    return text.strip()
        except Exception as err:
            print(f"[agent] OpenRouter API failed: {err}")

    # 3. OpenAI API integration
    if openai_key:
        try:
            req_data = json.dumps({
                "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 1200
            }).encode("utf-8")

            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": "application/json",
                },
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as res:
                body = json.loads(res.read().decode("utf-8"))
                text = body["choices"][0]["message"]["content"]
                if text:
                    return text.strip()
        except Exception as err:
            print(f"[agent] OpenAI API failed: {err}")

    # 4. Standalone Rule-Based AI Review Fallback (Guaranteed to work 100% of the time, zero API dependence)
    return generate_rule_based_review(evidence)


def generate_rule_based_review(evidence: dict) -> str:
    """
    Generate an executive financial review narrative using deterministic python logic.
    Guarantees 100% reliability with zero external network or API dependencies.
    """
    company = evidence.get("company", "Company")
    year = evidence.get("year", "N/A")
    prev_year = evidence.get("previous_year", "N/A")
    comparison = evidence.get("comparison", {})

    paragraphs = [
        f"### Executive Financial Review: {company} ({prev_year} vs. {year})\n",
        f"This executive narrative summarizes the financial performance of **{company}** for fiscal year **{year}** compared to **{prev_year}**, based strictly on Python-calculated evidence.\n",
        "#### Key Performance Indicators & Trends:\n"
    ]

    for metric, data in comparison.items():
        curr = data.get("current")
        prev = data.get("previous")
        pct = data.get("percent_change")
        if curr is not None and prev is not None and pct is not None:
            trend = "growth" if pct > 0 else "decline"
            paragraphs.append(f"- **{metric}**: Reported at **{curr}** in {year} compared to **{prev}** in {prev_year}, representing a **{pct}%** YoY {trend}.")

    variances = evidence.get("variances", [])
    if variances:
        paragraphs.append("\n#### Notable Financial Variances:")
        for v in variances:
            paragraphs.append(f"- **{v['metric']}**: Flagged with a significant **{v['direction']}** of **{v['percent_change']}%**.")

    paragraphs.append("\n*Note: Review generated directly from verified financial calculation engine.*")
    return "\n".join(paragraphs)


def generate_key_observations(evidence: dict) -> list:
    """
    Derived simple, evidence-backed observation strings directly from the calculated evidence.
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
            f"{metric} {direction} by {abs(pct)}% year-over-year, from {previous} to {current}."
        )

    variances = evidence.get("variances", [])
    for v in variances:
        observations.append(
            f"Significant {v['direction']} in {v['metric']}: {v['percent_change']}% change, exceeding the configured threshold."
        )

    return observations
