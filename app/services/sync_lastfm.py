#!/usr/bin/env python3
"""
Sync Last.fm scrobbles into SQLite.

- Uses API key + username from config.ini via config.get_api_key()
- Stores uts as INTEGER Unix timestamp in SECONDS (UTC)
- Inserts scrobbles in chronological order (oldest -> newest)
- Reconciles duplicates by listen identity: (uts, artist, track)
- Populates album_art with cover URLs per album_mbid
"""

import time
import sqlite3
import re
import requests
import logging
import json
from pathlib import Path
from .config import get_api_key  # your helper: returns (api_key, username)
from app.db.notifications import (
    create_notification,
    create_notification_once,
    ensure_notifications_table,
)
from app.services.track_album_routing import apply_track_album_routing
from app.services.migrate_entity_tables import ensure_entity_schema
from app.db.entities import Resolver

# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Time chunk size for fetching scrobbles (in seconds)
# Using smaller chunks with both from/to ensures no scrobbles are missed
# 7 days = 7 * 24 * 60 * 60 = 604800 seconds
TIME_CHUNK_SECONDS = 604800  # 7 days

# Last.fm can briefly expose the album of the currently-playing copy on the
# just-completed scrobble.  Let fresh metadata settle, then re-read a rolling
# window so a later corrected response updates the existing listen.
SCROBBLE_SETTLE_SECONDS = 5 * 60
RECONCILE_LOOKBACK_SECONDS = 24 * 60 * 60

# Setup logging
from app.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)


# ---------- Cleaning helpers ----------

# Regex patterns to remove remastered/remaster, expanded edition, and deluxe edition suffixes
# Order matters: more specific patterns (with year) must come before less specific ones
# Matches variants like:
#   - " - Remastered 2014", " - Remaster 2009" (word before year)
#   - " - 2018 Remaster", " - 2009 Remastered" (year before word)
#   - " - Remastered", " - Remaster" (no year)
#   - " 2014 Remaster", " 2009 Remastered" (year before word, no dash)
#   - " Remastered" (no dash, no year)
#   - "(Remastered)", "[Remastered 2014]" (parenthetical, word before year)
#   - "(2018 Remaster)", "[2009 Remastered]" (parenthetical, year before word)
#   - " - Expanded Edition", " (Expanded Edition)" (expanded edition variants)
#   - "(Deluxe Edition)", "[Deluxe Edition]" (deluxe edition variants)
_REMASTER_PATTERNS = [
    # Year BEFORE word (more specific - must be first)
    r" -\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    r"\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    r"\s*[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*[\)\]]\s*$",
    # Word BEFORE year (less specific - comes after)
    r" -\s+(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*$",
    r"\s+(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*$",
    r"\s*[\(\[]\s*(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*[\)\]]\s*$",
    # Expanded Edition variants (including just "Expanded")
    r" -\s+(?:Expanded\s+Edition|Expanded\s+Version|Expanded)\s*$",
    r"\s+(?:Expanded\s+Edition|Expanded\s+Version|Expanded)\s*$",
    r"\s*[\(\[]\s*(?:Expanded\s+Edition|Expanded\s+Version|expanded\s+edition|expanded\s+version|Expanded)\s*[\)\]]\s*$",
    # Mix/version suffixes (e.g., "2007 Stereo Mix", "2009 Remaster", "2011 Mix")
    r" -\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+(?:Version|version)\s*$",
    r"\s+[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+(?:Version|version)\s*[\)\]]\s*$",
    r"\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+(?:Version|version)\s*$",
    r" -\s+\d{4}\s+(?:Stereo Mix|Mono Mix|Remix|Mix|Version)\s*$",
    r"\s+[\(\[]\s*\d{4}\s+(?:Stereo Mix|Mono Mix|Remix|Mix|Version)\s*[\)\]]\s*$",
    r"\s+\d{4}\s+(?:Stereo Mix|Mono Mix|Remix|Mix|Version)\s*$",
    # Single Version, Album Version, Remix variations (without year)
    r" -\s+(?:Single Version|Album Version|Remix|Mix)\s*$",
    r"\s*[\(\[]\s*(?:Single Version|Album Version|Remix|Mix)\s*[\)\]]\s*$",
    # Collection versions
    r" -\s+(?:Platinum Collection Version|Platinum Collection)\s*$",
    r"\s+(?:Platinum Collection Version|Platinum Collection)\s*$",
    r"\s*[\(\[]\s*(?:Platinum Collection Version|Platinum Collection)\s*[\)\]]\s*$",
    # Deluxe Edition/Version/Reissue variants (comprehensive)
    r" -\s+(?:Deluxe Edition|Deluxe Version|Deluxe Reissue|Deluxe)\s*$",
    r"\s+(?:Deluxe Edition|Deluxe Version|Deluxe Reissue|deluxe edition|deluxe version|Deluxe)\s*$",
    r"\s*[\(\[]\s*(?:Deluxe Edition|Deluxe Version|Deluxe Reissue|deluxe edition|deluxe version|Deluxe)\s*[\)\]]\s*$",
    r"\s*\[Deluxe\]\s*$",
    r"\s*\(Deluxe\)\s*$",
    # Slash separator patterns (e.g., "Soundtrack / Deluxe Edition")
    r"\s*/\s*(?:Deluxe Edition|Deluxe Version|deluxe edition)\s*[\)\]]*\s*$",
    r"\s+/ *(?:Deluxe Edition|Deluxe Version|deluxe edition)\s*$",
    # Live suffixes (e.g., " - Live", " - Live Version")
    r" -\s+(?:Live|live|Live Version|live version)\s*$",
    r"\s+[\(\[]\s*(?:Live|live|Live Version|live version)\s*[\)\]]\s*$",
    # Bare year suffix (e.g., " - 2011", " - 2009")
    r" -\s+\d{4}\s*$",
    r"\s+[\(\[]\s*\d{4}\s*[\)\]]\s*$",
    # Anniversary Edition suffixes (e.g., "25th Anniversary Edition", "40th Anniversary")
    # Colon separator (e.g., "Gladiator: 20th Anniversary Edition") - must be first before dash patterns
    r":\s+\d{1,2}(?:st|nd|rd|th)\s+Anniversary\s+(?:Edition|Version|Remaster|Remastered)\s*$",
    r" -\s+\d{1,2}(?:st|nd|rd|th)\s+Anniversary\s+(?:Edition|Version|Remaster|Remastered)\s*$",
    r"\s+[\(\[]\s*\d{1,2}(?:st|nd|rd|th)\s+Anniversary\s+(?:Edition|Version|Remaster|Remastered)\s*[\)\]]\s*$",
    r" -\s+\d{1,2}(?:st|nd|rd|th)\s+Anniversary\s*$",
    r"\s+[\(\[]\s*\d{1,2}(?:st|nd|rd|th)\s+Anniversary\s*[\)\]]\s*$",
    r" -\s+Anniversary\s+Edition\s*$",
    r"\s+[\(\[]\s*Anniversary\s+Edition\s*[\)\]]\s*$",
]

