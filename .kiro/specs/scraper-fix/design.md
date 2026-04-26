# Scraper Fix Bugfix Design

## Overview

Two bugs in `scraper.py` prevent the Chennai Used Car AI Analyzer from returning useful
data. First, `scrape_spinny()` returns 0 results because the three-strategy chain (direct
REST API → browser XHR interception → `__NEXT_DATA__` regex) all fail against the current
live site — the API endpoint path, required headers/cookies, and/or JSON response structure
have changed since the scraper was written. Second, when listings are returned from either
source, the parsed numeric values (price, km, year) are wrong because the CSS selectors
for CarWale and the JSON field names for Spinny no longer match the current live site.

The fix strategy is:
1. **Discover** the current Spinny data-delivery mechanism (API path, auth requirements,
   response shape) by inspecting live network traffic.
2. **Update** all three Spinny strategies to match the discovered structure.
3. **Update** CarWale CSS selectors and the regex fallback to match the current live HTML.
4. **Preserve** all parser helper functions (`_parse_price`, `_parse_km`, `_parse_year`,
   `_parse_fuel`) and the overall `scrape_all()` contract unchanged.

---

## Glossary

- **Bug_Condition (C)**: The condition that triggers either bug — Spinny returning 0
  listings, or any scraper returning a listing with a price outside 1–200 L, km < 0 or
  > 500 000, or year outside 2000–current year.
- **Property (P)**: The desired behavior when the bug condition holds — Spinny returns ≥ 1
  listing per page with plausible numeric fields; CarWale listings have plausible numeric
  fields.
- **Preservation**: The existing behavior that must remain unchanged — parser helper
  functions, the `scrape_all()` return contract, retry logic, and the app-level fallback
  to historical data.
- **`scrape_spinny()`**: Entry point in `scraper.py` that orchestrates the three Spinny
  strategies and returns a `List[Dict]`.
- **`_scrape_carwale_page()`**: Function in `scraper.py` that navigates to a CarWale URL
  and extracts listing cards using CSS selectors, falling back to regex.
- **`_fetch_spinny_api()`**: Function in `scraper.py` that calls the Spinny REST API
  directly via `page.request.get()`.
- **`_scrape_spinny_browser()`**: Function in `scraper.py` that loads the Spinny SPA and
  intercepts XHR responses.
- **`_fallback_parse_spinny()`**: Function in `scraper.py` that extracts data from
  `__NEXT_DATA__` or raw JSON patterns in the page source.
- **`_fallback_parse_carwale()`**: Function in `scraper.py` that extracts data from
  CarWale page HTML using regex patterns.
- **`isBugCondition(X)`**: Pseudocode predicate (defined below) that returns `true` when
  an invocation exhibits either bug.
- **`expectedBehavior(result)`**: Pseudocode predicate that returns `true` when a result
  list satisfies the correctness criteria.

---

## Bug Details

### Bug Condition

The bug manifests in two related ways:

1. **Spinny zero-results**: `scrape_spinny()` returns an empty list because all three
   data-extraction strategies fail against the current live site.
2. **Incorrect numeric fields**: A listing returned by either scraper has a price, km, or
   year value that falls outside the plausible range for a used car in Chennai.

**Formal Specification:**

```
FUNCTION isBugCondition(X)
  INPUT: X of type ScraperInvocation
         (X.source ∈ {"Spinny", "CarWale"},
          X.page_html = rendered HTML / API JSON at invocation time,
          X.results   = list returned by the scraper function)
  OUTPUT: boolean

  // Bug 1: Spinny returns no listings at all
  IF X.source = "Spinny" AND length(X.results) = 0 THEN
    RETURN true
  END IF

  // Bug 2: Any listing has an implausible numeric field
  FOR EACH r IN X.results DO
    IF r.price IS NULL OR r.price < 1.0 OR r.price > 200.0 THEN
      RETURN true
    END IF
    IF r.km IS NOT NULL AND (r.km < 0 OR r.km > 500000) THEN
      RETURN true
    END IF
    IF r.year IS NOT NULL AND (r.year < 2000 OR r.year > CURRENT_YEAR) THEN
      RETURN true
    END IF
  END FOR

  RETURN false
END FUNCTION
```

### Examples

- **Spinny API endpoint changed**: `GET /api/v2/car_listing/?city=chennai&page=1` returns
  HTTP 404 or `{"detail": "Not found"}` → `_fetch_spinny_api()` returns `[]` → all three
  strategies return `[]` → `scrape_spinny()` returns `[]`. Bug condition holds.

