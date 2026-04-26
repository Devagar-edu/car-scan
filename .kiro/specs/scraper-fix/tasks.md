# Implementation Plan

- [x] 1. Write bug condition exploration tests
  - **Property 1: Bug Condition** - Spinny Zero Results & Stale Selectors
  - **CRITICAL**: These tests MUST FAIL on unfixed code — failure confirms the bugs exist
  - **DO NOT attempt to fix the tests or the code when they fail**
  - **NOTE**: These tests encode the expected behavior — they will validate the fix when they pass after implementation
  - **GOAL**: Surface counterexamples that demonstrate each root cause
  - **Scoped PBT Approach**: Scope each property to the concrete failing case to ensure reproducibility
  - Create `tests/test_scraper_bugfix.py` with the following exploration tests:
    - **1a — Spinny API 404**: Mock `page.request.get()` to return HTTP 404 for `SPINNY_API`. Assert `_fetch_spinny_api()` returns `[]`. (Confirms API path is broken.)
    - **1b — Spinny JSON key mismatch**: Mock API to return `{"listings": [{"name": "2022 Maruti Swift", "price_inr": 550000, "mileage": 45000, "registration_year": 2022, "fuelType": "Petrol", "url_slug": "maruti-swift-abc"}]}`. Assert `_fetch_spinny_api()` returns `[]` because `data.get("results")` and `data.get("data")` both return `None`. (Confirms key mismatch.)
    - **1c — Spinny XHR filter miss**: Simulate a browser-intercepted response body containing `{"cars": [{"name": "...", "price_inr": 550000}]}` (no `carName` or `kms_driven` keys). Assert `_scrape_spinny_browser()` captures 0 responses. (Confirms filter is too narrow.)
    - **1d — Spinny `__NEXT_DATA__` wrong path**: Mock page HTML with `__NEXT_DATA__` containing `{"props": {"pageProps": {"initialData": {"cars": [{"name": "2022 Swift", "price_inr": 550000}]}}}}` (not `carList`/`cars`/`listings` under `pageProps`). Assert `_fallback_parse_spinny()` returns `[]`. (Confirms path mismatch.)
    - **1e — CarWale price selector miss**: Mock a card HTML where the price element has class `sc-price-xyz` (CSS-module-hashed, no plain `price` substring). Assert `price_raw` is empty and the listing is dropped. (Confirms selector staleness.)
    - **1f — CarWale km wrong element**: Mock a card HTML where `[class*='subtitle']` matches the model-name element before the spec line. Assert `km` is `None`. (Confirms selector ambiguity.)
  - Run all tests on UNFIXED code
  - **EXPECTED OUTCOME**: All tests FAIL (this is correct — it proves the bugs exist)
  - Document counterexamples found (e.g., `_fetch_spinny_api()` returns `[]` for `{"listings": [...]}` response)
  - Mark task complete when tests are written, run, and failures are documented
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Parser Helper Functions Backward-Compatible
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs (well-formed price/km/year/fuel strings)
  - Observe: `_parse_price("Rs. 64 Lakh")` returns `64.0` on unfixed code
  - Observe: `_parse_price("Rs. 1.95 Crore")` returns `195.0` on unfixed code
  - Observe: `_parse_price("649000")` returns `6.49` on unfixed code
  - Observe: `_parse_km("21,321 km")` returns `21321.0` on unfixed code
  - Observe: `_parse_year("2023 BMW iX xDrive 40")` returns `2023` on unfixed code
  - Observe: `_parse_fuel("Diesel")` returns `"Diesel"` on unfixed code
  - Add the following property-based tests to `tests/test_scraper_bugfix.py` using `hypothesis`:
    - **2a — `_parse_price` preservation**: Generate random strings in formats `"Rs. N Lakh"`, `"Rs. N.NN Crore"`, raw rupee integers > 10 000, and already-in-lakhs floats. Assert fixed `_parse_price` returns the same value as the original for all inputs. (From Preservation Requirements in design.)
    - **2b — `_parse_km` preservation**: Generate random strings in formats `"N km"`, `"N,NNN kms"`, plain integer strings. Assert fixed `_parse_km` returns the same value as the original.
    - **2c — `_parse_year` preservation**: Generate random title strings containing 4-digit years in 2000–2026 embedded in car-name-like text. Assert fixed `_parse_year` returns the same year as the original.
    - **2d — `_parse_fuel` preservation**: Generate random strings containing fuel-type keywords (`Petrol`, `Diesel`, `CNG`, `Electric`, `Hybrid`, `LPG`). Assert fixed `_parse_fuel` returns the same fuel type as the original.
    - **2e — `scrape_all()` contract preservation**: Assert the return type is `List[Dict]` and each dict contains all required keys: `title`, `price`, `km`, `year`, `fuel_type`, `link`, `source`, `scraped_at`.
  - Run all preservation tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6_

