"""
Database connection management and utility functions.
"""
import sqlite3
import logging
import re
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone, timedelta


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

logger = logging.getLogger(__name__)


def get_db_connection() -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        logger.error(f"Database connection error: {e}")
        raise


@contextmanager
def db_connection():
    """
    Context manager for automatic database connection cleanup.

    Usage:
        with db_connection() as conn:
            conn.execute(...)
            # connection automatically closed after block
    """
    conn = get_db_connection()
    try:
        yield conn
    finally:
        conn.close()


def _ymd_to_epoch_bounds(start: str, end: str) -> tuple[int | None, int | None]:
    """
    Convert inclusive [start, end] in YYYY-MM-DD to epoch bounds:
    uts >= start_epoch AND uts < end_epoch_exclusive
    """
    if not start or not end:
        return None, None

    s = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    e = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)

    return int(s.timestamp()), int(e.timestamp())


def _normalize_for_matching(text: str) -> str:
    """
    Normalize text for fuzzy matching.
    - Removes accents (é → e, ö → o, etc.)
    - Lowercases
    - Replaces special characters (hyphens) with spaces
    - Removes other punctuation
    - Fixes common typos
    """
    if not text:
        return ""

    # Remove accents by converting to ASCII
    # e.g., "Café" → "Cafe", "ö" → "o"
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])

    # Lowercase
    text = text.lower()

    # Replace hyphens and slashes with spaces (important for "Four-Calendar" → "Four Calendar", "Weird Fishes/Arpeggi" → "Weird Fishes Arpeggi")
    text = re.sub(r'[–—\-/]+', ' ', text)

    # Remove common punctuation and special chars
    text = re.sub(r'[\'".,:;!?(){}\[\]<>]+', '', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Common typos/fixes
    typo_fixes = {
        'calender': 'calendar',
        'occured': 'occurred',
        'seperate': 'separate',
    }
    for typo, correct in typo_fixes.items():
        text = text.replace(typo, correct)

    return text


def _normalize_track_name_for_matching(text: str) -> str:
    """
    Normalize track name for matching between album_tracks and scrobbles.
    This handles smart quotes, common suffixes, and other variations.

    - Normalizes Unicode quotes/apostrophes to straight apostrophe
    - Normalizes Unicode dashes (en dash, em dash) to regular hyphen
    - Removes common suffixes like " - Remastered", " (Single Version)", etc.
    - Replaces slashes with spaces
    - Normalizes whitespace
    - Lowercases for case-insensitive matching
    """
    if not text:
        return ""

    # Unicode apostrophe/quote variants to straight apostrophe
    #   ' (U+2019 RIGHT SINGLE QUOTATION MARK) - most common "smart quote"
    #   ' (U+2018 LEFT SINGLE QUOTATION MARK)
    #   ' (U+00B4 ACUTE ACCENT)
    #   ` (U+0060 GRAVE ACCENT)
    quote_mapping = {
        '\u2019': "'",  # RIGHT SINGLE QUOTATION MARK
        '\u2018': "'",  # LEFT SINGLE QUOTATION MARK
        '\u00b4': "'",  # ACUTE ACCENT
        '\u0060': "'",  # GRAVE ACCENT
    }
    for unicode_char, straight_char in quote_mapping.items():
        text = text.replace(unicode_char, straight_char)

    # Normalize Unicode dashes to regular hyphen (U+002D)
    #   – (U+2013 EN DASH) - commonly used in track names from Last.fm
    #   — (U+2014 EM DASH)
    #   − (U+2212 MINUS SIGN)
    dash_mapping = {
        '\u2013': '-',  # EN DASH
        '\u2014': '-',  # EM DASH
        '\u2212': '-',  # MINUS SIGN
    }
    for unicode_char, hyphen in dash_mapping.items():
        text = text.replace(unicode_char, hyphen)

    # Replace slashes with spaces
    text = text.replace('/', ' ')

    # Lowercase for case-insensitive matching
    text = text.lower()

    # First, apply regex-based suffix removal (for patterns with years)
    # These must be done before literal suffix matching since they're more specific
    regex_patterns = [
        (r' - \d{4} remastered', ''),  # " - 2024 remastered"
        (r' \(\d{4} remastered\)', ''),  # " (2024 remastered)"
        (r' - \d{4} rem', ''),  # " - 2024 rem"
        (r' \(\d{4} rem\)', ''),  # " (2024 rem)"
        (r' - \d{4} ', ''),  # " - 2024 " (catch-all for year suffixes)
        (r' \(\d{4}\)', ''),  # " (2024)" (year in parentheses)
    ]
    for pattern, replacement in regex_patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Common suffixes to strip (order matters - longer first)
    suffixes = [
        " - john robie remix; substance edit",
        " (john robie remix; substance edit)",
        " - extended dance mix",
        " (extended dance mix)",
        " - substance edit",
        " (substance edit)",
        " - single version",
        " (single version)",
        " - album version",
        " (album version)",
        " - original version",
        " (original version)",
        " - original mix",
        " (original mix)",
        " - radio edit",
        " (radio edit)",
        " - remastered",
        " (remastered)",
        " - remastered version",
        " (remastered version)",
        " - rem",
        " (rem)",
        " - remix",
        " (remix)",
        " - edit",
        " (edit)",
    ]

    for suffix in suffixes:
        if text.lower().endswith(suffix):
            text = text[:-len(suffix)]

    # Normalize whitespace (handle 2+ spaces after replacing slashes)
    while "  " in text:
        text = text.replace("  ", " ")
    text = text.strip()

    return text
