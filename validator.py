"""
validator.py - Data validation and cleaning for scraped car listings.
Ensures price, km, and year are numeric; drops invalid records; fills missing values.
"""

import logging
import re
from typing import List, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)

# Known Chennai-relevant car models for model extraction
MODEL_KEYWORDS = [
    "Swift", "Baleno", "i20", "i10", "Creta", "Venue", "Verna", "City",
    "Jazz", "Amaze", "WR-V", "Nexon", "Altroz", "Harrier", "Safari",
    "Punch", "Tiago", "Tigor", "Dzire", "Ertiga", "Brezza", "Grand i10",
    "Innova", "Fortuner", "Corolla", "Camry", "Yaris", "Glanza", "Urban Cruiser",
    "Duster", "Kwid", "Triber", "Kiger", "Magnite", "S-Cross", "Ciaz",
    "Polo", "Vento", "Taigun", "Virtus", "Seltos", "Sonet", "Carnival",
    "EcoSport", "Freestyle", "Figo", "Aspire", "Endeavour",
    "XUV700", "XUV300", "Thar", "Scorpio", "Bolero", "Marazzo",
    "Compass", "Meridian", "Meridian", "Xuv", "Omni",
    "Alto", "WagonR", "Celerio", "S-Presso", "Ignis", "Eeco",
]


def extract_model(title: str) -> str:
    """Extract car model name from listing title."""
    if not title:
        return "Unknown"
    title_lower = title.lower()
    for model in sorted(MODEL_KEYWORDS, key=len, reverse=True):
        if model.lower() in title_lower:
            return model
    # Fallback: take second word of title (often model name)
    parts = title.strip().split()
    if len(parts) >= 2:
        return parts[1]
    return parts[0] if parts else "Unknown"


def clean_listings(raw: List[Dict]) -> pd.DataFrame:
    """
    Validate and clean a list of raw listing dicts.
    Returns a clean DataFrame with all required columns.
    """
    if not raw:
        logger.warning("No raw listings to clean.")
        return pd.DataFrame()

    df = pd.DataFrame(raw)

    # ── Ensure required columns exist ──────────────────────────────────────
    required = ["title", "price", "km", "year", "fuel_type", "link", "source", "scraped_at"]
    for col in required:
        if col not in df.columns:
            df[col] = None

    # ── Coerce numeric types ───────────────────────────────────────────────
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df["km"] = pd.to_numeric(df["km"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce")

    # ── Drop rows with critical missing values ────────────────────────────
    before = len(df)
    df.dropna(subset=["price", "year"], inplace=True)
    df = df[df["price"] > 0]
    df = df[df["year"] >= 2000]
    after = len(df)
    logger.info(f"Validation: {before - after} rows dropped, {after} rows kept.")

    # ── Fill missing km intelligently ─────────────────────────────────────
    if df["km"].isna().any():
        median_km = df["km"].median()
        df["km"].fillna(median_km if pd.notna(median_km) else 50000, inplace=True)

    # ── Fill missing fuel type ────────────────────────────────────────────
    df["fuel_type"].fillna("Unknown", inplace=True)
    df["fuel_type"] = df["fuel_type"].astype(str).str.strip()
    df.loc[df["fuel_type"].isin(["", "nan", "None"]), "fuel_type"] = "Unknown"

    # ── Normalise title ────────────────────────────────────────────────────
    df["title"] = df["title"].astype(str).str.strip()

    # ── Cast year to int ──────────────────────────────────────────────────
    df["year"] = df["year"].astype(int)

    # ── Round km ──────────────────────────────────────────────────────────
    df["km"] = df["km"].round(0).astype(int)

    # ── Extract model ─────────────────────────────────────────────────────
    df["model"] = df["title"].apply(extract_model)

    # ── Normalise scraped_at to datetime ──────────────────────────────────
    df["scraped_at"] = pd.to_datetime(df["scraped_at"], errors="coerce")
    df["scraped_at"].fillna(pd.Timestamp.now(), inplace=True)

    # ── Remove exact duplicates by title + price + source ─────────────────
    df.drop_duplicates(subset=["title", "price", "source"], keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)

    logger.info(f"Final clean dataset: {len(df)} rows")
    return df


def apply_filters(
    df: pd.DataFrame,
    min_year: Optional[int] = None,
    max_year: Optional[int] = None,
    max_km: Optional[float] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    fuel_type: Optional[str] = None
) -> pd.DataFrame:
    """Apply user-defined filters to the clean DataFrame."""
    if df.empty:
        return df

    fdf = df.copy()

    try:
        if min_year:
            fdf = fdf[fdf["year"] >= min_year]
        if max_year:
            fdf = fdf[fdf["year"] <= max_year]
        if max_km:
            fdf = fdf[fdf["km"] <= max_km]
        if min_price:
            fdf = fdf[fdf["price"] >= min_price]
        if max_price:
            fdf = fdf[fdf["price"] <= max_price]
        if fuel_type and fuel_type.lower() not in ("all", "any", ""):
            fdf = fdf[fdf["fuel_type"].str.lower() == fuel_type.lower()]
    except Exception as e:
        logger.error(f"Filter error: {e}")

    logger.info(f"Filtered dataset: {len(fdf)} rows")
    return fdf.reset_index(drop=True)
