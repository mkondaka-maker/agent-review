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
    Send structured, Python-calculated evidence to Google Gemini AI (or Anthropic Claude)
    and ask it to explain only what's supplied.
    """
    gemini_key = os.environ.get("GEMINI_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    user_prompt = (
        "Here is the evidence calculated by Python for this financial review. "
        "Only discuss the metrics provided below. Do not reference any other financial metric:\n\n"
        + json.dumps(evidence, indent=2, default=str)
    )

    # 1. Google Gemini AI integration
    if gemini_key:
        try:
            from google import genai
            from google.genai import types

            gemini_client = genai.Client(api_key=gemini_key)
            gemini_model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            config = types.GenerateContentConfig(
                system_instruction=REVIEW_SYSTEM_PROMPT,
                temperature=0.2,
                max_output_tokens=1500,
            )
            response = gemini_client.models.generate_content(
                model=gemini_model,
                contents=user_prompt,
                config=config,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as err:
            print(f"[agent] Gemini API call failed ({err}).")

    # 2. Anthropic Claude fallback integration
    if anthropic_key:
        try:
            import anthropic
            claude_client = anthropic.Anthropic(api_key=anthropic_key)
            claude_model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            response = claude_client.messages.create(
                model=claude_model,
                max_tokens=1200,
                system=REVIEW_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
            return "\n".join(text_parts).strip()
        except Exception as err:
            print(f"[agent] Anthropic API call failed ({err}).")

    raise RuntimeError("AI narrative unavailable: GEMINI_API_KEY or ANTHROPIC_API_KEY is not configured or failed.")


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
