"""
market_store.py - Persistent storage for car listing data using CSV.
Maintains historical data across runs, avoids duplicates.
"""

import os
import logging
from pathlib import Path
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

DATA_DIR = Path("data")
LISTINGS_FILE = DATA_DIR / "listings_history.csv"

COLUMNS = [
    "title", "price", "km", "year", "fuel_type",
    "link", "source", "scraped_at", "model"
]


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_history() -> pd.DataFrame:
    """Load all historical listings from disk."""
    _ensure_data_dir()
    if not LISTINGS_FILE.exists():
        logger.info("No history file found. Starting fresh.")
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(LISTINGS_FILE, parse_dates=["scraped_at"])
        logger.info(f"Loaded {len(df)} historical records.")
        return df
    except Exception as e:
        logger.error(f"Failed to load history: {e}")
        return pd.DataFrame(columns=COLUMNS)


def append_new_listings(new_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge new listings into historical store.
    Deduplicates on title + price + source.
    Returns the full combined dataset.
    """
    _ensure_data_dir()
    if new_df.empty:
        logger.warning("No new listings to append.")
        return load_history()

    history = load_history()

    # Ensure all required columns
    for col in COLUMNS:
        if col not in new_df.columns:
            new_df[col] = None

    combined = pd.concat([history, new_df[COLUMNS]], ignore_index=True)
    combined.drop_duplicates(subset=["title", "price", "source"], keep="last", inplace=True)
    combined["scraped_at"] = pd.to_datetime(combined["scraped_at"], errors="coerce")
    combined.sort_values("scraped_at", ascending=False, inplace=True)
    combined.reset_index(drop=True, inplace=True)

    try:
        combined.to_csv(LISTINGS_FILE, index=False)
        logger.info(f"Saved {len(combined)} total records to {LISTINGS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save history: {e}")

    return combined


def get_recent_listings(days: int = 7) -> pd.DataFrame:
    """Return listings scraped within the last N days."""
    df = load_history()
    if df.empty:
        return df
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days)
    return df[df["scraped_at"] >= cutoff].reset_index(drop=True)


def get_listings_by_date_range(start: datetime, end: datetime) -> pd.DataFrame:
    """Return listings scraped between two datetimes."""
    df = load_history()
    if df.empty:
        return df
    mask = (df["scraped_at"] >= pd.Timestamp(start)) & (df["scraped_at"] <= pd.Timestamp(end))
    return df[mask].reset_index(drop=True)
