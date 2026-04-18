# Chennai Used Car AI Analyzer

A production-ready AI system that scrapes used car listings from CarWale and Spinny, computes real-time market benchmarks, detects price trends, and delivers **BUY / WAIT / SKIP** recommendations via an AI-powered Streamlit dashboard.

---

## 📁 Project Structure

```
project/
├── app.py                  ← Streamlit dashboard (main entry point)
├── scraper.py              ← Async Playwright scraper (CarWale + Spinny)
├── validator.py            ← Data cleaning, validation, filtering
├── market_store.py         ← Persistent CSV-based historical data store
├── price_engine.py         ← Per-model price benchmarks (avg/min/max)
├── trend_engine.py         ← Price trend detection (INCREASING/DROPPING/STABLE)
├── market_intelligence.py  ← UNDERPRICED / FAIR / OVERPRICED classification
├── ai_engine.py            ← AI decision engine (Claude/OpenAI, batch processing)
├── scoring.py              ← Composite 0–100 scoring
├── cache.py                ← File-based TTL cache (45-minute window)
├── requirements.txt
└── README.md
```

---

## ⚡ Quick Setup

### 1. Create virtual environment

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Playwright browsers

```bash
playwright install chromium
```

### 4. Set up API key (optional but recommended)

Create a `.env` file (or set as environment variable):

```env
ANTHROPIC_API_KEY=sk-ant-...
# or
OPENAI_API_KEY=sk-...
```

Or enter it directly in the Streamlit sidebar.

### 5. Run the dashboard

```bash
streamlit run app.py
```

The app will open at **http://localhost:8501**

---

## 🎯 How to Use

1. **Open the sidebar** and configure filters (year, km, price, fuel type)
2. **Enter your API key** (Anthropic or OpenAI) for AI-powered decisions — or leave blank for rule-based fallback
3. **Click "Fetch & Analyse Cars"** to run the full pipeline
4. View **Top Recommendations**, **All Listings** table, and **Market Insights**
5. **Download** results as Excel or CSV

---

## 🔄 Pipeline Flow

```
Scrape (CarWale + Spinny)
    ↓
Clean & Validate
    ↓
Store to CSV history (data/listings_history.csv)
    ↓
Compute Price Benchmarks (per model avg/min/max)
    ↓
Detect Trends (recent vs older data)
    ↓
Market Intelligence (UNDERPRICED / FAIR / OVERPRICED)
    ↓
AI Decisions in batches of 15 (BUY / WAIT / SKIP)
    ↓
Composite Scoring (0–100)
    ↓
Apply User Filters
    ↓
Display in Dashboard
```

---

## 🧠 AI Decision Logic

| Condition | Decision |
|-----------|----------|
| Underpriced + stable/rising trend | **BUY** (HIGH confidence) |
| Fair price, low KM, recent year | **BUY** (MEDIUM) |
| Price dropping | **WAIT** (better deal soon) |
| Overpriced | **WAIT** or **SKIP** |
| Very high KM (>120k) or old year (<2013) | **SKIP** |

---

## ⚙️ Configuration Notes

- **Cache TTL**: 45 minutes by default (edit `cache.py` → `DEFAULT_TTL_MINUTES`)
- **Batch size**: 15 cars per AI API call (edit `ai_engine.py` → `BATCH_SIZE`)
- **Trend window**: Recent = last 3 days, Older = 3–14 days (edit `trend_engine.py`)
- **Scraping pages**: 3 pages per site by default (controllable in `app.py`)

---

## ⚠️ Known Considerations

- **Anti-scraping**: CarWale and Spinny may use bot detection. The scraper uses realistic user-agents and scroll simulation. If scraping fails, the app falls back to historical data.
- **First run**: On first run, no historical data exists for trend analysis — trends will default to STABLE.
- **API keys**: Without an API key, the system uses a deterministic rule engine that is still quite accurate.

---

## 🛠️ Troubleshooting

| Issue | Fix |
|-------|-----|
| `playwright install` not found | Run `python -m playwright install chromium` |
| No listings returned | Sites may be blocking — check logs; data falls back to history |
| AI rate limit error | Reduce batch size or add retry delay in `ai_engine.py` |
| `ModuleNotFoundError` | Ensure venv is activated and `pip install -r requirements.txt` ran |
