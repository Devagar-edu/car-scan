# Bugfix Requirements Document

## Introduction

The Chennai Used Car AI Analyzer scrapes live listings from CarWale and Spinny via
Playwright (async). Two related bugs are present in `scraper.py`:

1. **Spinny returns 0 results** — The scraper's three-strategy chain (direct REST API →
   browser XHR interception → `__NEXT_DATA__` regex) all fail to return any car listings.
   The most likely causes are: the API endpoint path or query-parameter schema has changed,
   the site now requires authentication/session cookies that the headless browser does not
   supply, or the JSON response structure no longer matches the expected keys
   (`results`, `carName`, `kms_driven`, `make_year`, `car_slug`).

2. **Incorrect scraped values (price, km, year)** — When listings are returned from either
   source, the parsed numeric values are wrong. Prices may be off by orders of magnitude,
   km readings may be swapped with other fields, or years may not be extracted at all.
   This points to mismatches between the current live HTML/JSON structure and the selectors,
   regex patterns, and field-name assumptions baked into the parsers.

Both bugs degrade the downstream pipeline: market benchmarks, trend analysis, AI decisions,
and scoring all depend on accurate, non-empty listing data.

---

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `scrape_spinny()` is called THEN the system returns 0 listings because the
    direct API call to `https://www.spinny.com/api/v2/car_listing/?city=chennai` returns
    a non-200 status or an empty/unrecognised JSON structure.

1.2 WHEN the Spinny direct API fails and the browser XHR interception fallback runs THEN
    the system captures 0 matching responses because the intercepted network requests no
    longer contain the keys `carName` or `kms_driven` that the filter checks for.

1.3 WHEN both API and XHR strategies fail and the `__NEXT_DATA__` regex fallback runs
    THEN the system returns 0 listings because the JSON path
    `props.pageProps.carList / cars / listings` no longer exists in the embedded script tag.

1.4 WHEN a Spinny listing is successfully parsed THEN the system stores an incorrect price
    because the raw price field is no longer a plain integer in rupees (e.g. `649000`) but
    uses a different key name, unit, or nested structure that `_parse_price()` does not
    handle correctly.

1.5 WHEN a Spinny listing is successfully parsed THEN the system stores an incorrect km
    value because the odometer field key (currently tried: `kms_driven`, `km_driven`,
    `odometer`) does not match the actual key present in the current API/JSON response.

1.6 WHEN a CarWale listing card is parsed THEN the system stores an incorrect or missing
    price because the CSS selector chain
    `[class*='price'], [class*='Price'], [class*='amount'], [class*='Amount']` no longer
    matches the current live HTML class names.

1.7 WHEN a CarWale listing card is parsed THEN the system stores an incorrect km or fuel
    value because the subtitle element selector
    `p, [class*='subtitle'], [class*='specs'], [class*='detail'], [class*='info']`
    matches a different element than the spec line containing `km | fuel | location`.

1.8 WHEN the CarWale regex fallback runs THEN the system stores incorrect km values
    because the regex `([\d,]+)\s*km\b` matches km figures from unrelated parts of the
    HTML (e.g. distance-to-dealer text) before the listing-specific km figures.

---

### Expected Behavior (Correct)

2.1 WHEN `scrape_spinny()` is called THEN the system SHALL discover the current working
    Spinny API endpoint (or equivalent data source) and return at least 1 listing per
    page for Chennai used cars.

2.2 WHEN the Spinny direct API fails THEN the system SHALL successfully intercept XHR
    responses during browser navigation by matching on the actual current network request
    URL pattern and JSON key names present in the live site.

2.3 WHEN both API and XHR strategies fail THEN the system SHALL extract listings from
    `__NEXT_DATA__` by navigating the correct current JSON path within the embedded
    script tag.

2.4 WHEN a Spinny listing is parsed THEN the system SHALL store a price in the range
    1.0–200.0 lakhs by correctly identifying the price field name and unit in the current
    API/JSON response and applying `_parse_price()` accordingly.

2.5 WHEN a Spinny listing is parsed THEN the system SHALL store a km value greater than 0
    by correctly identifying the odometer field name in the current API/JSON response.

2.6 WHEN a CarWale listing card is parsed THEN the system SHALL store a price in the range
    1.0–200.0 lakhs by using CSS selectors that match the current live HTML class names
    for the price element.

2.7 WHEN a CarWale listing card is parsed THEN the system SHALL store the correct km and
    fuel values by using a selector that uniquely targets the spec line
    (`km | fuel | location`) within each card.

2.8 WHEN the CarWale regex fallback runs THEN the system SHALL store km values that
    correspond to the listing's odometer reading by anchoring the km regex to the
    listing-card context rather than the full page HTML.

---

### Unchanged Behavior (Regression Prevention)