- **Spinny JSON key renamed**: API returns `{"listings": [...]}` instead of
  `{"results": [...]}` → `data.get("results") or data.get("data")` both return `None` →
  `cars = []` → 0 listings parsed. Bug condition holds.

- **Spinny price field changed**: Car record has `"price": {"amount": 649000, "currency": "INR"}`
  instead of `"price": 649000` → `_parse_price(str({"amount": 649000, ...}))` returns
  `None` → listing dropped. Bug condition holds.

- **CarWale price selector stale**: Current HTML uses `class="sc-price"` but selector
  `[class*='price']` no longer matches due to CSS module hashing → `price_raw = ""` →
  regex fallback may pick up a wrong number → price outside 1–200 L. Bug condition holds.

- **CarWale km selector wrong element**: `[class*='subtitle']` matches the car model
  subtitle ("BMW 3 Series") instead of the spec line ("21,321 km | Petrol | Chennai") →
  `parts[0]` is a model name → `_parse_km("BMW 3 Series")` returns `None`. Bug condition
  holds (km is `None` / 0).

---

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**

- `_parse_price("Rs. 64 Lakh")` must continue to return `64.0`.
- `_parse_price("Rs. 1.95 Crore")` must continue to return `195.0`.
- `_parse_price("649000")` must continue to return `6.49`.
- `_parse_year("2023 BMW iX xDrive 40")` must continue to return `2023`.
- `_parse_fuel("Diesel")` must continue to return `"Diesel"`.
- `_parse_km("21,321 km")` must continue to return `21321.0`.
- `scrape_all()` must continue to return a `List[Dict]` where each dict contains the keys
  `title`, `price`, `km`, `year`, `fuel_type`, `link`, `source`, `scraped_at`.
- `scrape_carwale()` must continue to work when its CSS selectors match live cards.
- Retry logic (`MAX_RETRIES = 3`) must continue to apply to all network operations.
- `app.py` must continue to fall back to historical data when `scrape_all()` returns `[]`.

**Scope:**

All inputs that do NOT involve the changed Spinny API/JSON structure or the changed
CarWale HTML selectors should be completely unaffected by this fix. This includes:

- The four parser helper functions (`_parse_price`, `_parse_km`, `_parse_year`,
  `_parse_fuel`) — their logic must not change.
- The `scrape_all()` orchestration function — its signature and return type must not change.
- The retry/timeout infrastructure (`MAX_RETRIES`, `TIMEOUT_MS`).
- The `app.py` pipeline — no changes required there.

---

## Hypothesized Root Cause

Based on the bug description and code analysis, the most likely issues are:

1. **Spinny API endpoint or version changed**: The path `/api/v2/car_listing/` may have
   moved to `/api/v3/`, `/api/cars/`, or a completely different path. The `city` query
   parameter may now be a city ID integer rather than the string `"chennai"`.

2. **Spinny API requires authentication**: The current site may require a CSRF token,
   session cookie, or `Authorization` header that the headless browser does not supply
   when making direct `page.request.get()` calls. The API returns 401/403 or an empty
   result set without these credentials.

3. **Spinny JSON response structure changed**: The top-level key may have changed from
   `results` / `data` to something else (e.g. `cars`, `listings`, `items`). Nested car
   records may use different field names — e.g. `name` instead of `carName`, `price_inr`
   instead of `price`, `mileage` instead of `kms_driven`, `registration_year` instead of
   `make_year`, `url_slug` instead of `car_slug`.

4. **Spinny XHR interception filter too narrow**: The `on_response` handler checks for
   `"carName" in text or "kms_driven" in text`. If these keys have been renamed, no
   responses are captured even though the browser successfully loads car data.

5. **Spinny `__NEXT_DATA__` path changed**: The JSON path
   `props.pageProps.carList / cars / listings` may no longer exist. Spinny may have
   migrated to a different data-fetching pattern (e.g. React Query, SWR, or a separate
   hydration endpoint) that does not embed car data in `__NEXT_DATA__` at all.

6. **CarWale CSS class names hashed or renamed**: CarWale may use CSS Modules or a design
   system that generates hashed class names (e.g. `sc-bdXxxt`, `hJtFfQ`). The
   substring-match selectors `[class*='price']`, `[class*='subtitle']` etc. may no longer
   match any element, or may match the wrong element.

