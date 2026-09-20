"""Album-title rules shared by ingestion and canonical entity writers."""

from __future__ import annotations

import re


_DELUXE_QUALIFIER = r"(?:super\s+)?deluxe(?:\s+(?:edition|version|reissue))?"
_REMASTER_QUALIFIER = r"remaster(?:ed)?(?:\s+(?:edition|version))?"
_EXPANDED_QUALIFIER = r"expanded(?:\s+(?:edition|version))?"
_QUALIFIER_JOIN = r"(?:and|&|-)"
_COMBINED_QUALIFIER = (
    rf"(?:{_REMASTER_QUALIFIER}\s+{_QUALIFIER_JOIN}\s+{_EXPANDED_QUALIFIER}"
    rf"|{_EXPANDED_QUALIFIER}\s+{_QUALIFIER_JOIN}\s+{_REMASTER_QUALIFIER})"
)
_EDITION_QUALIFIER = (
    rf"(?:{_COMBINED_QUALIFIER}|{_DELUXE_QUALIFIER}|"
    rf"{_REMASTER_QUALIFIER}|{_EXPANDED_QUALIFIER})"
)
_EDITION_SUFFIX_RE = re.compile(
    rf"(?:"
    rf"\s*[\[(]\s*{_EDITION_QUALIFIER}\s*[\])]\s*"
    rf"|\s*(?:-|/|,)\s*{_EDITION_QUALIFIER}\s*"
    rf"|\s+{_EDITION_QUALIFIER}\s*"
    rf")$",
    flags=re.IGNORECASE,
)


def strip_edition_suffix(title: str) -> str:
    """Collapse a trailing remaster/expanded/deluxe qualifier to the base title."""
    if not title:
        return title
    return _EDITION_SUFFIX_RE.sub("", title).strip()


def strip_deluxe_album_suffix(title: str) -> str:
    """Backward-compatible name for the shared edition-suffix cleaner."""
    return strip_edition_suffix(title)