- [-] 3. Fix scraper.py — all 5 targeted changes

  - [ ] 3.1 Discover and update the Spinny API endpoint and parameters
    - Load `https://www.spinny.com/used-cars-in-chennai/s/` in a headed Playwright session and log all network requests to identify the current API URL, required headers, and query parameters
    - Update the `SPINNY_API` constant to the discovered endpoint path (e.g. `/api/v3/`, `/api/cars/`, or equivalent)
    - Update the `SPINNY_PARAMS` constant to match the discovered query-parameter schema (city may now be an integer ID rather than the string `"chennai"`)
    - If the API requires a CSRF token or session cookie, extract it from the browser context after page load and pass it in the `page.request.get()` headers inside `_fetch_spinny_api()`
    - _Bug_Condition: isBugCondition(X) where X.source = "Spinny" AND length(X.results) = 0 due to HTTP 404 / 401 / 403 on SPINNY_API_
    - _Expected_Behavior: expectedBehavior(results) — length(results) > 0, all prices in [1.0, 200.0] L_
    - _Preservation: SPINNY_API and SPINNY_PARAMS are module-level constants; changing them does not affect parser helper functions or scrape_all() contract_
    - _Requirements: 2.1, 2.2_

  - [~] 3.2 Update Spinny JSON field-name mapping across all three strategies
    - Inspect the actual JSON response to identify the current top-level key and update `_fetch_spinny_api()`, `_scrape_spinny_browser()`, and `_fallback_parse_spinny()` to use it
    - Build a multi-candidate field-name resolution for each car record field, trying keys in priority order:
      - Title: `carName`, `car_name`, `name`, `title`, `fullName`
      - Price: `price`, `selling_price`, `sp`, `price_inr`, `amount`
      - KM: `kms_driven`, `km_driven`, `odometer`, `mileage`, `kilometers`
      - Year: `make_year`, `year`, `registration_year`, `manufacturing_year`
      - Fuel: `fuel_type`, `fuel`, `fuelType`
      - Slug: `car_slug`, `slug`, `url_slug`, `carSlug`
    - Update the XHR interception filter in `_scrape_spinny_browser()` `on_response` handler to match on the discovered key names rather than the hardcoded `"carName"` / `"kms_driven"` strings
    - _Bug_Condition: isBugCondition(X) where data.get("results") and data.get("data") both return None, or car record keys don't match_
    - _Expected_Behavior: expectedBehavior(results) — each listing has plausible price, km, year extracted from the correct fields_
    - _Preservation: Multi-candidate fallback means existing key names remain tried first; parser helper functions are not touched_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [~] 3.3 Fix `__NEXT_DATA__` path in `_fallback_parse_spinny` with breadth-first search
    - Replace the hardcoded path `props.pageProps.carList / cars / listings` with a breadth-first search over the parsed `__NEXT_DATA__` JSON tree
    - The BFS should look for any list value whose items are dicts containing a price-like key (any of the price candidates from Change 2)
    - If `__NEXT_DATA__` no longer contains car data at all, fall through to the existing raw JSON pattern fallback (updated to use the new key names from Change 2)
    - _Bug_Condition: isBugCondition(X) where __NEXT_DATA__ path props.pageProps.carList/cars/listings does not exist_
    - _Expected_Behavior: expectedBehavior(results) — BFS finds the car list regardless of nesting depth or key name_
    - _Preservation: Fallback function signature and return type unchanged; parser helpers not touched_
    - _Requirements: 2.3, 2.4, 2.5_

  - [~] 3.4 Update CarWale CSS selectors in `_scrape_carwale_page`
    - Inspect the current live CarWale HTML to identify the actual class names or data attributes for price elements and spec-line elements
    - Update `card_selectors` list to include any new card container patterns (e.g. `div[class*='cardContainer']`, `div[data-testid*='listing']`)
    - Update the price element selector to match current class names; consider using `span:has-text("Lakh")` or `span:has-text("Crore")` as a structural fallback
    - Update the subtitle/spec-line selector to uniquely target the element containing `km | fuel | location`; consider `:has-text("km")` or a positional selector relative to the price element
    - _Bug_Condition: isBugCondition(X) where [class*='price'] and [class*='subtitle'] selectors match no element or the wrong element_
    - _Expected_Behavior: expectedBehavior(results) — price in [1.0, 200.0] L, km > 0 for CarWale listings_
    - _Preservation: Selector changes are local to _scrape_carwale_page(); parser helpers and scrape_all() contract unchanged_
    - _Requirements: 2.6, 2.7_

  - [~] 3.5 Anchor CarWale regex fallback in `_fallback_parse_carwale` to per-card HTML chunks
    - Split the full page HTML into per-card chunks before running regexes (split on `<li`, `<article`, or the discovered card container tag)
    - Run the title, price, km, and fuel regexes within each card chunk independently so km figures from distance-to-dealer text cannot be matched before listing-specific km figures
    - Update the title, price, km, and fuel regexes to match current HTML patterns if they have changed (e.g. updated `href` pattern for links)
    - _Bug_Condition: isBugCondition(X) where km regex matches distance-to-dealer text before listing km in full-page HTML_
    - _Expected_Behavior: expectedBehavior(results) — km values correspond to odometer readings, not dealer distances_
    - _Preservation: Function signature and return type unchanged; per-card chunking is an internal implementation detail_
    - _Requirements: 2.8_

  - [~] 3.6 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Spinny Zero Results & Stale Selectors
    - **IMPORTANT**: Re-run the SAME tests from task 1 — do NOT write new tests
    - The tests from task 1 encode the expected behavior; when they pass, the bugs are fixed
    - Run all six exploration tests (1a–1f) from step 1
    - **EXPECTED OUTCOME**: All tests PASS (confirms all 5 fixes are effective)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8_

  - [~] 3.7 Verify preservation tests still pass
    - **Property 2: Preservation** - Parser Helper Functions Backward-Compatible
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run all five preservation property tests (2a–2e) from step 2
    - **EXPECTED OUTCOME**: All tests PASS (confirms no regressions in parser helpers or scrape_all() contract)
    - Confirm all hypothesis-generated inputs still produce identical output before and after the fix

- [~] 4. Checkpoint — Ensure all tests pass
  - Run the full test suite: `python -m pytest tests/test_scraper_bugfix.py -v`
  - All exploration tests (1a–1f) must pass — confirms bugs are fixed
  - All preservation property tests (2a–2e) must pass — confirms no regressions
  - If any test fails, diagnose the root cause before patching; do not suppress failures
  - Ensure all tests pass; ask the user if questions arise