7. **CarWale HTML structure changed**: The listing card structure may have changed from
   `<li>` cards to `<div>` cards, or the price/spec elements may now be in a different
   nesting level, making the current selector chain ineffective.

---

## Correctness Properties

Property 1: Bug Condition — Spinny Returns Plausible Listings

_For any_ invocation where the bug condition holds for Spinny (i.e., `scrape_spinny()`
currently returns 0 results or implausible values), the fixed `scrape_spinny()` function
SHALL return a non-empty list where every listing has `price` in [1.0, 200.0] lakhs,
`km` ≥ 0 (or `None`), and `year` in [2000, current year] (or `None`).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Bug Condition — CarWale Returns Plausible Values

_For any_ invocation where the bug condition holds for CarWale (i.e., parsed price, km,
or year is outside the plausible range), the fixed `_scrape_carwale_page()` function
SHALL return listings where `price` is in [1.0, 200.0] lakhs, `km` ≥ 0 (or `None`), and
`year` is in [2000, current year] (or `None`).

**Validates: Requirements 2.6, 2.7, 2.8**

Property 3: Preservation — Parser Helper Functions Unchanged

_For any_ input string where the bug condition does NOT hold (i.e., the input is a
well-formed price/km/year/fuel string that the original parsers already handle correctly),
the fixed parser functions SHALL produce exactly the same output as the original functions.

**Validates: Requirements 3.2, 3.3, 3.4, 3.5**

Property 4: Preservation — `scrape_all()` Contract Unchanged

_For any_ invocation of `scrape_all()` after the fix, the function SHALL return a
`List[Dict]` where each dict contains exactly the keys `title`, `price`, `km`, `year`,
`fuel_type`, `link`, `source`, `scraped_at` — identical contract to the original.

**Validates: Requirements 3.1, 3.6, 3.7, 3.8**

---

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `scraper.py`

#### Change 1: Discover and update the Spinny API endpoint and parameters

**Function**: `_fetch_spinny_api()` and module-level constants `SPINNY_API`, `SPINNY_PARAMS`

**Specific Changes**:
- Use Playwright to load `https://www.spinny.com/used-cars-in-chennai/s/` and log all
  network requests to identify the current API URL, required headers, and query parameters.
- Update `SPINNY_API` and `SPINNY_PARAMS` to match the discovered endpoint.
- If the API requires a CSRF token or session cookie, extract it from the browser context
  after page load and pass it in the `page.request.get()` headers.

#### Change 2: Update Spinny JSON field name mapping

**Functions**: `_fetch_spinny_api()`, `_scrape_spinny_browser()`, `_fallback_parse_spinny()`

**Specific Changes**:
- Inspect the actual JSON response to identify the current top-level key (`results`,
  `data`, `cars`, `listings`, `items`, etc.) and update all three functions accordingly.
- Build a field-name resolution map for car records, trying multiple candidate keys in
  priority order for each field:
  - Title: `carName`, `car_name`, `name`, `title`, `fullName`
  - Price: `price`, `selling_price`, `sp`, `price_inr`, `amount`
  - KM: `kms_driven`, `km_driven`, `odometer`, `mileage`, `kilometers`
  - Year: `make_year`, `year`, `registration_year`, `manufacturing_year`
  - Fuel: `fuel_type`, `fuel`, `fuelType`
  - Slug: `car_slug`, `slug`, `url_slug`, `carSlug`
- Update the XHR interception filter in `_scrape_spinny_browser()` to match on the
  discovered key names rather than the hardcoded `"carName"` / `"kms_driven"` strings.

#### Change 3: Update Spinny `__NEXT_DATA__` JSON path

**Function**: `_fallback_parse_spinny()`

**Specific Changes**:
- Inspect the actual `__NEXT_DATA__` JSON (if present) to find the correct path to the
  car list. Try a breadth-first search for any list value whose items are dicts containing
  a price-like key, rather than hardcoding `carList / cars / listings`.
- If `__NEXT_DATA__` no longer contains car data, update the raw JSON pattern fallback to
  match the current key names discovered in Change 2.

#### Change 4: Update CarWale CSS selectors

**Function**: `_scrape_carwale_page()`

**Specific Changes**:
- Inspect the current live CarWale HTML to identify the actual class names or data
  attributes used for price elements and spec-line elements.
- Update `card_selectors` to include any new card container patterns.
- Update the price element selector to match the current class names (may need to use
  `data-*` attributes or a more structural selector like `span:has-text("Lakh")`).
