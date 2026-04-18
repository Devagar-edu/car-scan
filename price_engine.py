"""
price_engine.py - Computes per-model price benchmarks (avg, min, max, std)
from the full historical dataset.
"""

import logging
import pandas as pd
from typing import Dict

logger = logging.getLogger(__name__)


def compute_market_benchmarks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute per-model price statistics.

    Returns a DataFrame indexed by model with columns:
      avg_price, min_price, max_price, std_price, listing_count
    """
    if df.empty:
        logger.warning("Empty DataFrame passed to compute_market_benchmarks.")
        return pd.DataFrame()

    required = {"model", "price"}
    if not required.issubset(df.columns):
        logger.error(f"Missing columns: {required - set(df.columns)}")
        return pd.DataFrame()

    benchmarks = (
        df.groupby("model")["price"]
        .agg(
            avg_price="mean",
            min_price="min",
            max_price="max",
            std_price="std",
            listing_count="count"
        )
        .reset_index()
    )
    benchmarks["avg_price"] = benchmarks["avg_price"].round(2)
    benchmarks["min_price"] = benchmarks["min_price"].round(2)
    benchmarks["max_price"] = benchmarks["max_price"].round(2)
    benchmarks["std_price"] = benchmarks["std_price"].fillna(0).round(2)

    logger.info(f"Computed benchmarks for {len(benchmarks)} models.")
    return benchmarks


def get_model_benchmark(benchmarks: pd.DataFrame, model: str) -> Dict:
    """Look up benchmark data for a specific model. Returns defaults if not found."""
    default = {
        "model": model,
        "avg_price": None,
        "min_price": None,
        "max_price": None,
        "std_price": None,
        "listing_count": 0
    }
    if benchmarks.empty:
        return default
    row = benchmarks[benchmarks["model"].str.lower() == model.lower()]
    if row.empty:
        return default
    return row.iloc[0].to_dict()


def enrich_with_benchmarks(df: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """
    Join benchmark columns (avg_price, min_price, max_price) onto the listings DataFrame.
    """
    if df.empty or benchmarks.empty:
        return df

    benchmark_cols = benchmarks[["model", "avg_price", "min_price", "max_price"]]
    merged = df.merge(benchmark_cols, on="model", how="left", suffixes=("", "_market"))
    return merged
