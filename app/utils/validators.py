"""
Input validation utilities for the Last.fm scrobble statistics application.

Provides validation functions for dates, integers, strings, and enums.
Raises ValidationError for validation failures.
"""

from __future__ import annotations
import re
from datetime import date
from typing import Any
from app.utils.constants import (
    MAX_ARTIST_NAME_LENGTH,
    MAX_ALBUM_NAME_LENGTH,
    MAX_TRACK_NAME_LENGTH,
)


class ValidationError(Exception):
    """Raised when input validation fails."""
    pass


def validate_iso_date(date_string: str | None) -> date | None:
    """
    Validate and parse an ISO format date string (YYYY-MM-DD).

    Args:
        date_string: Date string in ISO format or None

    Returns:
        Parsed date object or None if date_string is None or empty

    Raises:
        ValidationError: If date_string is not in valid ISO format
    """
    if date_string is None or date_string == "":
        return None

    # First validate format with regex (YYYY-MM-DD)
    # This ensures basic format before attempting to parse
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_string):
        raise ValidationError(f"Invalid date format: '{date_string}'. Expected YYYY-MM-DD.")

    try:
        return date.fromisoformat(date_string)
    except ValueError as e:
        raise ValidationError(f"Invalid date: '{date_string}'. {str(e)}")


def validate_int(
    value: str | None,
    min_val: int | None = None,
    max_val: int | None = None,
    default: int | None = None,
) -> int | None:
    """
    Safely convert a string to an integer with optional bounds checking.

    Args:
        value: String value to convert
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)
        default: Default value to return if value is None/empty or invalid

    Returns:
        Parsed integer, default value, or None

    Raises:
        ValidationError: If value is not a valid integer or is out of bounds
    """
    if value is None or value == "":
        return default

    try:
        int_value = int(value)
    except ValueError:
        if default is not None:
            return default
        raise ValidationError(f"Invalid integer: '{value}'")

    if min_val is not None and int_value < min_val:
        raise ValidationError(f"Value {int_value} is below minimum {min_val}")

    if max_val is not None and int_value > max_val:
        raise ValidationError(f"Value {int_value} exceeds maximum {max_val}")

    return int_value


def validate_string(
    value: str | None,
    max_length: int = 500,
    allow_path_traversal: bool = False,
    strip: bool = True,
) -> str | None:
    """
    Validate a string parameter.

    Args:
        value: String value to validate
        max_length: Maximum allowed length
        allow_path_traversal: Whether to allow path traversal characters (..)
        strip: Whether to strip whitespace from the value

    Returns:
        Validated string or None if value is None/empty

    Raises:
        ValidationError: If string is too long or contains path traversal
    """
    if value is None:
        return None

    if strip:
        value = value.strip()

    if value == "":
        return None

    if len(value) > max_length:
        raise ValidationError(
            f"String exceeds maximum length of {max_length} characters"
        )

    if not allow_path_traversal:
        # Check for path traversal patterns
        if ".." in value:
            raise ValidationError("String contains path traversal sequence '..'")
        # Check for absolute paths
        if value.startswith("/") and "/" in value[1:]:
            # Allow single leading slash but not nested paths
            pass

    return value


def validate_enum(
    value: str | None,
    allowed_values: list[str],
    default: str,
    case_sensitive: bool = False,
) -> str:
    """
    Validate that a value is in the list of allowed values.

    Args:
        value: Value to check
        allowed_values: List of valid values
        default: Default value to return if value is None/empty or invalid
        case_sensitive: Whether comparison should be case-sensitive

    Returns:
        Valid value from allowed_values or default

    Raises:
        ValidationError: If value is not in allowed_values
    """
    if value is None or value == "":
        return default

    value = value.strip()

    if case_sensitive:
        if value not in allowed_values:
            raise ValidationError(
                f"Invalid value '{value}'. Must be one of: {', '.join(allowed_values)}"
            )
        return value
    else:
        # Case-insensitive comparison
        value_lower = value.lower()
        allowed_lower = [v.lower() for v in allowed_values]
        if value_lower not in allowed_lower:
            raise ValidationError(
                f"Invalid value '{value}'. Must be one of: {', '.join(allowed_values)}"
            )
        # Return the original case from allowed_values
        for allowed in allowed_values:
            if allowed.lower() == value_lower:
                return allowed
        return default


def validate_path_param(value: str, max_length: int) -> str:
    """
    Validate a URL path parameter (artist/album/track names).

    Path parameters are URL-decoded by Flask before reaching this function.

    Args:
        value: The path parameter value
        max_length: Maximum allowed length

    Returns:
        Validated string

    Raises:
        ValidationError: If value is too long
    """
    if not value:
        raise ValidationError("Path parameter cannot be empty")

    if len(value) > max_length:
        raise ValidationError(
            f"Path parameter exceeds maximum length of {max_length} characters"
        )

    return value


def validate_artist_name(value: str) -> str:
    """Validate an artist name path parameter."""
    return validate_path_param(value, MAX_ARTIST_NAME_LENGTH)


def validate_album_name(value: str) -> str:
    """Validate an album name path parameter."""
    return validate_path_param(value, MAX_ALBUM_NAME_LENGTH)


def validate_track_name(value: str) -> str:
    """Validate a track name path parameter."""
    return validate_path_param(value, MAX_TRACK_NAME_LENGTH)
