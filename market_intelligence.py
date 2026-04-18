"""
market_intelligence.py - Classifies each car as UNDERPRICED / FAIR / OVERPRICED
relative to market average, and attaches trend information.
"""

import logging
import pandas as pd

logger = logging.getLogger(__name__)

UNDERPRICED_THRESHOLD = 0.85   # < 85% of avg → UNDERPRICED
OVERPRICED_THRESHOLD = 1.15    # > 115% of avg → OVERPRICED


def classify_market_status(price: float, avg_price: float) -> str:
    """Classify a single car's price relative to market average."""
    if not avg_price or avg_price == 0:
        return "UNKNOWN"
    ratio = price / avg_price
    if ratio < UNDERPRICED_THRESHOLD:
        return "UNDERPRICED"
    elif ratio > OVERPRICED_THRESHOLD:
        return "OVERPRICED"
    else:
        return "FAIR"


def compute_price_ratio(price: float, avg_price: float) -> float:
    """Return price as percentage of market average (e.g. 92.5 means 7.5% below avg)."""
    if not avg_price or avg_price == 0:
        return 100.0
    return round((price / avg_price) * 100, 1)


def enrich_with_market_intelligence(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds 'market_status' and 'price_vs_market_pct' columns to df.
    Requires 'price' and 'avg_price' columns already present.
    """
    if df.empty:
        return df

    if "avg_price" not in df.columns:
        df["market_status"] = "UNKNOWN"
        df["price_vs_market_pct"] = 100.0
        return df

    df["market_status"] = df.apply(
        lambda r: classify_market_status(r["price"], r.get("avg_price")),
        axis=1
    )
    df["price_vs_market_pct"] = df.apply(
        lambda r: compute_price_ratio(r["price"], r.get("avg_price")),
        axis=1
    )

    logger.info(
        f"Market intelligence: "
        f"{(df['market_status'] == 'UNDERPRICED').sum()} underpriced, "
        f"{(df['market_status'] == 'FAIR').sum()} fair, "
        f"{(df['market_status'] == 'OVERPRICED').sum()} overpriced"
    )
    return df


def get_top_recommendations(df: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """
    Return the top N BUY recommendations, sorted by:
    1. market_status == UNDERPRICED
    2. trend == PRICE INCREASING (act soon)
    3. lowest price_vs_market_pct
    """
    if df.empty or "ai_decision" not in df.columns:
        return df.head(n)

    buys = df[df["ai_decision"] == "BUY"].copy()
    if buys.empty:
        # Fall back to underpriced
        buys = df[df["market_status"] == "UNDERPRICED"].copy()

    if buys.empty:
        return df.head(n)

    # Prioritise increasing trend (act soon) then lowest relative price
    buys["_sort_trend"] = buys["trend"].apply(
        lambda t: 0 if t == "PRICE INCREASING" else (1 if t == "STABLE" else 2)
    )
    buys.sort_values(["_sort_trend", "price_vs_market_pct"], ascending=[True, True], inplace=True)
    return buys.drop(columns=["_sort_trend"]).head(n)