- Update the subtitle/spec-line selector to uniquely target the element containing
  `km | fuel | location` — consider using `:has-text("km")` or a positional selector
  relative to the price element.

#### Change 5: Anchor CarWale regex fallback to card context

**Function**: `_fallback_parse_carwale()`

**Specific Changes**:
- Instead of running regexes against the full page HTML, first split the HTML into
  per-card chunks (e.g. by splitting on `<li` or `<article`) and run each regex within
  its card chunk. This prevents km figures from distance-to-dealer text from being
  matched before listing-specific km figures.
- Update the title, price, km, and fuel regexes to match the current HTML patterns if
  they have changed.

---

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that
demonstrate the bugs on the unfixed code, then verify the fix works correctly and
preserves existing behavior.

Because the bugs are caused by live-site changes, the exploratory phase involves both
automated tests against mock/recorded responses and manual inspection of live network
traffic. The fix-checking phase uses unit tests against recorded real responses. The
preservation phase uses property-based tests to verify parser helper functions remain
backward-compatible across a wide range of inputs.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bugs BEFORE implementing the fix.
Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that replay the current scraper logic against mock responses
that simulate the changed site structure, and assert that the bug condition holds (i.e.,
0 results or implausible values are returned). Run these tests on the UNFIXED code to
observe failures and understand the root cause.

**Test Cases**:

1. **Spinny API 404 Test**: Mock `page.request.get()` to return HTTP 404 for the current
   `SPINNY_API` URL. Assert that `_fetch_spinny_api()` returns `[]`. (Will pass on
   unfixed code — confirms the API path is broken.)

2. **Spinny JSON key mismatch Test**: Mock the API to return
   `{"listings": [{"name": "2022 Maruti Swift", "price_inr": 550000, ...}]}`.
   Assert that `_fetch_spinny_api()` returns `[]` because `data.get("results")` and
   `data.get("data")` both return `None`. (Will pass on unfixed code — confirms key
   mismatch.)

3. **Spinny XHR filter miss Test**: Simulate a browser response containing
   `{"cars": [{"name": "...", "price_inr": 550000}]}` (no `carName` or `kms_driven`
   keys). Assert that `_scrape_spinny_browser()` captures 0 responses. (Will pass on
   unfixed code — confirms filter is too narrow.)

4. **Spinny `__NEXT_DATA__` wrong path Test**: Mock page HTML with `__NEXT_DATA__`
   containing `{"props": {"pageProps": {"initialData": {"cars": [...]}}}}` (not
   `carList`). Assert that `_fallback_parse_spinny()` returns `[]`. (Will pass on
   unfixed code — confirms path mismatch.)

5. **CarWale price selector miss Test**: Mock a card HTML where the price element has
   class `sc-price` (no substring `price` in a CSS-module-hashed name). Assert that
   `price_raw` is empty and the listing is dropped. (Will pass on unfixed code —
   confirms selector staleness.)

6. **CarWale km wrong element Test**: Mock a card HTML where `[class*='subtitle']`
   matches the model name element before the spec line. Assert that `km` is `None`.
   (Will pass on unfixed code — confirms selector ambiguity.)

**Expected Counterexamples**:
- `_fetch_spinny_api()` returns `[]` for any response not matching `results`/`data` keys.
- `_scrape_spinny_browser()` captures 0 responses when key names differ from
  `carName`/`kms_driven`.
- `_fallback_parse_spinny()` returns `[]` when `__NEXT_DATA__` path is wrong.
- CarWale listings have `price = None` or `km = None` when selectors don't match.

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed functions
produce the expected behavior.

**Pseudocode:**

```
FUNCTION expectedBehavior(results)
  IF length(results) = 0 THEN RETURN false END IF
  FOR EACH r IN results DO
    IF r.price IS NULL OR r.price < 1.0 OR r.price > 200.0 THEN RETURN false END IF
    IF r.km IS NOT NULL AND (r.km < 0 OR r.km > 500000) THEN RETURN false END IF
    IF r.year IS NOT NULL AND (r.year < 2000 OR r.year > CURRENT_YEAR) THEN RETURN false END IF
    IF r.title IS NULL OR length(r.title) < 5 THEN RETURN false END IF
    IF r.source NOT IN {"Spinny", "CarWale"} THEN RETURN false END IF
  END FOR
  RETURN true
END FUNCTION

FOR ALL X WHERE isBugCondition(X) DO
  result := fixedScraper(X)
  ASSERT expectedBehavior(result)
END FOR
```

