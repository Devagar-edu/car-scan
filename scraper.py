"""
scraper.py - Async Playwright-based scraper for CarWale and Spinny used car listings in Chennai.
Implements retry logic, fallback regex extraction, and dynamic content handling.

Verified against live site structure (April 2026):
- CarWale: /used/chennai/ — server-side rendered listing cards
  Price format: "Rs. 64 Lakh" | "Rs. 1.95 Crore"
  KM/fuel in subtitle: "21,321 km | Petrol | Location"
  Year embedded in h3 title: "2023 BMW iX xDrive 40"
- Spinny: /used-cars-in-chennai/s/ — React SPA; uses internal REST API
  API: https://www.spinny.com/api/v2/car_listing/?city=chennai&page=1
  Price format: numeric in JSON (e.g. 649000 = Rs 6.49 Lakh)
"""

import asyncio
import json
import re
import logging
from typing import List, Dict, Optional
from datetime import datetime
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
TIMEOUT_MS = 45000


# ─────────────────────────────────────────────────────────────────────────────
# Price / KM / Year Parsers  (fixed for real site formats)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_price(text: str) -> Optional[float]:
    """
    Convert any Indian price string to Lakhs (float).

    Handles:
      "Rs. 64 Lakh"        -> 64.0
      "Rs. 1.95 Crore"     -> 195.0
      "Rs.1.95Crore"       -> 195.0
      "64 Lakh"            -> 64.0
      "649000"             -> 6.49   (raw rupees integer from Spinny API)
      "6.49"               -> 6.49   (already in lakhs)
    """
    if not text:
        return None

    s = str(text).strip()
    # Normalize: remove currency symbols, commas
    s = s.replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "").strip()

    # Crore -> Lakhs
    crore = re.search(r"([\d.]+)\s*[Cc]r(?:ore)?", s)
    if crore:
        return round(float(crore.group(1)) * 100, 2)

    # Lakh / Lac
    lakh = re.search(r"([\d.]+)\s*(?:[Ll]akh|[Ll]ac)\b", s)
    if lakh:
        return round(float(lakh.group(1)), 2)

    # Plain number
    plain = re.search(r"([\d]+(?:\.\d+)?)", s)
    if plain:
        val = float(plain.group(1))
        # Raw rupees (Spinny API returns e.g. 649000)
        if val > 10000:
            return round(val / 100000, 2)
        # Already in lakhs (e.g. 6.49, 12.5)
        return round(val, 2)

    return None


def _parse_km(text: str) -> Optional[float]:
    """Parse km driven from strings like '21,321 km', '45000 kms', '45000'."""
    if not text:
        return None
    s = str(text).replace(",", "").lower()
    m = re.search(r"(\d+)", s)
    return float(m.group(1)) if m else None


def _parse_year(text: str) -> Optional[int]:
    """Extract a 4-digit model year (2000-2026) from text."""
    m = re.search(r"\b(20[012]\d)\b", str(text))
    return int(m.group(1)) if m else None


def _parse_fuel(text: str) -> str:
    """Detect fuel type from any text blob."""
    t = str(text).lower()
    if "plug-in hybrid" in t or "phev" in t:
        return "Hybrid"
    if "electric" in t or " ev " in t or "bev" in t:
        return "Electric"
    if "cng" in t:
        return "CNG"
    if "lpg" in t:
        return "LPG"
    if "diesel" in t:
        return "Diesel"
    if "petrol" in t or "gasoline" in t:
        return "Petrol"
    return "Unknown"


# ─────────────────────────────────────────────────────────────────────────────
# CarWale Scraper
# Verified URL: https://www.carwale.com/used/chennai/
# Listing structure (from live HTML):
#   <li> or <div> cards containing:
#     <h3> "2023 BMW iX xDrive 40" </h3>
#     subtitle: "21,321 km  |  Electric  |  Location"
#     price span: "Rs. 64 Lakh"
#     <a href="/used/chennai/bmw-ix/0324h7uw/">
# ─────────────────────────────────────────────────────────────────────────────

