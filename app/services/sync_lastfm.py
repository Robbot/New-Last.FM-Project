#!/usr/bin/env python3
"""
Sync Last.fm scrobbles into SQLite.

- Uses API key + username from config.ini via config.get_api_key()
- Stores uts as INTEGER Unix timestamp in SECONDS (UTC)
- Inserts scrobbles in chronological order (oldest -> newest)
- Avoids duplicates via UNIQUE index on (uts, artist, album, track)
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
from app.db.notifications import create_notification, ensure_notifications_table

# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Time chunk size for fetching scrobbles (in seconds)
# Using smaller chunks with both from/to ensures no scrobbles are missed
# 7 days = 7 * 24 * 60 * 60 = 604800 seconds
TIME_CHUNK_SECONDS = 604800  # 7 days

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


# ---------- DB helpers ----------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _is_album_compilation(conn: sqlite3.Connection, album: str, album_mbid: str | None, current_artist: str) -> bool:
    """
    Check if an album is a compilation by examining existing scrobbles.

    An album is considered a compilation if:
    1. album_mbid is NOT NULL AND it has 2+ distinct artists in existing scrobbles, OR
    2. album_mbid is NOT NULL AND it has 1+ existing scrobbles by a different artist

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
    if not album or album_mbid is None:
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

    # If we already have 2+ distinct artists, it's definitely a compilation
    if existing_artist_count >= 2:
        return True

    # If we have 1 existing artist and it's different from current artist, it's a compilation
    if existing_artist_count == 1:
        cursor = conn.execute(
            """
            SELECT DISTINCT artist
            FROM scrobble
            WHERE album = ? AND album_mbid = ?
            LIMIT 1
            """,
            (album, album_mbid)
        )
        row = cursor.fetchone()
        if row and row["artist"] != current_artist:
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

    # Unique scrobble key: one row per (time, artist, album, track)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scrobble_unique
        ON scrobble(uts, artist, album, track);
    """)

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
    A compilation is defined as an album with 2+ distinct artists.
    Albums are identified by (album, album_mbid) to distinguish different
    albums that happen to have the same name (e.g., "21" by Adele vs "21" by KSU).

    IMPORTANT: Only considers albums with a non-NULL album_mbid to avoid
    incorrectly flagging different artists' albums with the same name as compilations.
    """
    # Find all (album, album_mbid) combinations that should be compilations
    # Only consider albums with non-NULL album_mbid to avoid false positives
    # from different artists having albums with the same name
    cursor = conn.execute(
        """
        SELECT album, album_mbid
        FROM scrobble
        WHERE album IS NOT NULL AND album != '' AND album_mbid IS NOT NULL
        GROUP BY album, album_mbid
        HAVING COUNT(DISTINCT artist) >= 2
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
    conn.commit()
    logger.info(
        f"Updated album_artist to 'Various Artists' for {updated} scrobbles "
        f"across {len(compilation_albums)} compilation albums."
    )


# ---------- Sync logic ----------

def sync_lastfm() -> None:
    api_key, username = get_api_key()
    logger.info(f"Starting Last.fm sync for user: {username}")

    conn = get_conn()
    ensure_schema(conn)

    last_uts = get_last_uts(conn)
    logger.info(f"Last known timestamp in database: {last_uts} ({time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(last_uts))} UTC)")

    # Avoid inclusive-from duplicates: Last.fm returns uts >= from
    from_ts = None if last_uts == 0 else last_uts + 1

    # Use time chunks to ensure no scrobbles are missed
    # Last.fm API has known issues with 'from' only - using both from+to is more reliable
    now_ts = int(time.time())
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

            scrobble_batch: list[tuple] = []
            album_batch: list[dict] = []
            current_ts = int(time.time())

            for t in tracks:
                # Skip "now playing" items (not yet scrobbled)
                if "@attr" in t and t["@attr"].get("nowplaying") == "true":
                    continue

                date_info = t.get("date")
                if not date_info:
                    continue

                uts = int(date_info["uts"])  # Last.fm gives seconds

                # Sanity: if somehow ms sneaks in, normalize to seconds
                if uts > 2_000_000_000:
                    uts //= 1000

                artist_name = t["artist"]["#text"]
                artist_mbid = t["artist"].get("mbid") or None

                if isinstance(t.get("album"), dict):
                    album_name = clean_title(t["album"]["#text"])
                    album_mbid = t["album"].get("mbid") or None
                else:
                    album_name = clean_title(t.get("album", ""))
                    album_mbid = None

                # Apply album name mappings (for known incorrect album names)
                album_name = clean_album_name(artist_name, album_name)

                if album_mbid == "":
                    album_mbid = None

                # Clean track name with Spotify-specific mappings
                track_name = clean_title(t["name"], artist_name, album_name)
                track_mbid = t.get("mbid") or None

                # ---------- Album Validation ----------
                # Check if album name is suspicious (might be a track name)
                # and try to find the correct album
                from .validate_albums import (
                    is_album_name_suspicious,
                    validate_and_correct_album,
                    log_data_quality_issue
                )

                corrected_album = None
                if album_name and is_album_name_suspicious(album_name, track_name, artist_name):
                    is_valid, correct_album, confidence = validate_and_correct_album(
                        artist_name,
                        album_name,
                        track_name,
                        artist_mbid,
                        auto_correct=True  # Auto-correct during sync
                    )

                    if not is_valid and correct_album:
                        corrected_album = correct_album
                        album_name = correct_album

                        # Log the correction for tracking
                        log_data_quality_issue(
                            artist_name,
                            f"(was: {album_name})",
                            track_name,
                            correct_album,
                            confidence,
                            auto_corrected=True
                        )

                        logger.info(f"Auto-corrected album for {artist_name} - {track_name}: '{correct_album}' (confidence: {confidence}%)")

                # Determine album_artist: check if album is a compilation
                # by looking at existing scrobbles in the database
                if _is_album_compilation(conn, album_name, album_mbid, artist_name):
                    album_artist = "Various Artists"
                else:
                    album_artist = artist_name

                # ---------- Track Validation ----------
                # Check if track name matches existing album_tracks data
                track_validation = validate_scrobble_track(
                    conn, artist_name, album_name, track_name, track_mbid
                )

                if not track_validation['is_valid']:
                    # Create warning notification
                    create_notification(
                        notification_type='track_mismatch',
                        title=f'Track mismatch: {artist_name} - {track_name}',
                        message=f'Scrobble track "{track_name}" does not match any track in album_tracks for {artist_name} - {album_name}',
                        details={
                            'artist': artist_name,
                            'album': album_name,
                            'scrobble_track': track_name,
                            'track_mbid': track_mbid,
                            'album_tracks': track_validation.get('album_tracks', [])
                        },
                        severity='warning'
                    )
                    logger.warning(f'Track mismatch: {artist_name} - {album_name} - "{track_name}"')
                elif track_validation['issue_type'] == 'normalized_match':
                    # Track names differ but normalize the same - log for review
                    logger.info(f'Track name variation: "{track_name}" → "{track_validation["matched_track"]}" for {artist_name} - {album_name}')

                scrobble_batch.append(
                    (artist_name, artist_mbid, album_name,
                     album_mbid, track_name, track_mbid, uts,
                     album_artist,  # Set based on compilation detection
                     'lastfm')     # source = 'lastfm' for Last.fm API scrobbles
                )

                # Collect album_art info for ALL albums (with or without MBID)
                if album_name:  # Only skip if album name is missing/empty
                    images = t.get("image", []) or []
                    img_small = img_medium = img_large = img_xlarge = None

                    for img in images:
                        url = img.get("#text") or None
                        size = img.get("size")
                        if not url:
                            continue
                        if size == "small":
                            img_small = url
                        elif size == "medium":
                            img_medium = url
                        elif size == "large":
                            img_large = url
                        elif size in ("extralarge", "mega"):
                            img_xlarge = url

                    # Only add to batch if we have at least one image URL
                    if img_small or img_medium or img_large or img_xlarge:
                        album_batch.append({
                            "artist": artist_name,
                            "album": album_name,
                            "album_mbid": album_mbid,
                            "artist_mbid": artist_mbid,
                            "image_small": img_small,
                            "image_medium": img_medium,
                            "image_large": img_large,
                            "image_xlarge": img_xlarge,
                            "last_updated": current_ts,
                        })

            if not scrobble_batch:
                logger.debug(f"No scrobbles on page {page} of chunk {chunks_processed}")
                break

            pages_with_data += 1

            # 🔢 Sort scrobbles chronologically (oldest → newest) before insert
            scrobble_batch.sort(key=lambda row: row[6])  # row[6] = uts

            cur = conn.cursor()
            cur.executemany(
                """
                INSERT OR IGNORE INTO scrobble
                    (artist, artist_mbid, album, album_mbid,
                     track, track_mbid, uts, album_artist, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                scrobble_batch,
            )
            conn.commit()

            new_rows = conn.total_changes - total_new_scrobbles
            skipped_rows = len(scrobble_batch) - new_rows
            total_new_scrobbles = conn.total_changes
            chunk_new_scrobbles += new_rows
            logger.info(
                f"Chunk {chunks_processed}, page {page}: inserted {new_rows} new scrobbles "
                f"(batch size {len(scrobble_batch)})"
            )

            # Log skipped inserts as notification
            if skipped_rows > 0:
                create_notification(
                    notification_type='sync_skip',
                    title=f'{skipped_rows} scrobble(s) skipped during sync',
                    message=f'Chunk {chunks_processed}, page {page}: {skipped_rows} of {len(scrobble_batch)} scrobbles were not inserted. This usually means they already exist in the database with different data (possible data inconsistency).',
                    details={
                        'chunk': chunks_processed,
                        'page': page,
                        'batch_size': len(scrobble_batch),
                        'inserted': new_rows,
                        'skipped': skipped_rows,
                        'timestamp': int(time.time())
                    },
                    severity='warning'
                )
                logger.warning(f'{skipped_rows} scrobbles skipped (likely duplicates or data conflicts)')

            # Optional: sort album_art batch by (artist, album) then time
            if album_batch:
                album_batch.sort(key=lambda a: (a["artist"], a["album"], a["last_updated"]))
                for a in album_batch:
                    cur.execute(
                        """
                        INSERT INTO album_art (
                            artist, album, album_mbid, artist_mbid,
                            image_small, image_medium, image_large, image_xlarge,
                            last_updated
                        )
                        VALUES (
                            :artist, :album, :album_mbid, :artist_mbid,
                            :image_small, :image_medium, :image_large, :image_xlarge,
                            :last_updated
                        )
                        ON CONFLICT(artist, album) DO UPDATE SET
                            album_mbid      = COALESCE(excluded.album_mbid, album_art.album_mbid),
                            artist_mbid     = COALESCE(excluded.artist_mbid, album_art.artist_mbid),
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

        # Move to next chunk
        chunk_start = chunk_end + 1

    # Post-sync: final update album_artist for compilation albums
    if total_new_scrobbles > 0:
        logger.info("Post-sync: final compilation album detection...")
        _update_compilation_albums(conn)

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
