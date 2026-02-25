# Input Validation Implementation Plan

## Overview
Implement comprehensive input validation across all Flask routes to prevent invalid inputs, improve error handling, and enhance security.

## Current State Analysis

### Existing Validation (Minimal)
1. **Pagination**: Page clamping between 1 and total_pages (in all library routes)
2. **Integer coercion**: `_coerce_int()` helper in daterange routes with basic error handling
3. **Sort parameter**: Only album detail route validates `sort` against allowed values
4. **Date parsing**: Uses `date.fromisoformat()` but errors are not caught - can crash with invalid dates

### Identified Vulnerabilities
1. **No date format validation** - Invalid date strings cause unhandled exceptions
2. **No integer bounds checking** - Page numbers, limits not bounded
3. **No string sanitization** - Artist/album/track names not validated for length/characters
4. **No rangetype validation** - Only 3 valid values but any string accepted
5. **No sort_by/sort_order validation** - SQL could receive unexpected values
6. **No limit validation** - API endpoints accept arbitrary limits

---

## Implementation Plan

### Step 1: Create Validation Utility Module
**File**: `app/utils/validators.py`

Create a centralized validation module with:

1. **Date validators**
   - `validate_iso_date(date_string: str | None) -> date | None`
   - Validates YYYY-MM-DD format with regex before parsing
   - Returns None for empty/None, raises ValueError for invalid format

2. **Integer validators**
   - `validate_int(value: str | None, min_val: int = None, max_val: int = None, default: int = None) -> int | None`
   - Safe conversion with bounds checking
   - Returns default for invalid/None inputs

3. **String validators**
   - `validate_string(value: str | None, max_length: int = 500, allowed_chars: str = None) -> str | None`
   - Length checking
   - Optional character whitelist validation

4. **Enum validators**
   - `validate_enum(value: str, allowed_values: list[str], default: str) -> str`
   - Validates against allowed list, returns default for invalid/None

5. **Custom exception class**
   - `class ValidationError(Exception)`
   - Used for validation failures

### Step 2: Create Date Range Validation Wrapper
**File**: `app/utils/range.py` (modify)

Add new function `compute_range_validated()`:
- Wraps `compute_range()` with proper validation
- Catches `ValueError` from date parsing and raises `ValidationError`
- Validates `rangetype` against allowed values: `["1day", "1month", "year"]`

### Step 3: Update All Route Files

For each blueprint, import and use validators:

1. **scrobbles/routes.py**
   - Validate `page` is positive integer
   - Use `compute_range_validated()` with error handling

2. **artists/routes.py**
   - Validate `page`, `sort_by`, `sort_order`
   - Use `compute_range_validated()`
   - Validate `artist_name` path parameter (length, no path traversal)

3. **albums/routes.py**
   - Validate `page`, `sort`
   - Use `compute_range_validated()`
   - Validate path parameters

4. **tracks/routes.py**
   - Validate `page`
   - Use `compute_range_validated()`
   - Validate path parameters

5. **trackgaps/routes.py**
   - Validate `page`
   - Use `compute_range_validated()`

6. **daterange/routes.py**
   - Validate `year`, `month`, `day`, `limit`
   - Add bounds: year (1900-2100), month (1-12), day (1-31), limit (1-500)
   - Validate date format for `from`/`to`

### Step 4: Global Error Handler
**File**: `app/__init__.py` (modify)

Add handler for `ValidationError`:
- Returns 400 Bad Request with clear error message
- Logs validation failures

### Step 5: Validation Constants File
**File**: `app/utils/constants.py` (new)

Define validation constants:
```python
# Pagination
MAX_PER_PAGE = 50
MIN_PAGE = 1

# Date ranges
MIN_YEAR = 1900
MAX_YEAR = 2100

# String lengths
MAX_ARTIST_NAME_LENGTH = 500
MAX_ALBUM_NAME_LENGTH = 500
MAX_TRACK_NAME_LENGTH = 500

# Enum values
ALLOWED_RANGETYPES = ["1day", "1month", "year"]
ALLOWED_SORT_BY = ["name", "plays"]
ALLOWED_SORT_ORDER = ["asc", "desc"]
ALLOWED_ALBUM_SORT = ["tracklist", "plays"]

# API limits
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
```

---

## File Changes Summary

### New Files
1. `app/utils/validators.py` - Validation functions
2. `app/utils/constants.py` - Validation constants

### Modified Files
1. `app/utils/range.py` - Add `compute_range_validated()`
2. `app/__init__.py` - Add ValidationError handler
3. `app/scrobbles/routes.py` - Add validation
4. `app/artists/routes.py` - Add validation
5. `app/albums/routes.py` - Add validation
6. `app/tracks/routes.py` - Add validation
7. `app/trackgaps/routes.py` - Add validation
8. `app/daterange/routes.py` - Add validation

---

## Testing Strategy

1. **Test invalid date formats**: `2024-13-01`, `not-a-date`, `2024/01/01`
2. **Test invalid integers**: negative pages, non-numeric values
3. **Test out-of-bounds values**: year=3000, page=999999
4. **Test invalid enum values**: rangetype="invalid", sort_order="invalid"
5. **Test path traversal**: artist_name="../../etc/passwd"
6. **Test extremely long strings**: 10000 character names

---

## Security Improvements

1. **Prevent DoS** - Limit values prevent resource exhaustion
2. **Prevent crashes** - Graceful error handling for invalid inputs
3. **Prevent path traversal** - Validate path parameters don't contain `..` or `/`
4. **Prevent SQL issues** - Ensure parameters match expected patterns before queries

---

## Backward Compatibility

- Empty/None values for optional parameters continue to work (defaults applied)
- Valid inputs work exactly as before
- Only invalid inputs now return proper 400 errors instead of crashing
