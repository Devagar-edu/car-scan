"""
scraper.py - Async Playwright-based scraper for CarWale and Spinny used car listings in Chennai.
Implements retry logic, fallback regex extraction, and dynamic content handling.

Verified against live site structure (April 2026):
- CarWale: /used/chennai/ — server-side rendered listing cards
  Price format: "Rs. 64 Lakh" | "Rs. 1.95 Crore"
  KM/fuel in subtitle: "21,321 km | Petrol | Location"
  Year embedded in h3 title: "2023 BMW iX xDrive 40"
- Spinny: /used-cars-in-chennai/s/ — React SPA; uses internal REST API
  API: https://api.spinny.com/v3/api/listing/v6/?city=chennai&page=1
  Price format: numeric in JSON (e.g. 649000 = Rs 6.49 Lakh)
  Field names: make, model, variant, mileage, make_year, price, fuel_type, permanent_url
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
      649000.0 (float)     -> 6.49   (raw rupees float from Spinny API)
      "6.49"               -> 6.49   (already in lakhs)
    """
    if not text:
        return None

    # Handle numeric input (int or float) directly
    if isinstance(text, (int, float)):
        val = float(text)
        # Raw rupees (Spinny API returns e.g. 649000.0)
        if val >= 100000:  # Changed from > 10000 to >= 100000 for better threshold
            return round(val / 100000, 2)
        # Already in lakhs (e.g. 6.49, 12.5, 64.0)
        return round(val, 2)

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
        if val >= 100000:  # Changed from > 10000 to >= 100000 for better threshold
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
            "div.ctofvW",  # Updated: actual listing cards on current CarWale site
            "div[class*='card']",
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

                    # Subtitle: "km | fuel | location" - try multiple selectors
                    subtitle_el = None
                    for subtitle_sel in ["span", "p", "[class*='subtitle']", "[class*='specs']", "[class*='detail']", "[class*='info']"]:
                        candidates = await card.query_selector_all(subtitle_sel)
                        for candidate in candidates:
                            candidate_text = await candidate.inner_text()
                            if "km" in candidate_text.lower() and "|" in candidate_text:
                                subtitle_el = candidate
                                break
                        if subtitle_el:
                            break
                    
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
    """
    Regex fallback parser with per-card chunking to prevent misalignment.
    
    Splits HTML into per-card chunks before running regexes to ensure
    km figures from distance-to-dealer text don't get matched before
    listing-specific km figures.
    """
    listings = []

    # Strategy 1: Try to extract from structured data (JSON-LD)
    # CarWale embeds structured data with accurate price/km/year
    json_ld_pattern = re.findall(
        r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
        html,
        re.DOTALL
    )
    
    for json_str in json_ld_pattern:
        try:
            data = json.loads(json_str)
            # Handle both single object and array
            items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            
            for item in items:
                if item.get('@type') in ['Car', 'Vehicle', 'Product']:
                    title = item.get('name', '')
                    year = item.get('vehicleModelDate') or _parse_year(title)
                    
                    # Price from offers
                    offers = item.get('offers', {})
                    price_val = offers.get('price') if isinstance(offers, dict) else None
                    price = _parse_price(price_val) if price_val else None
                    
                    # KM from mileageFromOdometer
                    km_val = item.get('mileageFromOdometer', {}).get('value') if isinstance(item.get('mileageFromOdometer'), dict) else None
                    km = float(km_val) if km_val else None
                    
                    # Fuel type
                    fuel = item.get('fuelType', 'Unknown')
                    
                    # URL
                    url_val = item.get('url', base_url)
                    
                    if title and price and price > 0:
                        listings.append({
                            "title": title,
                            "price": price,
                            "km": km,
                            "year": int(year) if year else None,
                            "fuel_type": _parse_fuel(fuel),
                            "link": url_val if url_val.startswith('http') else f"https://www.carwale.com{url_val}",
                            "source": "CarWale",
                            "scraped_at": datetime.now().isoformat()
                        })
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug(f"CarWale JSON-LD parse error: {e}")
            continue
    
    # Strategy 2: Per-card regex extraction (if JSON-LD didn't work)
    if not listings:
        # Split HTML into card chunks
        # Try multiple split patterns
        card_chunks = []
        for pattern in [r'<li[^>]*class="[^"]*(?:listing|card)[^"]*"[^>]*>',
                       r'<article[^>]*>',
                       r'<div[^>]*class="[^"]*(?:cardContent|listing)[^"]*"[^>]*>']:
            card_chunks = re.split(pattern, html)
            if len(card_chunks) > 5:  # Found a good split pattern
                break
        
        # If no good split found, fall back to old behavior but limit to first 25 matches
        if len(card_chunks) <= 5:
            card_chunks = [html]  # Treat whole page as one chunk
        
        for chunk in card_chunks[:30]:  # Process max 30 chunks
            # Extract from this chunk only
            title_match = re.search(r'<h[23][^>]*>\s*(20\d{2}\s+[A-Z][^<]{4,60}?)\s*</h[23]>', chunk)
            price_match = re.search(r'Rs\.?\s*([\d,.]+\s*(?:Lakh|Crore|lakh|crore))', chunk)
            km_match = re.search(r'([\d,]+)\s*km\b', chunk, re.IGNORECASE)
            fuel_match = re.search(r'\|\s*(Petrol|Diesel|CNG|Electric|Hybrid|LPG|Plug-in Hybrid)\s*\|', chunk)
            link_match = re.search(r'href="(/used/chennai/[a-z0-9-]+/[a-z0-9]+/)"', chunk)
            
            if title_match:
                title = title_match.group(1)
                price_raw = "Rs. " + price_match.group(1) if price_match else ""
                km_raw = km_match.group(1) if km_match else None
                fuel = fuel_match.group(1) if fuel_match else "Unknown"
                href = link_match.group(1) if link_match else ""
                
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

