"""
trend_engine.py - Detects price trends per model by comparing
recent listings (last 2-3 days) vs older historical data.
"""

import logging
import pandas as pd
from typing import Dict

logger = logging.getLogger(__name__)

RECENT_DAYS = 3
OLDER_DAYS = 14
TREND_THRESHOLD = 0.03   # 3% change = meaningful trend


def compute_trends(full_history: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-model price trend.

    Returns DataFrame with columns:
      model, recent_avg, older_avg, pct_change, trend
    where trend ∈ {PRICE INCREASING, PRICE DROPPING, STABLE, INSUFFICIENT DATA}
    """
    if full_history.empty:
        return pd.DataFrame()

    now = pd.Timestamp.now()
    recent_cutoff = now - pd.Timedelta(days=RECENT_DAYS)
    older_cutoff = now - pd.Timedelta(days=OLDER_DAYS)

    recent_df = full_history[full_history["scraped_at"] >= recent_cutoff]
    older_df = full_history[
        (full_history["scraped_at"] < recent_cutoff) &
        (full_history["scraped_at"] >= older_cutoff)
    ]

    if recent_df.empty:
        logger.warning("No recent data for trend computation.")
        return pd.DataFrame()

    recent_avg = recent_df.groupby("model")["price"].mean().rename("recent_avg")
    older_avg = older_df.groupby("model")["price"].mean().rename("older_avg") if not older_df.empty else pd.Series(dtype=float, name="older_avg")

    trends = pd.DataFrame(recent_avg).join(older_avg, how="left")
    trends.reset_index(inplace=True)

    def classify(row):
        if pd.isna(row.get("older_avg")) or row["older_avg"] == 0:
            return "STABLE"  # no older data — assume stable
        pct = (row["recent_avg"] - row["older_avg"]) / row["older_avg"]
        if pct > TREND_THRESHOLD:
            return "PRICE INCREASING"
        elif pct < -TREND_THRESHOLD:
            return "PRICE DROPPING"
        else:
            return "STABLE"

    def pct_change(row):
        if pd.isna(row.get("older_avg")) or row["older_avg"] == 0:
            return 0.0
        return round((row["recent_avg"] - row["older_avg"]) / row["older_avg"] * 100, 2)

    trends["pct_change"] = trends.apply(pct_change, axis=1)
    trends["trend"] = trends.apply(classify, axis=1)
    trends["recent_avg"] = trends["recent_avg"].round(2)
    trends["older_avg"] = trends["older_avg"].fillna(trends["recent_avg"]).round(2)

    logger.info(f"Computed trends for {len(trends)} models.")
    return trends


def enrich_with_trends(df: pd.DataFrame, trends: pd.DataFrame) -> pd.DataFrame:
    """Join trend columns onto listings DataFrame."""
    if df.empty or trends.empty:
        if "trend" not in df.columns:
            df["trend"] = "STABLE"
        return df

    trend_cols = trends[["model", "trend", "pct_change"]]
    merged = df.merge(trend_cols, on="model", how="left")
    merged["trend"].fillna("STABLE", inplace=True)
    merged["pct_change"].fillna(0.0, inplace=True)
    return merged


def get_trend_for_model(trends: pd.DataFrame, model: str) -> str:
    """Get trend string for a specific model."""
    if trends.empty:
        return "STABLE"
    row = trends[trends["model"].str.lower() == model.lower()]
    return row["trend"].iloc[0] if not row.empty else "STABLE"