# ---------- Spotify track name mappings ----------
_SPOTIFY_MAPPINGS_PATH = BASE_DIR / "app" / "services" / "spotify_track_mappings.json"
_spotify_mappings_cache = None


def _load_spotify_mappings():
    """Load Spotify track name mappings from JSON file."""
    global _spotify_mappings_cache
    if _spotify_mappings_cache is None:
        try:
            if _SPOTIFY_MAPPINGS_PATH.exists():
                with open(_SPOTIFY_MAPPINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    _spotify_mappings_cache = data.get('mappings', [])
                    logger.debug(f"Loaded {len(_spotify_mappings_cache)} Spotify track mappings")
            else:
                _spotify_mappings_cache = []
                logger.debug(f"No Spotify mappings file found at {_SPOTIFY_MAPPINGS_PATH}")
        except Exception as e:
            logger.error(f"Error loading Spotify mappings: {e}")
            _spotify_mappings_cache = []
    return _spotify_mappings_cache


def clean_spotify_track_name(artist: str, album: str, track: str) -> str:
    """
    Apply Spotify-specific track name corrections based on mapping file.

    This handles cases where Spotify uses non-standard naming that differs
    from the official album tracklist (e.g., capitalization variations,
    missing parentheticals, etc.).

    Args:
        artist: Artist name
        album: Album name
        track: Original track name from Last.fm/Spotify

    Returns:
        Standardized track name if mapping exists, otherwise original track name
    """
    if not track:
        return track

    mappings = _load_spotify_mappings()

    for mapping in mappings:
        if (mapping.get('artist') == artist and
            mapping.get('album') == album and
            mapping.get('from') == track):
            standard_name = mapping.get('to')
            logger.debug(f"Spotify mapping: '{track}' -> '{standard_name}' for {artist} - {album}")
            return standard_name

    return track


def apply_scrobble_metadata_mapping(
    artist: str,
    album: str | None,
    track: str,
    artist_mbid: str | None = None,
    album_mbid: str | None = None,
    track_mbid: str | None = None,
) -> tuple[str, str | None, str, str | None, str | None, str | None]:
    """Apply an exact track mapping, including optional artist/album overrides.

    Most entries only rename a track.  The optional ``to_artist`` and
    ``to_album`` fields support source metadata that attributes a cover to the
    performer rather than to the canonical recording artist/release.
    """
    for mapping in _load_spotify_mappings():
        if (
            mapping.get("artist") == artist
            and mapping.get("album") == album
            and mapping.get("from") == track
        ):
            artist = mapping.get("to_artist", artist)
            album = mapping.get("to_album", album)
            track = mapping.get("to", track)
            if "to_artist_mbid" in mapping:
                artist_mbid = mapping.get("to_artist_mbid") or None
            if "to_album_mbid" in mapping:
                album_mbid = mapping.get("to_album_mbid") or None
            if "to_track_mbid" in mapping:
                track_mbid = mapping.get("to_track_mbid") or None
            break
    return artist, album, track, artist_mbid, album_mbid, track_mbid


# ---------- Album name mappings ----------
_ALBUM_MAPPINGS_PATH = BASE_DIR / "app" / "services" / "album_name_mappings.json"
_album_mappings_cache = None


def _load_album_mappings():
    """Load album name mappings from JSON file."""
    global _album_mappings_cache
    if _album_mappings_cache is None:
        try:
            if _ALBUM_MAPPINGS_PATH.exists():
                with open(_ALBUM_MAPPINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    _album_mappings_cache = data.get('mappings', [])
                    logger.debug(f"Loaded {len(_album_mappings_cache)} album name mappings")
            else:
                _album_mappings_cache = []
                logger.debug(f"No album mappings file found at {_ALBUM_MAPPINGS_PATH}")
        except Exception as e:
            logger.error(f"Error loading album mappings: {e}")
            _album_mappings_cache = []
    return _album_mappings_cache


def clean_album_name(artist: str, album: str) -> str:
    """
    Apply album name corrections based on mapping file.

    This handles cases where Last.fm/Spotify uses incorrect album names
    that won't be caught by automatic cleaning patterns.

    Args:
        artist: Artist name
        album: Original album name from Last.fm/Spotify

    Returns:
        Corrected album name if mapping exists, otherwise original album name
    """
    if not album:
        return album

    mappings = _load_album_mappings()

    for mapping in mappings:
        if (mapping.get('artist') == artist and
            mapping.get('from') == album):
            correct_name = mapping.get('to')
            logger.info(f"Album mapping: '{album}' -> '{correct_name}' for {artist}")
            return correct_name

    return album


# ---------- Artist name mappings ----------
_ARTIST_MAPPINGS_PATH = BASE_DIR / "app" / "services" / "artist_name_mappings.json"
_artist_mappings_cache = None


def _load_artist_mappings():
    """Load artist name mappings from JSON file."""
    global _artist_mappings_cache
    if _artist_mappings_cache is None:
        try:
            if _ARTIST_MAPPINGS_PATH.exists():
                with open(_ARTIST_MAPPINGS_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    _artist_mappings_cache = data.get('mappings', [])
                    logger.debug(f"Loaded {len(_artist_mappings_cache)} artist name mappings")
            else:
                _artist_mappings_cache = []
                logger.debug(f"No artist mappings file found at {_ARTIST_MAPPINGS_PATH}")
        except Exception as e:
            logger.error(f"Error loading artist mappings: {e}")
            _artist_mappings_cache = []
    return _artist_mappings_cache


def clean_artist_name(artist: str) -> str:
    """
    Apply artist name corrections based on mapping file.

    This handles cases where Last.fm/Spotify uses incorrect artist names
    that won't be caught by automatic cleaning patterns.

    Args:
        artist: Original artist name from Last.fm/Spotify

    Returns:
        Corrected artist name if mapping exists, otherwise original artist name
    """
    if not artist:
        return artist

    mappings = _load_artist_mappings()

    for mapping in mappings:
        if mapping.get('from') == artist:
            correct_name = mapping.get('to')
            logger.info(f"Artist mapping: '{artist}' -> '{correct_name}'")
            return correct_name

    return artist


def normalize_album_separators(title: str) -> str:
    """
    Normalize album title separators to use hyphens instead of colons.
    This handles cases where different sources use different separators.

    Examples:
        "Echoes: the Best of Pink Floyd" -> "Echoes - the Best of Pink Floyd"
        "The Best: The Singles" -> "The Best - The Singles"

    Args:
        title: The original title

    Returns:
        Title with colons normalized to hyphens
    """
    if not title:
        return title

    # Replace " : " or ": " with " - " (common pattern in album titles)
    return re.sub(r'\s*:\s+', ' - ', title).strip()


def clean_remastered_suffix(title: str) -> str:
    """
    Remove artificial remastered/remaster, expanded edition, deluxe edition, and live suffixes from album or track titles.
    These are added by Last.fm/music services and are not part of the original title.

    Args:
        title: The original title from Last.fm API

    Returns:
        Cleaned title with remastered/remaster, expanded edition, deluxe edition, and live suffixes removed
    """
    if not title:
        return title

    cleaned = title
    for pattern in _REMASTER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


# Small words that should be lowercase in titles (except first/last word)
_SMALL_WORDS = {
    'a', 'an', 'the', 'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
    'at', 'by', 'from', 'in', 'into', 'of', 'off', 'on', 'onto', 'out',
    'over', 'to', 'up', 'with', 'as', 'but', 'via'
}


def _fix_small_words_case(title: str) -> str:
    """
    Fix capitalization of small words in titles to lowercase.
    These words should be lowercase except when they are the first or last word.

    Examples:
        "Beatles For Sale" -> "Beatles for Sale"
        "Ride The Lightning" -> "Ride the Lightning"
        "Back And Forth" -> "Back and Forth" (last word stays capitalized)

    Args:
        title: The title to fix

    Returns:
        Title with small words converted to lowercase (except first/last word)
    """
    if not title:
        return title

    words = title.split()
    if not words:
        return title

    # Fix small words that are not first or last
    for i in range(1, len(words) - 1):
        word_lower = words[i].lower()
        if word_lower in _SMALL_WORDS:
            words[i] = word_lower

    return ' '.join(words)


def clean_title(title: str, artist: str = None, album: str = None) -> str:
    """
    Clean a title by applying all cleaning functions in order.

    Args:
        title: The original title from Last.fm API
        artist: Artist name (optional, for Spotify-specific mappings)
        album: Album name (optional, for Spotify-specific mappings)

    Returns:
        Cleaned title with separators normalized, remastered suffixes removed, and small words fixed
    """
    if not title:
        return title

    # Apply Spotify-specific mappings first (if artist/album provided)
    if artist and album:
        title = clean_spotify_track_name(artist, album, title)

    title = normalize_album_separators(title)
    title = clean_remastered_suffix(title)

    # Normalize Unicode quotes to regular quotes before small words fix
    # This handles smart quotes from MusicBrainz: ' ' " " → ' "
    title = title.replace('\u2018', "'")  # Left single quote
    title = title.replace('\u2019', "'")  # Right single quote (apostrophe)
    title = title.replace('\u201c', '"')  # Left double quote
    title = title.replace('\u201d', '"')  # Right double quote

    title = _fix_small_words_case(title)

    return title


# ---------- Compilation album patterns ----------
# Known compilation album series and patterns
# These are albums that typically contain tracks from various artists
# Compilation detection patterns
# Used as fallback when album_mbid is not available
_COMPILATION_PATTERNS = [
    # Soundtrack patterns (high confidence)
    r'.*Soundtrack.*',
    r'.*OST.*',  # Original Soundtrack
    r'.*Original Motion Picture Soundtrack.*',
    r'.*Motion Picture Soundtrack.*',
    r'.*Music From and Inspired.*',
    r'.*Music from the Motion Picture.*',
    r'.*Score.*',  # Film scores
    # Compilation series
    r'Kuschel Rock\s*\d*',
    r'Kuschelrock\s*\d*',
    r'Bravo Hits\s*\d*',
    r'Now That\'?s What I Call Music',
    r'Now \d+',
    r'Totally \w+',
    # Various Artists indicators
    r'Various Artists',
    r'VA\s*-',
    r'\[VA\]',
    r'^VA\b',
    # Explicit compilation keywords
    r'\bCompilations?\b',
    r'\bGreatest Hits\b.*Various',  # Various artists greatest hits
    r'\bThe Best\b.*Various',
]

# Single-artist collections whose generic titles are prone to being confused
# with Various Artists releases. These must retain their performing artist as
# album_artist even though the release type itself is a compilation.
_FORCED_SINGLE_ARTIST_ALBUMS = {
    ("Boney M.", "Greatest Hits"),
    ("Eurythmics", "Greatest Hits"),
}

def _matches_compilation_pattern(album: str) -> bool:
    """
    Check if album name matches known compilation patterns.
    NOTE: Only used for validation hints, NOT for auto-detection.
    Auto-detection is based solely on artist count (4+ artists).

    Args:
        album: Album name

    Returns:
        True if album matches a known compilation pattern
    """
    if not album:
        return False

    for pattern in _COMPILATION_PATTERNS:
        if re.search(pattern, album, re.IGNORECASE):
            return True
    return False


# ---------- DB helpers ----------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enforce FK constraints at runtime (entity *_id columns are nullable,
    # so this is safe with existing data). See migrate_entity_tables.py.
    conn.execute("PRAGMA foreign_keys = ON")
    # Wait for a write lock instead of failing "database is locked" when the
    # web app writes concurrently with this sync (WAL allows only one writer).
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def _is_album_compilation(conn: sqlite3.Connection, album: str, album_mbid: str | None, current_artist: str) -> bool:
    """
    Check if an album is a compilation by examining existing scrobbles.

    An album is considered a compilation if it has 4+ distinct artists.
    This threshold prevents single-artist greatest hits albums from being
    incorrectly flagged as compilations.

    IMPORTANT: Only considers albums with a non-NULL album_mbid to avoid
    incorrectly flagging different artists' albums with the same name as compilations.

    Args:
        conn: Database connection
        album: Album name
        album_mbid: MusicBrainz ID for the album (can distinguish albums with same name)
        current_artist: The artist of the scrobble being processed

    Returns:
        True if the album should be marked as a compilation (album_artist = "Various Artists")
    """
    if not album:
        return False

    # Only proceed if we have an MBID to avoid false positives
    if album_mbid is None:
        return False

    # Count distinct artists for this album in existing scrobbles
    cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT artist) as artist_count
        FROM scrobble
        WHERE album = ? AND album_mbid = ?
        """,
        (album, album_mbid)
    )
    row = cursor.fetchone()
    existing_artist_count = row["artist_count"] if row else 0

    # Include current artist in the count
    total_artists = existing_artist_count

    # If we already have 3+ existing artists, adding current artist makes 4+
    if total_artists >= 3:
        return True

    # If we have 1-2 existing artists, check if current artist is different
    if existing_artist_count > 0:
        cursor = conn.execute(
            """
            SELECT DISTINCT artist
            FROM scrobble
            WHERE album = ? AND album_mbid = ?
            LIMIT 4
            """,
            (album, album_mbid)
        )
        existing_artists = {row["artist"] for row in cursor.fetchall()}
        # Add current artist to the set
        existing_artists.add(current_artist)
        # Check if we now have 4+ distinct artists
        if len(existing_artists) >= 4:
            return True

    return False


def _is_single_artist_album(conn: sqlite3.Connection, album: str, album_mbid: str | None, current_artist: str) -> bool:
    """
    Check if an album has only been scrobbled by a single artist.

    This prevents false positives where a single-artist greatest hits or
    collection album gets incorrectly tagged as "Various Artists" because
    the album name matches a compilation pattern (e.g. "Collection", "Anthology").
    """
    if album_mbid:
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT artist) as cnt FROM scrobble WHERE album = ? AND album_mbid = ?",
            (album, album_mbid),
        )
    else:
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT artist) as cnt FROM scrobble WHERE album = ?",
            (album,),
        )
    row = cursor.fetchone()
    # Only the current artist exists (count is 0 or 1)
    return row["cnt"] <= 1


def _is_album_compilation_with_fallback(conn: sqlite3.Connection, album: str, album_mbid: str | None, current_artist: str) -> bool:
    """
    Check if an album is a compilation with fallback detection for missing MBIDs.

    This extends _is_album_compilation() by adding fallback mechanisms:
    1. First tries the MBID-based detection (most accurate)
    2. Falls back to pattern matching for known compilation types (soundtracks, etc.)
    3. Falls back to artist count by album name only (less accurate, but better than nothing)

    Args:
        conn: Database connection
        album: Album name
        album_mbid: MusicBrainz ID for the album (can be None)
        current_artist: The artist of the scrobble being processed

    Returns:
        True if the album should be marked as a compilation (album_artist = "Various Artists")
    """
    if not album:
        return False

    if (current_artist, album) in _FORCED_SINGLE_ARTIST_ALBUMS:
        return False

    # First, try the accurate MBID-based detection
    if album_mbid is not None:
        return _is_album_compilation(conn, album, album_mbid, current_artist)

    # Fallback 1: Check if album name matches known compilation patterns
    # This is high confidence for soundtracks, OSTs, etc.
    if _matches_compilation_pattern(album):
        logger.debug(f"Album '{album}' matches compilation pattern (no MBID)")
        return True

    # Fallback 2: Check artist count by album name only (without MBID)
    # This is less accurate but catches multi-artist compilations without MBIDs
    # We use a higher threshold (6+ artists) to reduce false positives
    cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT artist) as artist_count
        FROM scrobble
        WHERE album = ?
        """,
        (album,)
    )
    row = cursor.fetchone()
    existing_artist_count = row["artist_count"] if row else 0

    # Include current artist in the count
    total_artists = existing_artist_count

    # Use higher threshold (6+ artists) when we don't have MBID to avoid false positives
    if total_artists >= 6:
        logger.debug(f"Album '{album}' has {total_artists}+ artists (no MBID)")
        return True

    # If we have 3-5 existing artists, check if current artist is different
    if existing_artist_count >= 3:
        cursor = conn.execute(
            """
            SELECT DISTINCT artist
            FROM scrobble
            WHERE album = ?
            LIMIT 7
            """,
            (album,)
        )
        existing_artists = {row["artist"] for row in cursor.fetchall()}
        existing_artists.add(current_artist)

        if len(existing_artists) >= 6:
            logger.debug(f"Album '{album}' has {len(existing_artists)}+ artists (no MBID)")
            return True

    return False


def validate_scrobble_track(conn, artist, album, track, track_mbid=None):
    """
    Validate a scrobble track against existing album_tracks data.

    Returns dict with:
        - is_valid: bool (True if match found or no album_tracks exist)
        - matched_track: str | None (the matched track name from album_tracks)
        - confidence: int (0-100)
        - issue_type: str ('exact_match', 'normalized_match', 'no_match', 'no_album_tracks')
        - album_tracks: list (all tracks from album_tracks for this album)
    """
    from app.db.connections import _normalize_track_name_for_matching

    # Check if album_tracks exist for this artist/album
    cursor = conn.execute(
        """
        SELECT track, track_number
        FROM album_tracks
        WHERE artist = ? AND album = ?
        ORDER BY track_number
        """,
        (artist, album)
    )
    album_tracks_list = cursor.fetchall()

    if not album_tracks_list:
        return {
            'is_valid': True,
            'matched_track': None,
            'confidence': 100,
            'issue_type': 'no_album_tracks',
            'album_tracks': []
        }

    # Normalize the scrobble track name
    normalized_scrobble = _normalize_track_name_for_matching(track)

    # Try to find a match
    for at in album_tracks_list:
        normalized_at = _normalize_track_name_for_matching(at['track'])
        if normalized_scrobble == normalized_at:
            if track != at['track']:
                # Names differ but normalize the same
                return {
                    'is_valid': True,
                    'matched_track': at['track'],
                    'confidence': 95,
                    'issue_type': 'normalized_match',
                    'album_tracks': [dict(at) for at in album_tracks_list]
                }
            return {
                'is_valid': True,
                'matched_track': at['track'],
                'confidence': 100,
                'issue_type': 'exact_match',
                'album_tracks': [dict(at) for at in album_tracks_list]
            }

    # No match found
    return {
        'is_valid': False,
        'matched_track': None,
        'confidence': 0,
        'issue_type': 'no_match',
        'album_tracks': [dict(at) for at in album_tracks_list]
    }


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Main scrobble table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scrobble (
            id          INTEGER PRIMARY KEY,
            artist      TEXT NOT NULL,
            artist_mbid TEXT,
            album       TEXT NOT NULL,
            album_mbid  TEXT,
            track       TEXT NOT NULL,
            track_mbid  TEXT,
            uts         INTEGER NOT NULL
        );
    """)

    # Album is mutable metadata, not part of a listen's identity.
    from app.services.migrations.reindex_scrobble_identity import (
        ensure_scrobble_identity_index,
    )
    ensure_scrobble_identity_index(conn)

    # Album artwork / metadata
    cur.execute("""
        CREATE TABLE IF NOT EXISTS album_art (
            artist           TEXT NOT NULL,
            album            TEXT NOT NULL,
            album_mbid       TEXT,
            artist_mbid      TEXT,
            image_small      TEXT,
            image_medium     TEXT,
            image_large      TEXT,
            image_xlarge     TEXT,
            last_updated     INTEGER,
            year_col         INTEGER,
            PRIMARY KEY (artist, album)
        );
    """)

    # Add index on album_mbid for lookups when available
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_album_art_mbid
        ON album_art(album_mbid)
        WHERE album_mbid IS NOT NULL
    """)

    # Notifications table for tracking sync issues and admin alerts
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            created_at INTEGER NOT NULL,
            dismissed_at INTEGER,
            severity TEXT NOT NULL DEFAULT 'info'
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_active
        ON notifications(dismissed_at)
        WHERE dismissed_at IS NULL
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_notifications_created
        ON notifications(created_at DESC)
    """)

    # Canonical entity tables + nullable *_id FK columns (Phase 0 relational
    # rework). Idempotent and additive; shared source of truth lives in
    # migrate_entity_tables.py so fresh installs match migrated databases.
    ensure_entity_schema(conn)

    conn.commit()


def get_last_uts(conn: sqlite3.Connection) -> int:
    """
    Return latest uts in seconds (0 if table empty).

    Note: Uses CAST to handle any TEXT values in uts column that might
    cause MAX() to fail silently.
    """
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(CAST(uts AS INTEGER)), 0) FROM scrobble;")
    (val,) = cur.fetchone()
    return int(val or 0)


# ---------- Last.fm API ----------

def fetch_recent_tracks(api_key: str,
                        username: str,
                        from_ts: int | None,
                        to_ts: int | None = None,
                        page: int = 1,
                        limit: int = 200) -> dict:
    """
    Call user.getRecentTracks for one page.

    Uses both from and to parameters to ensure no scrobbles are missed.
    Last.fm API has known issues with 'from' only - using both parameters
    is more reliable for complete data retrieval.
    """
    params = {
        "method": "user.getRecentTracks",
        "user": username,
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "page": page,
    }
    if from_ts is not None:
        params["from"] = int(from_ts)
    if to_ts is not None:
        params["to"] = int(to_ts)

    logger.debug(f"Calling Last.fm API: page={page}, from_ts={from_ts}, to_ts={to_ts}")
    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        logger.error(f"Last.fm API error {data['error']}: {data.get('message')}")
        raise RuntimeError(f"Last.fm API error {data['error']}: {data.get('message')}")

    return data


def _update_compilation_albums(conn: sqlite3.Connection) -> None:
    """
    Update album_artist to 'Various Artists' for compilation albums.

    A compilation is defined as an album with 4+ distinct artists.
    Albums are identified by (album, album_mbid) to distinguish different
    albums that happen to have the same name (e.g., "21" by Adele vs "21" by KSU).

    IMPORTANT: Only considers albums with a non-NULL album_mbid to avoid
    incorrectly flagging different artists' albums with the same name as compilations.
    """
    # Find all (album, album_mbid) combinations that should be compilations
    # Threshold: 4+ distinct artists (not 2+ to avoid single-artist greatest hits)
    cursor = conn.execute(
        """
        SELECT album, album_mbid
        FROM scrobble
        WHERE album IS NOT NULL AND album != '' AND album_mbid IS NOT NULL
        GROUP BY album, album_mbid
        HAVING COUNT(DISTINCT artist) >= 4
        """
    )
    compilation_albums = [(row["album"], row["album_mbid"]) for row in cursor.fetchall()]

    if not compilation_albums:
        logger.debug("No compilation albums found to update.")
        return

    # Build placeholders for the UPDATE query
    # We need two placeholders per compilation: one for album, one for album_mbid
    placeholders = ",".join(["(?,?)" for _ in compilation_albums])
    flat_values = []
    for album, mbid in compilation_albums:
        flat_values.extend([album, mbid])

    cursor = conn.execute(
        f"""
        UPDATE scrobble
        SET album_artist = 'Various Artists'
        WHERE (album, album_mbid) IN ({placeholders})
          AND album_artist != 'Various Artists'
        """,
        flat_values,
    )

    updated = cursor.rowcount
    _restore_forced_single_artist_albums(conn)
    conn.commit()
    logger.info(
        f"Updated album_artist to 'Various Artists' for {updated} scrobbles "
        f"across {len(compilation_albums)} compilation albums (4+ artists each)."
    )


def _restore_forced_single_artist_albums(conn: sqlite3.Connection) -> int:
    """Undo generic compilation classification for explicit artist releases."""
    restored = 0
    for artist, album in _FORCED_SINGLE_ARTIST_ALBUMS:
        cursor = conn.execute(
            """UPDATE scrobble SET album_artist = ?
               WHERE artist = ? AND album = ? AND album_artist != ?""",
            (artist, artist, album, artist),
        )
        restored += cursor.rowcount
    return restored


def _update_compilation_albums_no_mbid(conn: sqlite3.Connection) -> None:
    """
    Update album_artist to 'Various Artists' for compilation albums without MBIDs.

    This is a fallback for albums that don't have MusicBrainz IDs.
    Uses:
    1. Pattern matching for known compilation types (soundtracks, OSTs, etc.)
    2. Artist count threshold (6+ artists) when no MBID is available

    IMPORTANT: Uses a higher threshold (6+ artists) and pattern matching
    to reduce false positives for albums without MBIDs.
    """
    updated_total = 0

    # 1. Find albums matching compilation patterns (high confidence)
    cursor = conn.execute(
        """
        SELECT DISTINCT album
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        """
    )
    albums_to_check = [row["album"] for row in cursor.fetchall()]

    pattern_albums = []
    for album in albums_to_check:
        if _matches_compilation_pattern(album):
            # Safety check: skip single-artist albums that happen to match a pattern
            artist_count = conn.execute(
                "SELECT COUNT(DISTINCT artist) as cnt FROM scrobble WHERE album = ? AND album_mbid IS NULL",
                (album,),
            ).fetchone()["cnt"]
            if artist_count >= 3:
                pattern_albums.append(album)
            else:
                logger.debug(f"Skipping single-artist album matching compilation pattern: '{album}' ({artist_count} artist(s))")

    # Update albums matching compilation patterns
    if pattern_albums:
        placeholders = ",".join(["?" for _ in pattern_albums])
        cursor = conn.execute(
            f"""
            UPDATE scrobble
            SET album_artist = 'Various Artists'
            WHERE album IN ({placeholders})
              AND album_mbid IS NULL
              AND album_artist != 'Various Artists'
            """,
            pattern_albums,
        )
        updated = cursor.rowcount
        updated_total += updated
        logger.info(f"Pattern-based: Updated {updated} scrobbles across {len(pattern_albums)} compilation albums (matched by name).")

    # 2. Find albums with 6+ distinct artists (lower confidence)
    cursor = conn.execute(
        """
        SELECT album
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        GROUP BY album
        HAVING COUNT(DISTINCT artist) >= 6
        """
    )
    high_artist_albums = [row["album"] for row in cursor.fetchall()]

    # Update albums with high artist count
    if high_artist_albums:
        placeholders = ",".join(["?" for _ in high_artist_albums])
        cursor = conn.execute(
            f"""
            UPDATE scrobble
            SET album_artist = 'Various Artists'
            WHERE album IN ({placeholders})
              AND album_mbid IS NULL
              AND album_artist != 'Various Artists'
            """,
            high_artist_albums,
        )
        updated = cursor.rowcount
        updated_total += updated
        logger.info(f"Artist-count-based: Updated {updated} scrobbles across {len(high_artist_albums)} compilation albums (6+ artists, no MBID).")

    restored = _restore_forced_single_artist_albums(conn)
    if updated_total > 0 or restored > 0:
        conn.commit()

    if updated_total == 0:
        logger.debug("No compilation albums (no MBID) found to update.")


# ---------- Sync logic ----------

def sync_lastfm() -> None:
    api_key, username = get_api_key()
    logger.info(f"Starting Last.fm sync for user: {username}")

    # Lazy import: app.services.ingest imports cleaning helpers from this module
    # at top level, so it must be imported here (call time) to avoid a cycle.
    from app.services.ingest import AlbumlessScrobbleError, RawScrobble, ingest_scrobble

    conn = get_conn()
    ensure_schema(conn)
    # One resolver per sync connection; its cache warms as distinct entities
    # are seen, so post-first-page resolves are dict hits. (Phase 2)
    resolver = Resolver(conn)

    last_uts = get_last_uts(conn)
    logger.info(f"Last known timestamp in database: {last_uts} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(last_uts))} UTC)")

    # Re-read recent rows so corrected Last.fm metadata can be reconciled.
    from_ts = None if last_uts == 0 else max(0, last_uts - RECONCILE_LOOKBACK_SECONDS)

    # Use time chunks to ensure no scrobbles are missed
    # Last.fm API has known issues with 'from' only - using both from+to is more reliable
    now_ts = int(time.time()) - SCROBBLE_SETTLE_SECONDS
    chunk_start = from_ts if from_ts is not None else 0
    total_new_scrobbles = 0
    chunks_processed = 0

    # Process data in time chunks
    while chunk_start is not None and chunk_start < now_ts:
        chunks_processed += 1
        chunk_end = min(chunk_start + TIME_CHUNK_SECONDS, now_ts)

        logger.info(f"Processing time chunk {chunks_processed}: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(chunk_start))} UTC to {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(chunk_end))} UTC")

        page = 1
        chunk_new_scrobbles = 0
        pages_with_data = 0

        while True:
            logger.debug(f"Fetching page {page} for chunk {chunks_processed} (from_ts={chunk_start}, to_ts={chunk_end})...")
            data = fetch_recent_tracks(api_key, username, chunk_start, chunk_end, page)
            recent = data.get("recenttracks", {})
            tracks = recent.get("track", [])

            if isinstance(tracks, dict):
                tracks = [tracks]

            if not tracks:
                logger.debug(f"No tracks returned for page {page} of chunk {chunks_processed}")
                break

            album_batch: list[dict] = []
            current_ts = int(time.time())

            # Parse + filter (skip "now playing" / undated items).
            parsed = []
            for t in tracks:
                if "@attr" in t and t["@attr"].get("nowplaying") == "true":
                    continue
                if not t.get("date"):
                    continue
                parsed.append(t)

            if not parsed:
                logger.debug(f"No scrobbles on page {page} of chunk {chunks_processed}")
                break

            pages_with_data += 1

            # Insert oldest-first (chronological), one transaction per page.
            parsed.sort(key=lambda t: int(t["date"]["uts"]))

            page_processed = 0
            page_inserted = 0
            page_reconciled = 0
            for t in parsed:
                uts = int(t["date"]["uts"])  # Last.fm gives seconds
                if uts > 2_000_000_000:      # guard against ms sneaking in
                    uts //= 1000

                artist_name_raw = t["artist"]["#text"]
                artist_mbid = t["artist"].get("mbid") or None

                if isinstance(t.get("album"), dict):
                    album_name_raw = t["album"]["#text"]
                    album_mbid = t["album"].get("mbid") or None
                else:
                    album_name_raw = t.get("album", "")
                    album_mbid = None

                track_name_raw = t["name"]
                track_mbid = t.get("mbid") or None

                # Album art images (pull path only) -> dict for ingest.
                images = None
                for img in (t.get("image", []) or []):
                    url = img.get("#text") or None
                    if not url:
                        continue
                    size = img.get("size")
                    if images is None:
                        images = {}
                    if size == "small":
                        images["small"] = url
                    elif size == "medium":
                        images["medium"] = url
                    elif size == "large":
                        images["large"] = url
                    elif size in ("extralarge", "mega"):
                        images["xlarge"] = url

                raw_scrobble = RawScrobble(
                    artist_name=artist_name_raw,
                    track_name=track_name_raw,
                    uts=uts,
                    artist_mbid=artist_mbid,
                    album_name=album_name_raw or None,
                    album_mbid=album_mbid,
                    track_mbid=track_mbid,
                    source="lastfm",
                    images=images,
                )
                try:
                    result = ingest_scrobble(conn, resolver, raw_scrobble)
                except AlbumlessScrobbleError:
                    incident_title = f"Albumless Last.fm scrobble skipped ({uts})"
                    create_notification_once(
                        notification_type="sync_skip",
                        title=incident_title,
                        message=(
                            f'Last.fm returned "{track_name_raw}" by '
                            f'{artist_name_raw} without an album. The scrobble '
                            "was not added to the database."
                        ),
                        details={
                            "artist": artist_name_raw,
                            "track": track_name_raw,
                            "uts": uts,
                            "timestamp_utc": time.strftime(
                                "%Y-%m-%d %H:%M:%S", time.gmtime(uts)
                            ),
                            "reason": "missing_album",
                        },
                        severity="warning",
                        conn=conn,
                    )
                    logger.warning(
                        'Skipped albumless scrobble: %s - "%s" (%s)',
                        artist_name_raw, track_name_raw, uts,
                    )
                    continue
                page_processed += 1
                if result.inserted:
                    page_inserted += 1
                if result.reconciled:
                    page_reconciled += 1
                if result.album_art_record:
                    result.album_art_record["last_updated"] = current_ts
                    album_batch.append(result.album_art_record)

            conn.commit()

            new_rows = page_inserted
            unchanged_rows = page_processed - new_rows - page_reconciled
            total_new_scrobbles += new_rows
            chunk_new_scrobbles += new_rows
            logger.info(
                f"Chunk {chunks_processed}, page {page}: inserted {new_rows} new scrobbles "
                f"and reconciled {page_reconciled} (batch size {page_processed})"
            )

            if unchanged_rows:
                logger.debug("%d lookback scrobble(s) already current", unchanged_rows)

            # Optional: sort album_art batch by (artist, album) then time
            if album_batch:
                album_batch.sort(key=lambda a: (a["artist"], a["album"], a["last_updated"]))
                for a in album_batch:
                    conn.execute(
                        """
                        INSERT INTO album_art (
                            artist, album, album_mbid, artist_mbid,
                            artist_id, album_id,
                            image_small, image_medium, image_large, image_xlarge,
                            last_updated
                        )
                        VALUES (
                            :artist, :album, :album_mbid, :artist_mbid,
                            :artist_id, :album_id,
                            :image_small, :image_medium, :image_large, :image_xlarge,
                            :last_updated
                        )
                        ON CONFLICT(artist, album) DO UPDATE SET
                            album_mbid      = COALESCE(excluded.album_mbid, album_art.album_mbid),
                            artist_mbid     = COALESCE(excluded.artist_mbid, album_art.artist_mbid),
                            artist_id       = COALESCE(excluded.artist_id, album_art.artist_id),
                            album_id        = COALESCE(excluded.album_id, album_art.album_id),
                            image_small     = COALESCE(excluded.image_small, album_art.image_small),
                            image_medium    = COALESCE(excluded.image_medium, album_art.image_medium),
                            image_large     = COALESCE(excluded.image_large, album_art.image_large),
                            image_xlarge    = COALESCE(excluded.image_xlarge, album_art.image_xlarge),
                            last_updated    = excluded.last_updated;
                        """,
                        a,
                    )
                conn.commit()
                logger.debug(f"Page {page}: upserted {len(album_batch)} album_art rows")

            # Pagination
            attr = recent.get("@attr", {})
            total_pages = int(attr.get("totalPages", page))

            if page >= total_pages:
                logger.debug(f"Reached final page {page} of {total_pages} for chunk {chunks_processed}")
                break

            page += 1
            # polite delay – you're nowhere near the rate limit with this
            time.sleep(0.25)

        if chunk_new_scrobbles == 0 and pages_with_data == 0:
            # No data in this chunk, we might be past the last scrobble
            logger.debug(f"No data found in chunk {chunks_processed}, stopping sync")
            break

        # After each chunk: update album_artist for compilation albums
        # This ensures newly synced scrobbles get marked correctly without waiting for full sync to complete
        if chunk_new_scrobbles > 0:
            logger.info(f"Chunk {chunks_processed}: updating compilation album artists...")
            _update_compilation_albums(conn)
            _update_compilation_albums_no_mbid(conn)

        # Move to next chunk
        chunk_start = chunk_end + 1

    # Post-sync: final update album_artist for compilation albums
    if total_new_scrobbles > 0:
        logger.info("Post-sync: final compilation album detection...")
        _update_compilation_albums(conn)
        _update_compilation_albums_no_mbid(conn)

        # Post-sync: re-route scrobbles on colliding self-titled albums by track name
        logger.info("Post-sync: track-name album routing...")
        apply_track_album_routing(conn)

    conn.close()
    logger.info(f"Sync complete. Total new scrobbles added: {total_new_scrobbles}")


# ---------- CLI entry point ----------

if __name__ == "__main__":
    import traceback
    try:
        sync_lastfm()
        logger.info("Sync finished successfully.")
    except requests.exceptions.RequestException as exc:
        logger.error(f"Network error during sync: {exc}", exc_info=True)
        try:
            create_notification(
                notification_type='sync_error',
                title='Last.fm sync failed: Network error',
                message=f'Could not connect to Last.fm API: {str(exc)}',
                details={'error': str(exc), 'error_type': 'RequestException'},
                severity='error'
            )
        except Exception as notify_err:
            logger.error(f"Failed to create notification: {notify_err}")
    except sqlite3.Error as exc:
        logger.error(f"Database error during sync: {exc}", exc_info=True)
        try:
            create_notification(
                notification_type='sync_error',
                title='Last.fm sync failed: Database error',
                message=f'Database error occurred during sync: {str(exc)}',
                details={'error': str(exc), 'error_type': 'sqlite3.Error'},
                severity='error'
            )
        except Exception as notify_err:
            logger.error(f"Failed to create notification: {notify_err}")
    except Exception as exc:
        logger.error(f"Unexpected error during sync: {exc}", exc_info=True)
        try:
            create_notification(
                notification_type='sync_error',
                title='Last.fm sync failed: Unexpected error',
                message=f'An unexpected error occurred: {str(exc)}',
                details={'error': str(exc), 'error_type': type(exc).__name__, 'traceback': traceback.format_exc()},
                severity='critical'
            )
        except Exception as notify_err:
            logger.error(f"Failed to create notification: {notify_err}")
        raise