**Test Cases**:

1. **Spinny API fixed response Test**: Feed the fixed `_fetch_spinny_api()` a mock
   response using the discovered JSON structure. Assert ≥ 1 listing with plausible
   price, km, year.

2. **Spinny XHR fixed interception Test**: Feed the fixed `_scrape_spinny_browser()` a
   mock XHR response using the discovered key names. Assert ≥ 1 listing captured.

3. **Spinny `__NEXT_DATA__` fixed path Test**: Feed the fixed `_fallback_parse_spinny()`
   a mock HTML with the correct `__NEXT_DATA__` path. Assert ≥ 1 listing.

4. **CarWale price selector fixed Test**: Feed the fixed `_scrape_carwale_page()` a mock
   card HTML with the updated price selector. Assert price is in [1.0, 200.0].

5. **CarWale km selector fixed Test**: Feed the fixed `_scrape_carwale_page()` a mock
   card HTML where the spec line is correctly targeted. Assert km > 0.

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed
functions produce the same result as the original functions.

**Pseudocode:**

```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT fixedParser(input) = originalParser(input)
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking of
the parser helper functions because:
- They are pure functions with well-defined input domains.
- PBT can generate thousands of price/km/year/fuel strings automatically.
- It catches edge cases (empty strings, Unicode, very large numbers) that manual tests
  miss.
- It provides strong guarantees that the parsers remain backward-compatible.

**Test Plan**: Capture the current behavior of `_parse_price`, `_parse_km`, `_parse_year`,
and `_parse_fuel` on the unfixed code as the oracle, then write property-based tests that
assert the fixed versions produce identical output.

**Test Cases**:

1. **`_parse_price` preservation**: Generate random strings in the formats
   `"Rs. N Lakh"`, `"Rs. N Crore"`, `"N"` (raw rupees), `"N.NN"` (already in lakhs).
   Assert fixed `_parse_price` returns the same value as original for all inputs.

2. **`_parse_km` preservation**: Generate random strings in the formats `"N km"`,
   `"N,NNN kms"`, `"N"`. Assert fixed `_parse_km` returns the same value as original.

3. **`_parse_year` preservation**: Generate random title strings containing 4-digit years
   in 2000–2026. Assert fixed `_parse_year` returns the same year as original.

4. **`_parse_fuel` preservation**: Generate random strings containing fuel type keywords.
   Assert fixed `_parse_fuel` returns the same fuel type as original.

5. **`scrape_all()` contract preservation**: Assert the return type is `List[Dict]` and
   each dict contains all required keys after the fix.

### Unit Tests

- Test `_fetch_spinny_api()` with mock responses for the new API structure (correct keys,
  nested price, renamed fields).
- Test `_scrape_spinny_browser()` XHR interception with mock responses using new key names.
- Test `_fallback_parse_spinny()` with mock `__NEXT_DATA__` at the correct new path.
- Test `_scrape_carwale_page()` with mock HTML using updated CSS selectors.
- Test `_fallback_parse_carwale()` with mock HTML split into per-card chunks.
- Test edge cases: empty API response, missing fields in car records, malformed JSON,
  network timeout on all retries.

### Property-Based Tests

- Generate random valid Indian price strings and verify `_parse_price` is unchanged after
  the fix (preservation of parser behavior across the full input domain).
- Generate random km strings and verify `_parse_km` is unchanged.
- Generate random title strings with embedded years and verify `_parse_year` is unchanged.
- Generate random Spinny-like JSON payloads with the new field names and verify the fixed
  scraper extracts plausible values (fix checking across many generated inputs).
- Generate random CarWale-like HTML card structures and verify the fixed scraper extracts
  plausible price and km values.

### Integration Tests

- Run `scrape_spinny(max_pages=1)` against the live Spinny site (or a recorded HAR
  fixture) and assert ≥ 1 listing with plausible values.
- Run `scrape_carwale(max_pages=1)` against the live CarWale site (or a recorded HAR
  fixture) and assert ≥ 1 listing with plausible values.
- Run `scrape_all(max_pages=1)` and assert results from both sources are present.
- Verify that `app.py` pipeline completes without exception when `scrape_all()` returns
  the fixed results.
- Verify that `app.py` pipeline falls back to historical data gracefully when
  `scrape_all()` returns `[]` (regression test for requirement 3.8).
