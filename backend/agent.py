"""
agent.py
The AI agent's job is limited to two things:
  1. Understand the user's natural-language intent (which analysis/metrics are needed).
  2. Turn Python-calculated evidence into a written, evidence-grounded review using LLM providers (Groq, Google Gemini, OpenRouter, OpenAI).
It NEVER performs financial math itself.
"""

import os
import re
import json
import urllib.request
import urllib.error
from dotenv import load_dotenv

load_dotenv()

# Standard User-Agent to avoid Cloudflare/WAF block (HTTP 403 / code 1010)
HTTP_HEADERS_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

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


def _clean_think_tags(text: str) -> str:
    """Remove any <think>...</think> reasoning traces emitted by reasoning models."""
    if not text:
        return ""
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
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
        with urllib.request.urlopen(req, timeout=8) as res:
            data = json.loads(res.read().decode("utf-8"))
            model_ids = [m["id"] for m in data.get("data", [])]
            # Exclude audio and moderation/guard models
            chat_models = [
                m for m in model_ids
                if not any(x in m for x in ["whisper", "guard", "safeguard", "orpheus"])
            ]
            return chat_models
    except Exception as e:
        print(f"[agent] Note: Dynamic Groq models discovery skipped: {e}")
        return []


def generate_financial_review(evidence: dict) -> str:
    """
    Send structured, Python-calculated evidence to LLM API (Groq, Gemini, OpenRouter, OpenAI)
    and ask it to explain only what's supplied.
    """
    user_prompt = (
        "Here is the evidence calculated by Python for this financial review. "
        "Only discuss the metrics provided below. Do not reference any other financial metric:\n\n"
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
        
        # Priority list of modern, active Groq chat models
        preferred_models = [
            "openai/gpt-oss-120b",
            "openai/gpt-oss-20b",
            "groq/compound-mini",
            "groq/compound",
            "qwen/qwen3.6-27b",
            "qwen/qwen3.8-27b",
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "llama-3.1-70b-versatile",
            "allam-2-7b",
        ]

        candidate_models = []
        if configured_model:
            candidate_models.append(configured_model)
        
        # Add dynamic models that are in preferred list first
        for m in preferred_models:
            if m in dynamic_models and m not in candidate_models:
                candidate_models.append(m)
        
        # Add remaining dynamic models
        for m in dynamic_models:
            if m not in candidate_models:
                candidate_models.append(m)
                
        # Add preferred models as fallback
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
                    "max_tokens": 1200
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
                with urllib.request.urlopen(req, timeout=20) as res:
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
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1200}
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
                with urllib.request.urlopen(req, timeout=20) as res:
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
                    "max_tokens": 1200
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
                with urllib.request.urlopen(req, timeout=20) as res:
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
                    "max_tokens": 1200
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
                with urllib.request.urlopen(req, timeout=20) as res:
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