SPINNY_API = "https://api.spinny.com/v3/api/listing/v6/"
SPINNY_PARAMS = "?city=chennai&product_type=cars&category=used&page={page}&size=20&show_max_on_assured=true&custom_budget_sort=true&ratio_status=available&prioritize_filter_listing=true&high_intent_required=true&active_banner=true&added_in_inventory=true"


async def _fetch_spinny_api(page: Page, api_url: str) -> List[Dict]:
    """Call Spinny's internal REST API via Playwright request context."""
    listings = []
    try:
        # Generate anonymous-id (timestamp-based)
        import time
        anonymous_id = f"{int(time.time())}.{int(time.time())}"
        
        response = await page.request.get(
            api_url,
            timeout=TIMEOUT_MS,
            headers={
                "Accept": "application/json",
                "Referer": "https://www.spinny.com/",
                "X-Requested-With": "XMLHttpRequest",
                "anonymous-id": anonymous_id,
                "platform": "web",
                "content-type": "application/json",
            }
        )
        if response.status != 200:
            logger.warning(f"Spinny API {api_url}: HTTP {response.status}")
            return listings

        data = await response.json()
        # API returns: {"count": N, "results": [...]} or {"data": [...]} or {"listings": [...]}
        cars = data.get("results") or data.get("data") or data.get("listings") or []

        for car in cars:
            try:
                # Build title from make, model, variant (new API structure)
                make = car.get("make", "")
                model = car.get("model", "")
                variant = car.get("variant", "")
                year_val = car.get("make_year") or car.get("registration_year") or car.get("year")
                
                # Try multiple title formats
                title = (
                    car.get("carName")
                    or car.get("car_name")
                    or car.get("title")
                    or f"{year_val} {make} {model} {variant}".strip()
                    or f"{make} {model} {variant}".strip()
                )

                raw_price = (
                    car.get("price")
                    or car.get("selling_price")
                    or car.get("sp")
                    or 0
                )
                price = _parse_price(str(raw_price))

                # Try multiple km field names
                km_val = (
                    car.get("mileage")
                    or car.get("kms_driven")
                    or car.get("km_driven")
                    or car.get("odometer")
                    or car.get("round_off_mileage")
                )
                km = float(km_val) if km_val else None

                year = int(year_val) if year_val else _parse_year(title)

                fuel = car.get("fuel_type") or car.get("fuel") or "Unknown"
                
                # Try multiple slug/URL field names
                slug = (
                    car.get("permanent_url")
                    or car.get("car_slug")
                    or car.get("slug")
                    or ""
                )

                if title and price and price > 0:
                    # Build link from permanent_url or slug
                    if slug and slug.startswith("/"):
                        link = f"https://www.spinny.com{slug}"
                    elif slug and not slug.startswith("http"):
                        link = f"https://www.spinny.com/buy-used-{slug}/"
                    elif slug:
                        link = slug
                    else:
                        link = "https://www.spinny.com/used-cars-in-chennai/s/"
                    
                    listings.append({
                        "title": title,
                        "price": price,
                        "km": km,
                        "year": year,
                        "fuel_type": _parse_fuel(fuel),
                        "link": link,
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
            if ("api" in resp.url or "car_listing" in resp.url or "listing" in resp.url) and resp.status == 200:
                ct = resp.headers.get("content-type", "")
                if "json" in ct:
                    body = await resp.body()
                    text = body.decode("utf-8", errors="ignore")
                    # Updated filter to match new field names: make, model, mileage, make_year
                    if any(key in text for key in ["make", "model", "mileage", "make_year", "carName", "kms_driven"]):
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
                cars = data.get("results") or data.get("data") or data.get("listings") or []
                for car in cars:
                    # Build title from make, model, variant
                    make = car.get("make", "")
                    model = car.get("model", "")
                    variant = car.get("variant", "")
                    year_val = car.get("make_year") or car.get("registration_year") or car.get("year")
                    
                    title = (
                        car.get("carName")
                        or car.get("car_name")
                        or car.get("title")
                        or f"{year_val} {make} {model} {variant}".strip()
                        or f"{make} {model} {variant}".strip()
                    )
                    
                    raw_price = car.get("price") or car.get("selling_price") or 0
                    price = _parse_price(str(raw_price))
                    
                    km_val = (
                        car.get("mileage")
                        or car.get("kms_driven")
                        or car.get("km_driven")
                        or car.get("round_off_mileage")
                    )
                    km = float(km_val) if km_val else None
                    
                    year = int(year_val) if year_val else _parse_year(title)
                    fuel = car.get("fuel_type") or "Unknown"
                    
                    slug = (
                        car.get("permanent_url")
                        or car.get("car_slug")
                        or car.get("slug")
                        or ""
                    )
                    
                    if title and price and price > 0:
                        # Build link from permanent_url or slug
                        if slug and slug.startswith("/"):
                            link = f"https://www.spinny.com{slug}"
                        elif slug and not slug.startswith("http"):
                            link = f"https://www.spinny.com/buy-used-{slug}/"
                        elif slug:
                            link = slug
                        else:
                            link = url
                        
                        listings.append({
                            "title": title, "price": price, "km": km,
                            "year": year, "fuel_type": _parse_fuel(fuel),
                            "link": link,
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
            # Try multiple possible paths for car list
            cars = (
                props.get("carList")
                or props.get("cars")
                or props.get("listings")
                or props.get("results")
                or props.get("initialData", {}).get("cars")
                or props.get("initialData", {}).get("results")
                or []
            )
            for car in cars:
                if isinstance(car, dict):
                    # Build title from make, model, variant
                    make = car.get("make", "")
                    model = car.get("model", "")
                    variant = car.get("variant", "")
                    year_val = car.get("make_year") or car.get("registration_year") or car.get("year")
                    
                    title = (
                        car.get("carName")
                        or car.get("car_name")
                        or car.get("title")
                        or f"{year_val} {make} {model} {variant}".strip()
                        or f"{make} {model} {variant}".strip()
                    )
                    
                    raw_price = car.get("price") or 0
                    price = _parse_price(str(raw_price))
                    
                    km = float(car.get("mileage") or car.get("kms_driven") or 0) or None
                    year = int(year_val) if year_val else _parse_year(title)
                    
                    if title and price and price > 0:
                        listings.append({
                            "title": title, "price": price, "km": km, "year": year,
                            "fuel_type": _parse_fuel(car.get("fuel_type", "")),
                            "link": base_url, "source": "Spinny",
                            "scraped_at": datetime.now().isoformat()
                        })
        except Exception as e:
            logger.debug(f"Spinny __NEXT_DATA__ parse error: {e}")

    # Raw JSON pattern fallback - try both old and new field names
    if not listings:
        # Try new field names: make, model, variant, price
        pattern_new = re.findall(
            r'"(?:make)"\s*:\s*"([^"]+)"[^}]{0,200}"(?:model)"\s*:\s*"([^"]+)"[^}]{0,200}"price"\s*:\s*(\d{4,8})',
            html, re.DOTALL
        )
        for make, model, price_str in pattern_new[:25]:
            title = f"{make} {model}".strip()
            price = _parse_price(price_str)
            year = _parse_year(title)
            if price:
                listings.append({
                    "title": title, "price": price, "km": None, "year": year,
                    "fuel_type": "Unknown", "link": base_url, "source": "Spinny",
                    "scraped_at": datetime.now().isoformat()
                })
        
        # Try old field names: carName, car_name, title
        if not listings:
            pattern_old = re.findall(
                r'"(?:carName|car_name|title)"\s*:\s*"([^"]{6,60})"[^}]{0,400}"price"\s*:\s*(\d{4,8})',
                html, re.DOTALL
            )
            for title, price_str in pattern_old[:25]:
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
