"""
ai_engine.py - AI Decision Engine using Anthropic Claude API.
Processes cars in batches of 10-20, returns BUY/WAIT/SKIP decisions.
"""

import json
import logging
import re
from typing import List, Dict, Any, Optional
import pandas as pd

logger = logging.getLogger(__name__)

BATCH_SIZE = 15
MAX_RETRIES = 3

# ─────────────────────────────────────────────────────────────────────────────
# Prompt Construction
# ─────────────────────────────────────────────────────────────────────────────

def _build_batch_prompt(batch: List[Dict]) -> str:
    cars_block = json.dumps(batch, indent=2)
    return f"""You are an expert used car market analyst in Chennai, India.

Analyze the following {len(batch)} used car listings and return a decision for each.

MARKET CONTEXT:
- Market is in Chennai, India
- Prices are in Indian Lakhs (1 Lakh = 100,000 INR)
- Typical used car price range: 2–25 Lakhs
- Average KM for used cars: 20,000–80,000 KM

DECISION RULES:
- BUY: Underpriced or fair-priced, low KM, recent year, price dropping or stable trend
- WAIT: Fair-priced but price is dropping (better deal soon), or market is uncertain
- SKIP: Overpriced, high KM, old model, or price is actively increasing beyond fair value

For each car, consider:
1. price vs market average (market_status)
2. km driven (lower is better)
3. year (newer is better)
4. market trend (PRICE INCREASING means act soon or skip, PRICE DROPPING means wait)
5. price_vs_market_pct (< 90 is great value, > 115 is overpriced)

CAR LISTINGS:
{cars_block}

Return ONLY a valid JSON array (no markdown, no explanation) with exactly {len(batch)} objects:
[
  {{
    "index": 0,
    "decision": "BUY | WAIT | SKIP",
    "confidence": "HIGH | MEDIUM | LOW",
    "reason": "One concise sentence explaining the decision based on price, km, year and trend"
  }}
]"""


def _parse_ai_response(content: str, expected_count: int) -> List[Dict]:
    """Parse AI JSON response with fallback handling."""
    try:
        # Strip potential markdown fences
        clean = re.sub(r"```(?:json)?", "", content).strip()
        parsed = json.loads(clean)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        # Try to extract JSON array from mixed content
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except Exception:
                pass

    logger.warning("AI response parsing failed. Using fallback decisions.")
    return [
        {"index": i, "decision": "WAIT", "confidence": "LOW", "reason": "AI analysis unavailable"}
        for i in range(expected_count)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Anthropic-Based AI Engine
# ─────────────────────────────────────────────────────────────────────────────

def _call_claude_api(prompt: str, api_key: str) -> str:
    """Call Anthropic Claude API synchronously."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


def _call_openai_api(prompt: str, api_key: str) -> str:
    """Call OpenAI API as alternative."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2048,
        response_format={"type": "json_object"}
    )
    return response.choices[0].message.content


def _call_ai(prompt: str, api_key: str, provider: str = "anthropic") -> str:
    """Unified AI call with provider selection."""
    if provider == "openai":
        return _call_openai_api(prompt, api_key)
    return _call_claude_api(prompt, api_key)


