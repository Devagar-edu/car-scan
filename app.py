"""
app.py - Main Streamlit dashboard for Chennai Used Car AI Analyzer.
Orchestrates scraping, enrichment, AI decisions, and display.
"""

import asyncio
import io
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except AttributeError:
        pass

# ── Project imports ────────────────────────────────────────────────────────
from scraper import scrape_all
from validator import clean_listings, apply_filters
from market_store import append_new_listings, load_history
from price_engine import compute_market_benchmarks, enrich_with_benchmarks
from trend_engine import compute_trends, enrich_with_trends
from market_intelligence import enrich_with_market_intelligence, get_top_recommendations
from ai_engine import get_ai_decisions, get_rule_based_decisions
from scoring import compute_scores, get_score_band
from cache import cache_get, cache_set, cache_clear_all, cache_info

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("app")

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Chennai Used Car AI Analyzer",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Space Grotesk', sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #0a0e1a 0%, #0f1628 50%, #0a1020 100%);
        color: #e2e8f0;
    }
    .main-header {
        background: linear-gradient(135deg, #1a2744 0%, #243460 100%);
        border: 1px solid #2d4080;
        border-radius: 16px;
        padding: 24px 32px;
        margin-bottom: 24px;
        text-align: center;
    }
    .main-header h1 {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(135deg, #60a5fa, #a78bfa, #34d399);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }
    .main-header p {
        color: #94a3b8;
        margin: 8px 0 0;
        font-size: 0.95rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #1e2d4f 0%, #1a2540 100%);
        border: 1px solid #2d4080;
        border-radius: 12px;
        padding: 20px;
        text-align: center;
    }
    .decision-BUY {
        background: linear-gradient(135deg, #064e2e, #065f46);
        border: 1px solid #10b981;
        color: #34d399;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .decision-WAIT {
        background: linear-gradient(135deg, #78350f, #92400e);
        border: 1px solid #f59e0b;
        color: #fbbf24;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .decision-SKIP {
        background: linear-gradient(135deg, #7f1d1d, #991b1b);
        border: 1px solid #ef4444;
        color: #fca5a5;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: 600;
        font-size: 0.85rem;
    }
    .rec-card {
        background: linear-gradient(135deg, #0f2410, #0a1e0d);
        border: 1px solid #10b981;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .rec-card h4 {
        color: #34d399;
        margin: 0 0 8px;
        font-size: 0.95rem;
    }
    .rec-card .price {
        font-size: 1.3rem;
        font-weight: 700;
        color: #60a5fa;
    }
    .rec-card .meta {
        color: #94a3b8;
        font-size: 0.82rem;
        margin-top: 4px;
    }
    .status-UNDERPRICED { color: #34d399; font-weight: 600; }
    .status-FAIR { color: #60a5fa; font-weight: 600; }
    .status-OVERPRICED { color: #f87171; font-weight: 600; }
    .trend-INCREASING { color: #f59e0b; }
    .trend-DROPPING { color: #34d399; }
    .trend-STABLE { color: #94a3b8; }
    div[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1628 0%, #0a1020 100%);
        border-right: 1px solid #1e2d4f;
    }
    .stButton > button {
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        color: white;
        border: none;
        border-radius: 10px;
        font-weight: 600;
        font-size: 1rem;
        padding: 12px 24px;
        width: 100%;
        transition: opacity 0.2s;
    }
    .stButton > button:hover { opacity: 0.85; }
    .dataframe { font-size: 0.82rem; }
</style>
""", unsafe_allow_html=True)


# ── Helper functions ───────────────────────────────────────────────────────

def run_async(coro):
    """Run an async coroutine from a sync context."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result()
        else:
            return asyncio.run(coro)
    except RuntimeError:
        return asyncio.run(coro)


def decision_badge(decision: str) -> str:
    icons = {"BUY": "✅", "WAIT": "⏳", "SKIP": "❌"}
    return f"{icons.get(decision, '?')} {decision}"


def trend_icon(trend: str) -> str:
    icons = {
        "PRICE INCREASING": "📈 Rising",
        "PRICE DROPPING": "📉 Dropping",
        "STABLE": "➡️ Stable"
    }
    return icons.get(trend, trend)


def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convert DataFrame to Excel bytes for download."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Car Listings")
    return output.getvalue()


def pipeline(
    api_key: str,
    ai_provider: str,
    min_year: int,
    max_year: int,
    max_km: float,
    min_price: float,
    max_price: float,
    fuel_type: str,
    force_refresh: bool = False
) -> pd.DataFrame:
    """
    Full data pipeline:
    1. Check cache
    2. Scrape (if needed)
    3. Clean & validate
    4. Store to history
    5. Compute benchmarks & trends
    6. Market intelligence
    7. AI decisions
    8. Scoring
    9. Filter
    """

    CACHE_KEY = "scraped_listings"
    progress = st.progress(0, text="Initialising pipeline...")

    # ── Step 1: Scrape or load from cache ─────────────────────────────────
    if not force_refresh:
        cached = cache_get(CACHE_KEY)
        if cached is not None:
            st.info("⚡ Using cached data (within 45-minute window). Force refresh to re-scrape.")
            raw_listings = cached
        else:
            raw_listings = None
    else:
        raw_listings = None
        cache_clear_all()

    if raw_listings is None:
        progress.progress(10, text="🌐 Scraping CarWale & Spinny...")
        try:
            raw_listings = run_async(scrape_all(max_pages=3))
            if raw_listings:
                cache_set(CACHE_KEY, raw_listings)
            else:
                st.warning("⚠️ Scraping returned no results. Loading from historical data...")
        except Exception as e:
            logger.error(f"Scraping failed: {e}")
            st.warning(f"⚠️ Scraping error: {e}. Falling back to historical data.")
            raw_listings = []

    progress.progress(25, text="🧹 Cleaning & validating data...")

    # ── Step 2: Clean ──────────────────────────────────────────────────────
    clean_df = clean_listings(raw_listings)

    # ── Step 3: Persist ────────────────────────────────────────────────────
    if not clean_df.empty:
        full_history = append_new_listings(clean_df)
    else:
        full_history = load_history()

    if full_history.empty:
        progress.progress(100)
        st.error("❌ No data available. Please try again later.")
        return pd.DataFrame()

    progress.progress(40, text="📊 Computing market benchmarks...")

    # ── Step 4: Price benchmarks ───────────────────────────────────────────
    benchmarks = compute_market_benchmarks(full_history)
    working_df = enrich_with_benchmarks(clean_df if not clean_df.empty else full_history, benchmarks)

    progress.progress(55, text="📈 Analysing market trends...")

    # ── Step 5: Trends ─────────────────────────────────────────────────────
    trends = compute_trends(full_history)
    working_df = enrich_with_trends(working_df, trends)

    progress.progress(65, text="🧠 Running market intelligence...")

    # ── Step 6: Market intelligence ────────────────────────────────────────
    working_df = enrich_with_market_intelligence(working_df)

    progress.progress(78, text="🤖 Getting AI decisions...")

    # ── Step 7: AI decisions ───────────────────────────────────────────────
    if api_key and api_key.strip():
        try:
            working_df = get_ai_decisions(working_df, api_key.strip(), provider=ai_provider)
        except Exception as e:
            logger.error(f"AI engine failed: {e}")
            st.warning(f"⚠️ AI API failed ({e}). Using rule-based decisions instead.")
            working_df = get_rule_based_decisions(working_df)
    else:
        st.info("ℹ️ No API key provided. Using rule-based decisions.")
        working_df = get_rule_based_decisions(working_df)

    progress.progress(90, text="📐 Computing composite scores...")

    # ── Step 8: Scoring ────────────────────────────────────────────────────
    working_df = compute_scores(working_df)

    # ── Step 9: Apply user filters ─────────────────────────────────────────
    filtered_df = apply_filters(
        working_df,
        min_year=min_year,
        max_year=max_year,
        max_km=max_km,
        min_price=min_price,
        max_price=max_price,
        fuel_type=fuel_type
    )

    progress.progress(100, text="✅ Done!")
    return filtered_df


# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────────────────────────────────────

# ── Header ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🚗 Chennai Used Car AI Analyzer</h1>
    <p>Real-time market intelligence • AI-powered BUY / WAIT / SKIP decisions • Live price trends</p>
</div>
""", unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### ⚙️ Configuration")

    ai_provider = st.selectbox(
        "AI Provider",
        ["anthropic", "openai"],
        index=0,
        help="Select which AI API to use for decisions"
    )

    api_key = st.text_input(
        "API Key",
        type="password",
        placeholder="sk-... or claude key",
        help="Anthropic or OpenAI API key. Leave blank for rule-based decisions."
    )

    st.markdown("---")
    st.markdown("### 🔍 Filters")

    current_year = datetime.now().year
    col1, col2 = st.columns(2)
    with col1:
        min_year = st.number_input("Min Year", min_value=2000, max_value=current_year, value=2016)
    with col2:
        max_year = st.number_input("Max Year", min_value=2000, max_value=current_year, value=current_year)

    max_km = st.slider(
        "Max KM Driven",
        min_value=0,
        max_value=200000,
        value=100000,
        step=5000,
        format="%d KM"
    )

    col3, col4 = st.columns(2)
    with col3:
        min_price = st.number_input("Min Price (₹ Lakh)", min_value=0.0, max_value=100.0, value=2.0, step=0.5)
    with col4:
        max_price = st.number_input("Max Price (₹ Lakh)", min_value=0.0, max_value=100.0, value=20.0, step=0.5)

    fuel_type = st.selectbox(
        "Fuel Type",
        ["All", "Petrol", "Diesel", "CNG", "Electric"],
        index=0
    )

    st.markdown("---")
    force_refresh = st.checkbox("🔄 Force Refresh (re-scrape)", value=False)

    fetch_btn = st.button("🚀 Fetch & Analyse Cars", use_container_width=True)

    st.markdown("---")
    # Cache info
    info = cache_info()
    st.caption(f"📦 Cache: {info['count']} entries")


# ── Main content ────────────────────────────────────────────────────────────

if fetch_btn:
    fuel_filter = "" if fuel_type == "All" else fuel_type

    with st.spinner("Running full pipeline..."):
        result_df = pipeline(
            api_key=api_key,
            ai_provider=ai_provider,
            min_year=min_year,
            max_year=max_year,
            max_km=float(max_km),
            min_price=min_price,
            max_price=max_price,
            fuel_type=fuel_filter,
            force_refresh=force_refresh
        )

    st.session_state["result_df"] = result_df
    st.session_state["last_run"] = datetime.now().strftime("%d %b %Y %H:%M:%S")

# ── Results ─────────────────────────────────────────────────────────────────
if "result_df" in st.session_state and not st.session_state["result_df"].empty:
    df = st.session_state["result_df"]
    last_run = st.session_state.get("last_run", "—")

    # ── Summary metrics ────────────────────────────────────────────────────
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        st.metric("📋 Total Listings", len(df))
    with col2:
        buys = (df["ai_decision"] == "BUY").sum() if "ai_decision" in df.columns else 0
        st.metric("✅ BUY Signals", buys)
    with col3:
        waits = (df["ai_decision"] == "WAIT").sum() if "ai_decision" in df.columns else 0
        st.metric("⏳ WAIT Signals", waits)
    with col4:
        skips = (df["ai_decision"] == "SKIP").sum() if "ai_decision" in df.columns else 0
        st.metric("❌ SKIP Signals", skips)
    with col5:
        avg_score = df["composite_score"].mean() if "composite_score" in df.columns else 0
        st.metric("📊 Avg Score", f"{avg_score:.1f}/100")

    st.caption(f"Last updated: {last_run}")
    st.markdown("---")

    # ── Top Recommendations ────────────────────────────────────────────────
    st.markdown("### 🏆 Top Recommendations")
    top_recs = get_top_recommendations(df, n=6)

    if not top_recs.empty:
        cols = st.columns(min(3, len(top_recs)))
        for i, (_, row) in enumerate(top_recs.iterrows()):
            col_idx = i % 3
            with cols[col_idx]:
                score = row.get("composite_score", 0)
                score_band = get_score_band(score)
                trend_str = trend_icon(row.get("trend", "STABLE"))
                status = row.get("market_status", "UNKNOWN")
                link = row.get("link", "#")
                title = str(row.get("title", "Unknown"))[:55]
                price = row.get("price", 0)
                km = int(row.get("km", 0))
                year = int(row.get("year", 0))
                reason = row.get("ai_reason", "—")[:100]

                st.markdown(f"""
                <div class="rec-card">
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
                        <span class="decision-BUY">✅ BUY</span>
                        <span style="color:#64748b;font-size:0.8rem">{score_band}</span>
                    </div>
                    <h4>{title}</h4>
                    <div class="price">₹{price:.2f}L</div>
                    <div class="meta">
                        📅 {year} &nbsp;|&nbsp; 🛣️ {km:,} km &nbsp;|&nbsp; {trend_str}
                    </div>
                    <div class="meta" style="margin-top:6px;color:#a78bfa">
                        {reason}
                    </div>
                    <a href="{link}" target="_blank" style="color:#60a5fa;font-size:0.8rem;text-decoration:none">
                        🔗 View Listing →
                    </a>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("No BUY recommendations found with current filters.")

    st.markdown("---")

    # ── Full Data Table ─────────────────────────────────────────────────────
    st.markdown("### 📊 All Listings")

    # Prepare display columns
    display_cols = [
        "title", "price", "km", "year", "fuel_type", "model",
        "market_status", "trend", "ai_decision", "confidence",
        "composite_score", "ai_reason", "source", "link"
    ]
    display_cols = [c for c in display_cols if c in df.columns]
    display_df = df[display_cols].copy()

    # Rename for display
    rename_map = {
        "title": "Car",
        "price": "Price (₹L)",
        "km": "KM Driven",
        "year": "Year",
        "fuel_type": "Fuel",
        "model": "Model",
        "market_status": "Market Status",
        "trend": "Trend",
        "ai_decision": "AI Decision",
        "confidence": "Confidence",
        "composite_score": "Score",
        "ai_reason": "Reason",
        "source": "Source",
        "link": "Link"
    }
    display_df.rename(columns=rename_map, inplace=True)

    # Filter by decision
    decision_filter = st.multiselect(
        "Filter by AI Decision",
        ["BUY", "WAIT", "SKIP"],
        default=["BUY", "WAIT", "SKIP"]
    )
    if decision_filter and "AI Decision" in display_df.columns:
        display_df = display_df[display_df["AI Decision"].isin(decision_filter)]

    # Sort
    sort_col = st.selectbox(
        "Sort by",
        ["Score", "Price (₹L)", "KM Driven", "Year"],
        index=0
    )
    display_df.sort_values(sort_col, ascending=(sort_col in ["Price (₹L)", "KM Driven"]), inplace=True)

    st.dataframe(
        display_df,
        use_container_width=True,
        height=500,
        column_config={
            "Link": st.column_config.LinkColumn("Link"),
            "Price (₹L)": st.column_config.NumberColumn(format="₹%.2f L"),
            "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.1f"),
            "KM Driven": st.column_config.NumberColumn(format="%d km"),
        }
    )

    st.caption(f"Showing {len(display_df)} of {len(df)} listings")

    # ── Export ──────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📤 Export Data")
    col_exp1, col_exp2 = st.columns(2)
    with col_exp1:
        excel_data = to_excel_bytes(df)
        st.download_button(
            label="⬇️ Download Full Dataset (Excel)",
            data=excel_data,
            file_name=f"chennai_cars_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    with col_exp2:
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="⬇️ Download Full Dataset (CSV)",
            data=csv_data,
            file_name=f"chennai_cars_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )

    # ── Market Insights ─────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📈 Market Insights")

    if "model" in df.columns and "price" in df.columns:
        model_stats = (
            df.groupby("model")
            .agg(
                avg_price=("price", "mean"),
                min_price=("price", "min"),
                max_price=("price", "max"),
                count=("price", "count"),
                trend=("trend", "first") if "trend" in df.columns else ("price", "count")
            )
            .reset_index()
            .sort_values("count", ascending=False)
            .head(15)
        )
        model_stats["avg_price"] = model_stats["avg_price"].round(2)
        st.dataframe(model_stats, use_container_width=True)

elif "result_df" not in st.session_state:
    # Landing state
    st.markdown("""
    <div style="text-align:center;padding:60px 20px;color:#64748b">
        <div style="font-size:4rem;margin-bottom:16px">🚗</div>
        <h3 style="color:#94a3b8">Configure your filters and click <span style="color:#60a5fa">Fetch & Analyse Cars</span></h3>
        <p>The system will scrape live listings from CarWale & Spinny, analyse the market,<br>
        detect trends, and provide AI-powered BUY / WAIT / SKIP recommendations.</p>
        <br>
        <div style="display:flex;justify-content:center;gap:32px;flex-wrap:wrap;color:#64748b;font-size:0.85rem">
            <div>🌐 Live scraping</div>
            <div>📊 Price benchmarks</div>
            <div>📈 Trend detection</div>
            <div>🤖 AI decisions</div>
            <div>📤 Excel export</div>
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.warning("⚠️ No listings matched your filters. Try relaxing some filter criteria.")

# ── Footer ──────────────────────────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:24px;color:#334155;font-size:0.75rem;margin-top:40px">
    Chennai Used Car AI Analyzer • Powered by Playwright + Claude/OpenAI • Data from CarWale & Spinny
</div>
""", unsafe_allow_html=True)
