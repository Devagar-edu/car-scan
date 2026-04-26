# Preservation Property Test Results (Task 2)

## Test Execution Date
2025-01-XX (Unfixed Code)

## Summary
All preservation property tests **PASSED** on unfixed code, confirming baseline behavior to preserve.

## Test Results

### Test 2a — `_parse_price` Preservation
**Status**: ✅ PASSED  
**Validates**: Requirements 3.2, 3.3  
**Description**: Property-based test verifying `_parse_price` returns consistent values for well-formed price strings.

**Specific Examples Verified**:
- `_parse_price("Rs. 64 Lakh")` → `64.0` ✅
- `_parse_price("Rs. 1.95 Crore")` → `195.0` ✅
- `_parse_price("649000")` → `6.49` ✅

**Property Test Coverage**:
- Format: "Rs. N Lakh" (1.0-200.0 range)
- Format: "Rs. N.NN Crore" (0.1-2.0 range)
- Raw rupee integers > 10,000 (100,000-20,000,000 range)
- Already-in-lakhs floats (1.0-200.0 range)

---

### Test 2b — `_parse_km` Preservation
**Status**: ✅ PASSED  
**Validates**: Requirements 3.2  
**Description**: Property-based test verifying `_parse_km` returns consistent values for well-formed km strings.

**Specific Examples Verified**:
- `_parse_km("21,321 km")` → `21321.0` ✅

**Property Test Coverage**:
- Format: "N km" (0-500,000 range)
- Format: "N,NNN kms" (0-500,000 range)
- Plain integer strings (0-500,000 range)

---

### Test 2c — `_parse_year` Preservation
**Status**: ✅ PASSED  
**Validates**: Requirements 3.4  
**Description**: Property-based test verifying `_parse_year` returns consistent values for title strings containing 4-digit years.

**Specific Examples Verified**:
- `_parse_year("2023 BMW iX xDrive 40")` → `2023` ✅

**Property Test Coverage**:
- Years: 2000-2026
- Prefixes: "", "Used ", "Certified "
- Suffixes: " BMW iX xDrive 40", " Maruti Swift", " Honda City", " Hyundai Creta", ""

---

### Test 2d — `_parse_fuel` Preservation
**Status**: ✅ PASSED  
**Validates**: Requirements 3.5  
**Description**: Property-based test verifying `_parse_fuel` returns consistent values for strings containing fuel-type keywords.

**Specific Examples Verified**:
- `_parse_fuel("Diesel")` → `"Diesel"` ✅

**Property Test Coverage**:
- Fuel types: Petrol, Diesel, CNG, Electric, Hybrid, LPG
- Prefixes: "", "Fuel: ", "Type: "
- Suffixes: "", " | Chennai", " | 21,321 km"

---

### Test 2e — `scrape_all()` Contract Preservation
**Status**: ✅ PASSED  
**Validates**: Requirements 3.1, 3.6  
**Description**: Integration test verifying `scrape_all()` returns a `List[Dict]` with all required keys.

**Contract Verified**:
- Return type: `List[Dict]` ✅
- Required keys in each dict: `title`, `price`, `km`, `year`, `fuel_type`, `link`, `source`, `scraped_at` ✅
- Valid source values: "CarWale" or "Spinny" ✅

**Execution Time**: 31.73 seconds

---

## Conclusion

All preservation property tests passed on unfixed code, confirming:
1. Parser helper functions (`_parse_price`, `_parse_km`, `_parse_year`, `_parse_fuel`) work correctly for well-formed inputs
2. `scrape_all()` contract is intact (returns `List[Dict]` with required keys)
3. Baseline behavior is documented and ready for preservation during fix implementation

**Next Step**: Implement the fix (Task 3+) while ensuring these tests continue to pass.