def get_ai_decisions(
    df: pd.DataFrame,
    api_key: str,
    provider: str = "anthropic"
) -> pd.DataFrame:
    """
    Process all listings in batches, attach AI decisions.
    Returns df with added columns: ai_decision, confidence, ai_reason
    """
    if df.empty:
        return df

    required_cols = ["price", "km", "year", "market_status", "trend"]
    for col in required_cols:
        if col not in df.columns:
            df[col] = "Unknown"

    results_map: Dict[int, Dict] = {}

    # Process in batches
    indices = list(df.index)
    batches = [indices[i:i + BATCH_SIZE] for i in range(0, len(indices), BATCH_SIZE)]

    for batch_num, batch_indices in enumerate(batches):
        batch_cars = []
        for pos, idx in enumerate(batch_indices):
            row = df.loc[idx]
            batch_cars.append({
                "index": pos,
                "title": str(row.get("title", "Unknown")),
                "price": round(float(row.get("price", 0)), 2),
                "km": int(row.get("km", 0)),
                "year": int(row.get("year", 2000)),
                "market_status": str(row.get("market_status", "UNKNOWN")),
                "trend": str(row.get("trend", "STABLE")),
                "price_vs_market_pct": round(float(row.get("price_vs_market_pct", 100)), 1),
                "fuel_type": str(row.get("fuel_type", "Unknown")),
            })

        prompt = _build_batch_prompt(batch_cars)

        for attempt in range(MAX_RETRIES):
            try:
                response_text = _call_ai(prompt, api_key, provider)
                batch_results = _parse_ai_response(response_text, len(batch_cars))

                for res in batch_results:
                    pos = res.get("index", 0)
                    if 0 <= pos < len(batch_indices):
                        actual_idx = batch_indices[pos]
                        results_map[actual_idx] = res
                break

            except Exception as e:
                logger.error(f"AI batch {batch_num+1} attempt {attempt+1} failed: {e}")
                if attempt == MAX_RETRIES - 1:
                    # Fill with fallbacks
                    for pos, idx in enumerate(batch_indices):
                        results_map[idx] = {
                            "decision": "WAIT",
                            "confidence": "LOW",
                            "reason": f"AI analysis failed: {str(e)[:80]}"
                        }

        logger.info(f"Processed AI batch {batch_num+1}/{len(batches)}")

    # Map results back to DataFrame
    df["ai_decision"] = df.index.map(lambda i: results_map.get(i, {}).get("decision", "WAIT"))
    df["confidence"] = df.index.map(lambda i: results_map.get(i, {}).get("confidence", "LOW"))
    df["ai_reason"] = df.index.map(lambda i: results_map.get(i, {}).get("reason", "No analysis available"))

    logger.info(
        f"AI decisions: "
        f"BUY={( df['ai_decision'] == 'BUY').sum()}, "
        f"WAIT={(df['ai_decision'] == 'WAIT').sum()}, "
        f"SKIP={(df['ai_decision'] == 'SKIP').sum()}"
    )
    return df


def get_rule_based_decisions(df: pd.DataFrame) -> pd.DataFrame:
    """
    Fallback rule-based decisions when AI API is unavailable.
    Provides deterministic BUY/WAIT/SKIP based on market intelligence.
    """
    if df.empty:
        return df

    def rule_decision(row):
        status = row.get("market_status", "UNKNOWN")
        trend = row.get("trend", "STABLE")
        km = row.get("km", 50000)
        year = row.get("year", 2018)
        pct = row.get("price_vs_market_pct", 100)

        # SKIP conditions
        if status == "OVERPRICED" and trend == "PRICE INCREASING":
            return "SKIP", "HIGH", "Overpriced and prices rising — poor value"
        if km > 120000:
            return "SKIP", "MEDIUM", "High mileage car — reliability concerns"
        if year < 2013:
            return "SKIP", "MEDIUM", "Older vehicle — higher maintenance risk"

        # BUY conditions
        if status == "UNDERPRICED" and trend in ("STABLE", "PRICE INCREASING"):
            return "BUY", "HIGH", "Below market value with stable/rising trend — act now"
        if status == "FAIR" and km < 40000 and year >= 2019:
            return "BUY", "MEDIUM", "Fair price, low km, recent model — good buy"

        # WAIT conditions
        if trend == "PRICE DROPPING":
            return "WAIT", "MEDIUM", "Prices are dropping — better deal may be available soon"
        if status == "OVERPRICED":
            return "WAIT", "HIGH", "Currently overpriced — wait for price correction"

        return "WAIT", "LOW", "Market is uncertain — monitor before buying"

    decisions = df.apply(lambda r: rule_decision(r), axis=1, result_type="expand")
    df["ai_decision"] = decisions[0]
    df["confidence"] = decisions[1]
    df["ai_reason"] = decisions[2]
    return df
