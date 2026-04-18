"""
scoring.py - Composite scoring for car listings.
Generates a 0-100 score combining price value, mileage, age, and AI decision.
"""

import pandas as pd
import logging

logger = logging.getLogger(__name__)

# Weights must sum to 1.0
WEIGHT_PRICE_VALUE = 0.35
WEIGHT_KM = 0.25
WEIGHT_YEAR = 0.20
WEIGHT_AI_DECISION = 0.20


def _score_price_value(price_vs_market_pct: float) -> float:
    """Score price relative to market. Lower % = better score."""
    if price_vs_market_pct <= 75:
        return 100.0
    elif price_vs_market_pct <= 90:
        return 85.0
    elif price_vs_market_pct <= 100:
        return 70.0
    elif price_vs_market_pct <= 115:
        return 50.0
    else:
        return max(0.0, 50.0 - (price_vs_market_pct - 115) * 2)


def _score_km(km: float) -> float:
    """Score based on km driven. Lower km = higher score."""
    if km <= 20000:
        return 100.0
    elif km <= 40000:
        return 85.0
    elif km <= 60000:
        return 70.0
    elif km <= 80000:
        return 55.0
    elif km <= 100000:
        return 35.0
    else:
        return max(0.0, 35.0 - (km - 100000) / 5000)


def _score_year(year: int) -> float:
    """Score based on manufacturing year. Newer = higher score."""
    import datetime
    current_year = datetime.datetime.now().year
    age = current_year - year
    if age <= 1:
        return 100.0
    elif age <= 3:
        return 85.0
    elif age <= 5:
        return 70.0
    elif age <= 8:
        return 55.0
    elif age <= 12:
        return 35.0
    else:
        return max(0.0, 35.0 - (age - 12) * 3)


def _score_ai_decision(decision: str, confidence: str) -> float:
    """Convert AI decision + confidence to a numeric score."""
    base = {"BUY": 100.0, "WAIT": 50.0, "SKIP": 10.0}.get(decision, 50.0)
    multiplier = {"HIGH": 1.0, "MEDIUM": 0.85, "LOW": 0.70}.get(confidence, 0.85)
    return base * multiplier


def compute_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add a 'composite_score' (0-100) to each listing.
    Higher score = better buy opportunity.
    """
    if df.empty:
        return df

    def row_score(row):
        pv = _score_price_value(row.get("price_vs_market_pct", 100))
        km = _score_km(row.get("km", 60000))
        yr = _score_year(row.get("year", 2018))
        ai = _score_ai_decision(
            row.get("ai_decision", "WAIT"),
            row.get("confidence", "LOW")
        )
        composite = (
            pv * WEIGHT_PRICE_VALUE
            + km * WEIGHT_KM
            + yr * WEIGHT_YEAR
            + ai * WEIGHT_AI_DECISION
        )
        return round(composite, 1)

    df["composite_score"] = df.apply(row_score, axis=1)
    logger.info(
        f"Scoring complete. Top score: {df['composite_score'].max()}, "
        f"Avg score: {df['composite_score'].mean():.1f}"
    )
    return df


def get_score_band(score: float) -> str:
    """Human-readable band for composite score."""
    if score >= 75:
        return "🟢 EXCELLENT"
    elif score >= 60:
        return "🟡 GOOD"
    elif score >= 45:
        return "🟠 AVERAGE"
    else:
        return "🔴 POOR"
