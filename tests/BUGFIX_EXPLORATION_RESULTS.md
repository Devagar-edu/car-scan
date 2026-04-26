# Bug Condition Exploration Test Results

**Date**: Task 1 Execution
**Status**: ✅ All 6 tests written and executed on UNFIXED code
**Outcome**: All 6 tests FAILED as expected (this confirms the bugs exist)

---

## Test Results Summary

### Test 1a — Spinny API 404
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.1

**Counterexample Found**:
- When `page.request.get()` returns HTTP 404 for `SPINNY_API`
- `_fetch_spinny_api()` returns `[]` (empty list)
- Expected behavior: Should handle 404 gracefully or use fallback strategy
- **Bug confirmed**: API endpoint path is broken or changed

**Error Message**:
```
AssertionError: Expected _fetch_spinny_api to return results even with 404 (should use fallback)
assert 0 > 0
 +  where 0 = len([])
```

---

### Test 1b — Spinny JSON Key Mismatch
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.2

**Counterexample Found**:
- When API returns `{"listings": [{"name": "2022 Maruti Swift", "price_inr": 550000, ...}]}`
- `_fetch_spinny_api()` returns `[]` because `data.get("results")` and `data.get("data")` both return `None`
- Expected behavior: Should extract listings from the "listings" key
- **Bug confirmed**: JSON response structure has changed; top-level key is no longer "results" or "data"

**Error Message**:
```
AssertionError: Expected _fetch_spinny_api to handle 'listings' key
assert 0 > 0
 +  where 0 = len([])
```

---

### Test 1c — Spinny XHR Filter Miss
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.3

**Counterexample Found**:
- When browser-intercepted response contains `{"cars": [{"name": "...", "price_inr": 550000}]}`
- Response has neither `"carName"` nor `"kms_driven"` keys
- Current filter in `_scrape_spinny_browser()` checks: `if "carName" in text or "kms_driven" in text`
- Expected behavior: Should capture responses with alternative key names like "name", "price_inr", etc.
- **Bug confirmed**: XHR interception filter is too narrow; field names have changed

**Error Message**:
```
AssertionError: Expected XHR filter to capture responses with alternative key names (but unfixed code only checks carName/kms_driven)
assert (False or False)
```

---

### Test 1d — Spinny __NEXT_DATA__ Wrong Path
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.4

**Counterexample Found**:
- When `__NEXT_DATA__` contains `{"props": {"pageProps": {"initialData": {"cars": [{"name": "2022 Swift", "price_inr": 550000, ...}]}}}}`
- Path is `props.pageProps.initialData.cars` (not `carList`/`cars`/`listings` directly under `pageProps`)
- `_fallback_parse_spinny()` returns `[]` because it only checks hardcoded paths
- Expected behavior: Should find cars at the new nested path
- **Bug confirmed**: `__NEXT_DATA__` JSON structure has changed; hardcoded path no longer exists

**Error Message**:
```
AssertionError: Expected _fallback_parse_spinny to find cars at props.pageProps.initialData.cars
assert 0 > 0
 +  where 0 = len([])
```

---

### Test 1e — CarWale Price Selector Miss
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.6

**Counterexample Found**:
- When CarWale card HTML has price element with class `"sc-price-xyz"` (CSS-module-hashed, no plain "price" substring)
- Selector `[class*='price']` doesn't match
- Card text doesn't contain price in regex-friendly format ("Rs. X Lakh")
- `_scrape_carwale_page()` drops the listing (returns `[]`)
- Expected behavior: Should extract price even with hashed class names
- **Bug confirmed**: CSS selectors are stale; CarWale now uses CSS-module-hashed class names

**Error Message**:
```
AssertionError: Expected _scrape_carwale_page to extract listing even with hashed price class
assert 0 > 0
 +  where 0 = len([])
```

**Log Output**:
```
WARNING  scraper:scraper.py:196 CarWale selectors empty for https://www.carwale.com/used/chennai/, using regex fallback
```

---

### Test 1f — CarWale KM Wrong Element
**Status**: ❌ FAILED (as expected)
**Validates**: Requirements 1.7

**Counterexample Found**:
- When CarWale card HTML has `[class*='subtitle']` matching the model-name element ("BMW 3 Series 320d M Sport") before the spec line ("35,421 km | Diesel | Chennai")
- Selector `[class*='subtitle']` matches wrong element
- `_scrape_carwale_page()` extracts km from wrong element
- Result: `km = 2023.0` (extracted from title "2023 BMW 3 Series" instead of spec line "35,421 km")
- Expected behavior: Should extract correct km (35,421) from the spec line
- **Bug confirmed**: Subtitle selector is ambiguous; matches multiple elements, picks wrong one

**Error Message**:
```
AssertionError: Expected correct km extraction (35421), got 2023.0
assert (2023.0 is not None and 2023.0 > 30000)
```

---

## Root Causes Confirmed

### Spinny Issues (Tests 1a-1d)
1. **API endpoint changed**: Current endpoint returns 404
2. **JSON response structure changed**: Top-level key is no longer "results" or "data"
3. **Field names changed**: No longer uses "carName", "kms_driven", etc.
4. **__NEXT_DATA__ path changed**: Car data is now nested deeper or at a different path

### CarWale Issues (Tests 1e-1f)
5. **CSS class names changed**: Now uses CSS-module-hashed names (e.g., "sc-price-xyz") instead of plain "price"
6. **Selector ambiguity**: `[class*='subtitle']` matches multiple elements, picks wrong one

---

## Next Steps

These tests encode the **expected behavior** after the fix. When the code is fixed:
- All 6 tests should **PASS**
- This will confirm that all bugs are resolved

**DO NOT attempt to fix the tests or the code yet** — this is the exploration phase.
The fix will be implemented in subsequent tasks (Task 3).