async def _scrape_carwale_page(page: Page, url: str) -> List[Dict]:
    listings = []
    try:
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        for _ in range(4):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(800)

        # Strategy 1: Try structured selectors (order: most specific first)
        card_selectors = [
            "li[class*='listing']",
            "li[class*='card']",
            "div[class*='cardContent']",
            "div[class*='listing']",
            "article",
        ]
        cards = []
        for sel in card_selectors:
            cards = await page.query_selector_all(sel)
            if len(cards) >= 3:
                logger.info(f"CarWale: {len(cards)} cards via '{sel}'")
                break

        if cards:
            for card in cards:
                try:
                    title_el = await card.query_selector("h3, h2, h4, [class*='title'], [class*='name']")
                    title = (await title_el.inner_text()).strip() if title_el else ""

                    # Price element
                    price_el = await card.query_selector(
                        "[class*='price'], [class*='Price'], [class*='amount'], [class*='Amount']"
                    )
                    price_raw = (await price_el.inner_text()).strip() if price_el else ""

                    # Subtitle: "km | fuel | location"
                    subtitle_el = await card.query_selector(
                        "p, [class*='subtitle'], [class*='specs'], [class*='detail'], [class*='info']"
                    )
                    subtitle = (await subtitle_el.inner_text()).strip() if subtitle_el else ""

                    # If no price from element, scan card text
                    if not price_raw:
                        card_text = await card.inner_text()
                        m = re.search(r"Rs\.?\s*([\d,.]+\s*(?:Lakh|Crore|lakh|crore))", card_text)
                        if m:
                            price_raw = "Rs. " + m.group(1)

                    link_el = await card.query_selector("a[href*='/used/']")
                    href = await link_el.get_attribute("href") if link_el else ""

                    price = _parse_price(price_raw)
                    year = _parse_year(title)

                    # KM from first pipe segment of subtitle
                    parts = [p.strip() for p in subtitle.split("|")]
                    km = _parse_km(parts[0]) if parts else None
                    fuel = _parse_fuel(parts[1] if len(parts) > 1 else subtitle or title)

                    if title and price and price > 0:
                        listings.append({
                            "title": title,
                            "price": price,
                            "km": km,
                            "year": year,
                            "fuel_type": fuel,
                            "link": f"https://www.carwale.com{href}" if href and href.startswith("/") else href or url,
                            "source": "CarWale",
                            "scraped_at": datetime.now().isoformat()
                        })
                except Exception as e:
                    logger.debug(f"CarWale card parse error: {e}")

        # Strategy 2: regex fallback
        if not listings:
            logger.warning(f"CarWale selectors empty for {url}, using regex fallback")
            content = await page.content()
            listings = _fallback_parse_carwale(content, url)

    except Exception as e:
        logger.error(f"CarWale page error ({url}): {e}")

    return listings


def _fallback_parse_carwale(html: str, base_url: str) -> List[Dict]:
    """Regex fallback parser — works against verified CarWale live HTML."""
    listings = []

    # Titles from h3/h2: ">2023 BMW iX xDrive 40<"
    titles = re.findall(r'<h[23][^>]*>\s*(20\d{2}\s+[A-Z][^<]{4,60}?)\s*</h[23]>', html)

    # Prices: "Rs. 64 Lakh" or "Rs. 1.95 Crore"
    prices = re.findall(r'Rs\.?\s*([\d,.]+\s*(?:Lakh|Crore|lakh|crore))', html)

    # KM: "21,321 km"
    kms = re.findall(r'([\d,]+)\s*km\b', html, re.IGNORECASE)

    # Fuel from pipe-separated spec strings
    fuels = re.findall(r'\|\s*(Petrol|Diesel|CNG|Electric|Hybrid|LPG|Plug-in Hybrid)\s*\|', html)

    # Links
    links = re.findall(r'href="(/used/chennai/[a-z0-9-]+/[a-z0-9]+/)"', html)

    count = min(max(len(titles), 1), 25)
    for i in range(count):
        title = titles[i] if i < len(titles) else f"Car {i+1}"
        price_raw = "Rs. " + prices[i] if i < len(prices) else ""
        km_raw = kms[i] if i < len(kms) else None
        fuel = fuels[i] if i < len(fuels) else "Unknown"
        href = links[i] if i < len(links) else ""

        price = _parse_price(price_raw)
        km = _parse_km(km_raw)
        year = _parse_year(title)

        if title and price and price > 0:
            listings.append({
                "title": title,
                "price": price,
                "km": km,
                "year": year,
                "fuel_type": _parse_fuel(fuel),
                "link": f"https://www.carwale.com{href}" if href else base_url,
                "source": "CarWale",
                "scraped_at": datetime.now().isoformat()
            })

    logger.info(f"CarWale regex fallback: {len(listings)} listings from {base_url}")
    return listings


async def scrape_carwale(max_pages: int = 3) -> List[Dict]:
    """Entry point for CarWale with retry logic."""
    all_listings = []
    base = "https://www.carwale.com/used/chennai/"
    urls = [base] + [f"https://www.carwale.com/used/chennai/page-{p}/" for p in range(2, max_pages + 1)]

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-IN",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        for url in urls:
            for attempt in range(MAX_RETRIES):
                try:
                    results = await _scrape_carwale_page(page, url)
                    all_listings.extend(results)
                    logger.info(f"CarWale {url}: {len(results)} listings")
                    await asyncio.sleep(2)
                    break
                except PlaywrightTimeout:
                    logger.warning(f"CarWale timeout attempt {attempt+1} for {url}")
                    if attempt == MAX_RETRIES - 1:
                        logger.error(f"CarWale: all retries failed for {url}")
                except Exception as e:
                    logger.error(f"CarWale attempt {attempt+1} error: {e}")
                    if attempt == MAX_RETRIES - 1:
                        logger.error(f"CarWale: giving up on {url}")

        await browser.close()

    return all_listings