3.1 WHEN `scrape_carwale()` is called and the current CSS selectors match live cards
    THEN the system SHALL CONTINUE TO return a list of dicts each containing `title`,
    `price`, `km`, `year`, `fuel_type`, `link`, `source`, and `scraped_at`.

3.2 WHEN `_parse_price()` receives a string in the format `"Rs. 64 Lakh"` or
    `"Rs. 1.95 Crore"` THEN the system SHALL CONTINUE TO return the correct float value
    in lakhs (64.0 and 195.0 respectively).

3.3 WHEN `_parse_price()` receives a raw integer string representing rupees greater than
    10 000 (e.g. `"649000"`) THEN the system SHALL CONTINUE TO convert it to lakhs by
    dividing by 100 000 (returning 6.49).

3.4 WHEN `_parse_year()` receives a title string containing a 4-digit year in the range
    2000–2026 THEN the system SHALL CONTINUE TO extract and return that year as an int.

3.5 WHEN `_parse_fuel()` receives a text string containing `"Petrol"`, `"Diesel"`,
    `"CNG"`, `"Electric"`, or `"Hybrid"` THEN the system SHALL CONTINUE TO return the
    correct normalised fuel-type string.

3.6 WHEN `scrape_all()` is called THEN the system SHALL CONTINUE TO run both
    `scrape_carwale()` and `scrape_spinny()` sequentially and return their combined
    results as a single list.

3.7 WHEN a scraper encounters a network timeout or unexpected exception on one page THEN
    the system SHALL CONTINUE TO retry up to `MAX_RETRIES` times before moving on,
    without crashing the overall pipeline.

3.8 WHEN `scrape_all()` returns an empty list THEN `app.py` SHALL CONTINUE TO fall back
    to historical data from `market_store.py` without raising an unhandled exception.

---

## Bug Condition Pseudocode

### Bug Condition Function

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type ScraperInvocation
         (X.source ∈ {"Spinny", "CarWale"},
          X.page_html = rendered HTML / API JSON at invocation time)
  OUTPUT: boolean

  // Spinny: all three strategies return 0 results
  IF X.source = "Spinny" THEN
    api_ok    ← HTTP_GET(SPINNY_API + params).status = 200
                AND response contains recognisable car records
    xhr_ok    ← browser navigation captures ≥1 JSON response
                containing current car-listing keys
    next_ok   ← __NEXT_DATA__ JSON path yields ≥1 car record
    RETURN NOT (api_ok OR xhr_ok OR next_ok)
  END IF

  // CarWale or Spinny: parsed numeric field is outside plausible range
  IF X.parsed_price < 1.0 OR X.parsed_price > 200.0 THEN
    RETURN true
  END IF
  IF X.parsed_km < 0 OR X.parsed_km > 500000 THEN
    RETURN true
  END IF
  IF X.parsed_year < 2000 OR X.parsed_year > CURRENT_YEAR THEN
    RETURN true
  END IF

  RETURN false
END FUNCTION
```

### Fix-Checking Property

```pascal
// Property: Fix Checking — Spinny returns results
FOR ALL X WHERE isBugCondition(X) AND X.source = "Spinny" DO
  results ← scrape_spinny'(max_pages=1)
  ASSERT length(results) > 0
  FOR EACH r IN results DO
    ASSERT 1.0 ≤ r.price ≤ 200.0
    ASSERT r.km > 0
    ASSERT 2000 ≤ r.year ≤ CURRENT_YEAR
  END FOR
END FOR

// Property: Fix Checking — CarWale values are plausible
FOR ALL X WHERE isBugCondition(X) AND X.source = "CarWale" DO
  results ← scrape_carwale'(max_pages=1)
  FOR EACH r IN results DO
    ASSERT 1.0 ≤ r.price ≤ 200.0
    ASSERT r.km ≥ 0
    ASSERT 2000 ≤ r.year ≤ CURRENT_YEAR
  END FOR
END FOR
```

### Preservation Property

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  // Parser functions must remain backward-compatible
  ASSERT _parse_price'("Rs. 64 Lakh")   = _parse_price("Rs. 64 Lakh")   // = 64.0
  ASSERT _parse_price'("Rs. 1.95 Crore") = _parse_price("Rs. 1.95 Crore") // = 195.0
  ASSERT _parse_price'("649000")         = _parse_price("649000")         // = 6.49
  ASSERT _parse_year'("2023 BMW iX")     = _parse_year("2023 BMW iX")     // = 2023
  ASSERT _parse_fuel'("Diesel")          = _parse_fuel("Diesel")          // = "Diesel"
  // scrape_all contract unchanged
  ASSERT type(scrape_all'()) = List[Dict]
  ASSERT scrape_all'() contains records with keys:
         {title, price, km, year, fuel_type, link, source, scraped_at}
END FOR
```
