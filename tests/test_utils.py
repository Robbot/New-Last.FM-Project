"""Tests for utility functions."""

import pytest


@pytest.mark.unit
class TestRangeCalculations:
    """Tests for date range calculation utilities."""

    def test_compute_range_validated_with_no_args(self):
        """Test range calculation with no arguments."""
        from app.utils.range import compute_range_validated
        start, end = compute_range_validated(None, None, None)
        # Returns None when no range is provided
        assert start is None or start == ""
        assert end is None or end == ""

    def test_compute_range_validated_with_dates(self):
        """Test range calculation with valid dates."""
        from app.utils.range import compute_range_validated
        start, end = compute_range_validated('2023-01-01', '2023-12-31', None)
        assert start == '2023-01-01'
        assert end == '2023-12-31'


@pytest.mark.unit
class TestValidators:
    """Tests for validation utilities."""

    def test_validate_int_with_valid_int(self):
        """Test validate_int with valid integer."""
        from app.utils.validators import validate_int
        result = validate_int('42')
        assert result == 42

    def test_validate_int_with_invalid_int(self):
        """Test validate_int with invalid integer returns default."""
        from app.utils.validators import validate_int
        result = validate_int('not-a-number', default=10)
        assert result == 10

    def test_validate_int_with_min_max(self):
        """Test validate_int with min/max constraints."""
        from app.utils.validators import validate_int
        from app.utils.validators import ValidationError
        # Function raises ValidationError for out-of-range values
        with pytest.raises(ValidationError):
            validate_int('150', min_val=0, max_val=100, default=50)