# ─────────────────────────────────────────────────────────────────────────────
# Spinny Scraper
# Verified URL: https://www.spinny.com/used-cars-in-chennai/s/
# This is a React SPA — car data is NOT in the static HTML.
# Spinny exposes a REST API used by its own frontend:
#   GET https://www.spinny.com/api/v2/car_listing/?city=chennai&page=1&page_size=24
# Response JSON keys: carName, price (raw rupees int), kms_driven, make_year, fuel_type, car_slug
# ─────────────────────────────────────────────────────────────────────────────

SPINNY_API = "https://www.spinny.com/api/v2/car_listing/"
SPINNY_PARAMS = "?city=chennai&page={page}&page_size=24&ordering=-created_at"


async def _fetch_spinny_api(page: Page, api_url: str) -> List[Dict]:
    """Call Spinny's internal REST API via Playwright request context."""
    listings = []
    try:
        response = await page.request.get(
            api_url,
            timeout=TIMEOUT_MS,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.spinny.com/",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        if response.status != 200:
            logger.warning(f"Spinny API {api_url}: HTTP {response.status}")
            return listings

        data = await response.json()
        # API returns: {"count": N, "results": [...]} or {"data": [...]}
        cars = data.get("results") or data.get("data") or []

        for car in cars:
            try:
                title = (
                    car.get("carName")
                    or car.get("car_name")
                    or car.get("title")
                    or "{} {} {}".format(
                        car.get("make_year", ""),
                        car.get("brand", ""),
                        car.get("model", "")
                    ).strip()
                )

                raw_price = (
                    car.get("price")
                    or car.get("selling_price")
                    or car.get("sp")
                    or 0
                )
                price = _parse_price(str(raw_price))

                km_val = car.get("kms_driven") or car.get("km_driven") or car.get("odometer")
                km = float(km_val) if km_val else None

                year_val = car.get("make_year") or car.get("year")
                year = int(year_val) if year_val else _parse_year(title)

                fuel = car.get("fuel_type") or car.get("fuel") or "Unknown"
                slug = car.get("car_slug") or car.get("slug") or ""

                if title and price and price > 0:
                    listings.append({
                        "title": title,
                        "price": price,
                        "km": km,
                        "year": year,
                        "fuel_type": _parse_fuel(fuel),
                        "link": f"https://www.spinny.com/buy-used-{slug}/" if slug else "https://www.spinny.com/used-cars-in-chennai/s/",
                        "source": "Spinny",
                        "scraped_at": datetime.now().isoformat()
                    })
            except Exception as e:
                logger.debug(f"Spinny item parse error: {e}")

    except Exception as e:
        logger.error(f"Spinny API fetch error: {e}")

    return listings


async def _scrape_spinny_browser(page: Page) -> List[Dict]:
    """
    Browser fallback: load Spinny SPA and intercept XHR responses
    that carry car listing JSON.
    """
    listings = []
    captured = []

    async def on_response(resp):
        try:
            if ("api" in resp.url or "car_listing" in resp.url) and resp.status == 200:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    body = await resp.body()
                    text = body.decode("utf-8", errors="ignore")
                    if "carName" in text or "kms_driven" in text:
                        captured.append(text)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        url = "https://www.spinny.com/used-cars-in-chennai/s/"
        await page.goto(url, timeout=TIMEOUT_MS, wait_until="domcontentloaded")
        await page.wait_for_timeout(6000)

        for _ in range(5):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await page.wait_for_timeout(1500)

        for text in captured:
            try:
                data = json.loads(text)
                cars = data.get("results") or data.get("data") or []
                for car in cars:
                    title = car.get("carName") or car.get("car_name") or car.get("title") or ""
                    raw_price = car.get("price") or car.get("selling_price") or 0
                    price = _parse_price(str(raw_price))
                    km_val = car.get("kms_driven") or car.get("km_driven")
                    km = float(km_val) if km_val else None
                    year_val = car.get("make_year") or car.get("year")
                    year = int(year_val) if year_val else _parse_year(title)
                    fuel = car.get("fuel_type") or "Unknown"
                    slug = car.get("car_slug") or ""
                    if title and price and price > 0:
                        listings.append({
                            "title": title, "price": price, "km": km,
                            "year": year, "fuel_type": _parse_fuel(fuel),
                            "link": f"https://www.spinny.com/buy-used-{slug}/" if slug else url,
                            "source": "Spinny",
                            "scraped_at": datetime.now().isoformat()
                        })
            except Exception:
                pass

        if not listings:
            page_html = await page.content()
            listings = _fallback_parse_spinny(page_html, url)

    except Exception as e:
        logger.error(f"Spinny browser fallback error: {e}")

    return listings


def _fallback_parse_spinny(html: str, base_url: str) -> List[Dict]:
    """Last-resort regex extraction from Spinny page source / Next.js data."""
    listings = []

    # Spinny embeds __NEXT_DATA__ JSON in a script tag
    next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if next_data_match:
        try:
            nd = json.loads(next_data_match.group(1))
            # Navigate into pageProps to find car data
            props = nd.get("props", {}).get("pageProps", {})
            cars = props.get("carList") or props.get("cars") or props.get("listings") or []
            for car in cars:
                if isinstance(car, dict):
                    title = car.get("carName") or car.get("title") or ""
                    raw_price = car.get("price") or 0
                    price = _parse_price(str(raw_price))
                    km = float(car.get("kms_driven") or 0) or None
                    year = int(car.get("make_year") or 0) or _parse_year(title)
                    if title and price and price > 0:
                        listings.append({
                            "title": title, "price": price, "km": km, "year": year,
                            "fuel_type": _parse_fuel(car.get("fuel_type", "")),
                            "link": base_url, "source": "Spinny",
                            "scraped_at": datetime.now().isoformat()
                        })
        except Exception as e:
            logger.debug(f"Spinny __NEXT_DATA__ parse error: {e}")

    # Raw JSON pattern fallback
    if not listings:
        pattern = re.findall(
            r'"(?:carName|car_name|title)"\s*:\s*"([^"]{6,60})"[^}]{0,400}"price"\s*:\s*(\d{4,8})',
            html, re.DOTALL
        )
        for title, price_str in pattern[:25]:
            price = _parse_price(price_str)
            year = _parse_year(title)
            if price:
                listings.append({
                    "title": title, "price": price, "km": None, "year": year,
                    "fuel_type": "Unknown", "link": base_url, "source": "Spinny",
                    "scraped_at": datetime.now().isoformat()
                })

    logger.info(f"Spinny regex fallback: {len(listings)} listings")
    return listings


async def scrape_spinny(max_pages: int = 3) -> List[Dict]:
    """
    Entry point for Spinny scraper.
    1. Direct API calls (most reliable)
    2. Browser + XHR interception
    3. Regex on page source
    """
    all_listings = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="en-IN",
        )
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        page = await context.new_page()

        # Attempt 1: Direct API
        api_success = False
        for pg in range(1, max_pages + 1):
            api_url = SPINNY_API + SPINNY_PARAMS.format(page=pg)
            for attempt in range(MAX_RETRIES):
                try:
                    results = await _fetch_spinny_api(page, api_url)
                    if results:
                        all_listings.extend(results)
                        api_success = True
                        logger.info(f"Spinny API page {pg}: {len(results)} listings")
                        await asyncio.sleep(1.5)
                        break
                    else:
                        logger.warning(f"Spinny API page {pg}: 0 results, skipping further pages")
                        break
                except PlaywrightTimeout:
                    logger.warning(f"Spinny API timeout attempt {attempt+1}, page {pg}")
                except Exception as e:
                    logger.error(f"Spinny API error: {e}")

        # Attempt 2: Browser with XHR interception
        if not api_success:
            logger.info("Spinny: switching to browser scrape")
            for attempt in range(MAX_RETRIES):
                try:
                    results = await _scrape_spinny_browser(page)
                    all_listings.extend(results)
                    logger.info(f"Spinny browser fallback: {len(results)} listings")
                    break
                except Exception as e:
                    logger.error(f"Spinny browser attempt {attempt+1}: {e}")
                    if attempt == MAX_RETRIES - 1:
                        logger.error("Spinny: all strategies exhausted")

        await browser.close()

    return all_listings


# ─────────────────────────────────────────────────────────────────────────────
# Combined Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def scrape_all(max_pages: int = 3) -> List[Dict]:
    """Run both scrapers sequentially and combine results."""
    combined = []
    for fn, name in [(scrape_carwale, "CarWale"), (scrape_spinny, "Spinny")]:
        try:
            results = await fn(max_pages)
            combined.extend(results)
            logger.info(f"{name}: {len(results)} listings")
        except Exception as e:
            logger.error(f"{name} scraper failed: {e}")

    sources = set(r["source"] for r in combined)
    logger.info(f"Total: {len(combined)} listings from {sources}")
    return combined
