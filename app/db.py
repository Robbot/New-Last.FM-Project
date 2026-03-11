import sqlite3
import re
import logging
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import current_app, url_for
from datetime import datetime, timezone, timedelta
from contextlib import contextmanager
import unicodedata
import io
import struct


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

logger = logging.getLogger(__name__)


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


def get_db_connection() ->sqlite3.Connection:
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

def get_album_release_year(album_artist_name: str, album_name: str, table: str = "album_art", col: str ="year_col") -> str | None:
    conn = get_db_connection()
    try:
        row = conn.execute(
            f"""
            SELECT {col}
            FROM {table}
            WHERE artist = ?
              AND album  = ?
            LIMIT 1
            """,
            (album_artist_name, album_name),
        ).fetchone()
        if not row:
            return None
        y = row[col]
        return str(y) if y is not None else None
    finally:
        conn.close()


def get_latest_scrobbles(start: str = "", end: str = ""):
    conn = get_db_connection()

    sql = """
        SELECT artist,
               album,
               album_artist,
               track,
               strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ WHERE date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Order chronologically when filtering by date, reverse chronologically otherwise
    if start and end:
        sql += " ORDER BY uts ASC"
    else:
        sql += " ORDER BY uts DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def average_scrobbles_per_day():
    conn = get_db_connection()
    row = conn.execute(
        """
        WITH bounds AS (
            SELECT
                MIN(uts) AS first_ts,
                MAX(uts) AS last_ts
            FROM scrobble
        ),
        calc AS (
            SELECT
                (SELECT COUNT(*) FROM scrobble) * 1.0
                / ((last_ts - first_ts) / 86400.0 + 1)
                AS per_day
            FROM bounds
        )
        SELECT ROUND(per_day) AS per_day_rounded
        FROM calc;
        """
    ).fetchone()
    conn.close()
    # row is a sqlite3.Row like {'per_day_rounded': 24}
    if row is None:
        return 0

    # either of these is fine, depending on your preference:
    # return int(row[0])
    return int(row["per_day_rounded"])

def get_artist_overview(artist_name: str):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*)               AS scrobbles,
            COUNT(DISTINCT album)  AS albums,
            COUNT(DISTINCT track)  AS tracks
        FROM scrobble
        WHERE artist = ?
        """,
        (artist_name,),
    ).fetchone()
    conn.close()

    if row is None or row["scrobbles"] == 0:
        return None

    return {
        "scrobbles": row["scrobbles"],
        "albums": row["albums"],
        "tracks": row["tracks"],
    }

def get_library_stats():
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT artist) AS total_artists,
               COUNT(*) AS total_scrobbles
        FROM scrobble
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_artists": 0, "total_scrobbles": 0}

    return {
        "total_artists": row["total_artists"],
        "total_scrobbles": row["total_scrobbles"]
    }

def get_artist_stats(artist_name: str, start: str = "", end: str = ""):
    conn = get_db_connection()

    sql = """
        SELECT
            COUNT(*) AS scrobbles,
            COUNT(DISTINCT album) AS albums,
            COUNT(DISTINCT track) AS tracks
        FROM scrobble
        WHERE artist = ?
    """

    params = [artist_name]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def get_artist_position(artist_name: str, start: str = "", end: str = "") -> int:
    """
    Returns the artist's position (rank) in the list of most played artists.
    Position 1 = most played artist.
    Returns None if artist not found.
    """
    conn = get_db_connection()

    sql = """
        SELECT artist, COUNT(*) AS scrobbles
        FROM scrobble
    """

    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ WHERE date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += " GROUP BY artist ORDER BY scrobbles DESC"

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Find the artist's position
    for position, row in enumerate(rows, start=1):
        if row["artist"] == artist_name:
            return position

    return None


def get_top_tracks_for_artist(
        artist_name: str,
        start: str = "",
        end: str = "",
        limit: int = 50
    ):

    conn = get_db_connection()

    sql = """
        SELECT
            artist,
            track,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
    """
    params = [artist_name]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += """
        GROUP BY artist, track
        ORDER BY plays DESC, track ASC
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_artists_details(start: str = "", end: str = "", sort_by: str = "plays", sort_order: str = "desc", search_term: str = ""):
    conn = get_db_connection()

    print(f"DB get_artists_details - Input: start={start}, end={end}, sort_by={sort_by}, sort_order={sort_order}, search_term={search_term}")

    # Validate sort_by and sort_order
    valid_sort_columns = {"rank", "artist", "plays", "tracks"}
    valid_sort_orders = {"asc", "desc"}

    if sort_by not in valid_sort_columns:
        sort_by = "plays"
    if sort_order not in valid_sort_orders:
        sort_order = "desc"

    sql = """
        SELECT artist, COUNT(*) AS plays, COUNT(DISTINCT track) AS tracks
        FROM scrobble
    """
    params = []
    where_conditions = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        where_conditions.append("date(uts, 'unixepoch', 'localtime') >= ?")
        where_conditions.append("date(uts, 'unixepoch', 'localtime') <= ?")
        params.extend([start, end])
        print(f"DB get_artists_details - Using date filter")

    # Search filter - case-insensitive partial matching on artist name
    if search_term:
        where_conditions.append("LOWER(artist) LIKE ?")
        params.append(f"%{search_term.lower()}%")
        print(f"DB get_artists_details - Using search filter: {search_term}")

    if where_conditions:
        sql += " WHERE " + " AND ".join(where_conditions)
    else:
        print(f"DB get_artists_details - NO filters applied")

    sql += " GROUP BY artist"

    # Apply sorting
    if sort_by == "artist":
        sql += f" ORDER BY artist {sort_order.upper()}"
    elif sort_by == "tracks":
        sql += f" ORDER BY tracks {sort_order.upper()}, artist ASC"
    else:  # plays or rank (default)
        sql += f" ORDER BY plays {sort_order.upper()}, artist ASC"

    rows = conn.execute(sql, params).fetchall()
    print(f"DB get_artists_details - Returned {len(rows)} rows")
    conn.close()
    return rows


def get_artist_albums(album_artist_name: str, start: str = "", end: str = ""):
    conn = get_db_connection()

    sql = """
        SELECT
            album,
            album_artist,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
    """
    params = [album_artist_name]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += """
        GROUP BY album
        ORDER BY plays DESC, album ASC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_artist_tracks(artist_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            track,
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
        GROUP BY track, album
        ORDER BY plays DESC
        """,
        (artist_name,),
    ).fetchall()
    conn.close()
    return rows

def get_album_stats():
    """Total distinct albums and total album scrobbles."""
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT album) AS total_albums,
            COUNT(*)              AS total_scrobbles
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_albums": 0, "total_scrobbles": 0}

    return {
        "total_albums": row["total_albums"],
        "total_scrobbles": row["total_scrobbles"],
    }

def get_top_albums(start: str = "", end: str = "", search_term: str = ""):
    """Albums sorted by plays (scrobbles) desc."""
    conn = get_db_connection()

    sql = """
        SELECT
            album,
            artist,
            album_artist,
            COUNT(*) AS plays
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Search filter - case-insensitive partial matching on album, artist, or album_artist
    if search_term:
        sql += """ AND (LOWER(album) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(album_artist) LIKE ?)"""
        search_pattern = f"%{search_term.lower()}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    sql += """
        GROUP BY album, artist, album_artist
        ORDER BY plays DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_track_stats():
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT track) AS total_tracks,
            COUNT(*) AS total_scrobbles
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_tracks": 0, "total_scrobbles": 0}
    return {
        "total_tracks": row["total_tracks"],
        "total_scrobbles": row["total_scrobbles"]
    }

def get_track_stats_detail(artist_name: str, track_name: str):
    conn = get_db_connection()
    row = conn.execute(
         """
        SELECT
            COUNT(*) AS plays
        FROM scrobble
        WHERE lower(trim(artist)) = lower(trim(?))
          AND lower(replace(replace(replace(trim(track), '\\!', '!'), '\\?', '?'), '\\[', '[')) = lower(trim(?))
        """,
        (artist_name, track_name),
    ).fetchone()
    conn.close()
    return row

def get_recent_scrobbles_for_track(artist_name: str, track_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            album_artist,
            track,
            strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        WHERE
            LOWER(TRIM(artist)) = LOWER(TRIM(?))
            AND LOWER(replace(replace(replace(trim(track), '\\!', '!'), '\\?', '?'), '\\[', '[')) = LOWER(TRIM(?))
        ORDER BY uts DESC
        """,
        (artist_name, track_name),
    ).fetchall()
    conn.close()
    return rows


def get_top_tracks(start: str = "", end: str = "", search_term: str = ""):
    """Tracks sorted by plays (scrobbles) desc.

    Groups by track AND artist to correctly handle tracks with the same name
    by different artists. For compilations (Various Artists), shows the
    original artist instead when available.
    """
    conn = get_db_connection()

    # Use a CTE to first normalize the artist for each scrobble, then group
    sql = """
        WITH normalized_scrobbles AS (
            SELECT
                track,
                -- Prefer non-Various Artists as the primary artist
                COALESCE(
                    CASE WHEN LOWER(artist) != 'various artists' THEN artist END,
                    CASE WHEN LOWER(album_artist) != 'various artists' THEN album_artist END,
                    artist
                ) AS primary_artist,
                album_artist,
                album,
                uts
            FROM scrobble
            WHERE track IS NOT NULL AND track != ''
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Search filter - case-insensitive partial matching on track or artist
    # Need to search in the original artist field too
    if search_term:
        sql += """ AND (LOWER(track) LIKE ? OR LOWER(artist) LIKE ? OR LOWER(album_artist) LIKE ?)"""
        search_pattern = f"%{search_term.lower()}%"
        params.extend([search_pattern, search_pattern, search_pattern])

    sql += """
        )
        SELECT
            track,
            primary_artist AS artist,
            MAX(album_artist) AS album_artist,
            MAX(album) AS album,
            COUNT(*) AS plays
        FROM normalized_scrobbles
        GROUP BY track, primary_artist
        ORDER BY plays DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_track_overview(artist_name: str, track_name: str):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS plays,
            COUNT(DISTINCT album) AS albums
        FROM scrobble
        WHERE
            LOWER(TRIM(artist)) = LOWER(TRIM(?))
            AND LOWER(TRIM(track)) = LOWER(TRIM(?))
        """,
        (artist_name, track_name),
    ).fetchone()
    conn.close()

    if row is None or row["plays"] == 0:
        return None

    return {
        "plays": row["plays"],
        "albums": row["albums"],
    }


    # Total album plays
def get_album_total_plays(album_artist_name, album_name, start: str = "", end: str = ""):

    conn = get_db_connection()

    sql = """
        SELECT COUNT(*) AS total
        FROM scrobble
        WHERE album_artist = ?
          AND album  = ?
    """
    params = [album_artist_name, album_name]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()

    return row["total"] if row else 0

    # 3) Album art lookup from album_art table
def get_album_art(album_artist_name, album_name):

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT album_mbid, image_xlarge
        FROM album_art
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (album_artist_name, album_name),
    ).fetchone()
    conn.close()
    return rows

def album_tracks_exist(album_artist_name, album_name):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT 1
        FROM album_tracks
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (album_artist_name, album_name),
    ).fetchone()
    return row is not None

def upsert_album_tracks(album_artist_name, album_name, tracks):
    """
    tracks = list of dicts:
      [{"track": "The Grudge", "track_number": 1}, ...]
    """
    conn = get_db_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO album_tracks (artist, album, track, track_number)
        VALUES (?, ?, ?, ?)
        """,
        [(album_artist_name, album_name, t["track"], t["track_number"]) for t in tracks],
    )
    conn.commit()

def get_album_tracks(album_artist_name: str, album_name: str, start: str = "", end: str = "", sort_by: str = "tracklist"):
    """
    Returns exactly ONE row per track, ordered by album track number (default)
    or by play count (if sort_by='plays'), with correct play counts.

    Uses Python-based normalization for track name matching instead of complex SQL REPLACE functions.
    """
    conn = get_db_connection()

    # Normalize the album name for fuzzy matching
    normalized_album = _normalize_for_matching(album_name)

    # For Various Artists compilations, query by album name only (not by artist)
    is_various_artists = album_artist_name.lower() in ("various artists", "various artist")

    # Step 1: Find all album name variations in album_tracks that match the normalized name
    if is_various_artists:
        album_track_albums = conn.execute(
            """
            SELECT DISTINCT album
            FROM album_tracks
            WHERE album = ?
            """,
            (album_name,),
        ).fetchall()
    else:
        album_track_albums = conn.execute(
            """
            SELECT DISTINCT album
            FROM album_tracks
            WHERE artist = ?
            """,
            (album_artist_name,),
        ).fetchall()

    # Find the canonical album_tracks album name (first match)
    canonical_album = None
    for row in album_track_albums:
        if _normalize_for_matching(row["album"]) == normalized_album:
            canonical_album = row["album"]
            break

    # If no exact normalized match, try exact match first
    if canonical_album is None:
        for row in album_track_albums:
            if row["album"] == album_name:
                canonical_album = row["album"]
                break

    # If still no match, use the provided album_name and return empty results
    if canonical_album is None:
        conn.close()
        return []

    # Step 2: Get all album_tracks for this album
    # For Various Artists, prefer entries with actual track artists over "Various Artists"
    if is_various_artists:
        album_tracks = conn.execute(
            """
            SELECT track_number, track, artist
            FROM album_tracks
            WHERE album = ?
              AND rowid IN (
                  SELECT rowid
                  FROM (
                      SELECT rowid,
                             ROW_NUMBER() OVER (
                                 PARTITION BY track_number, track
                                 ORDER BY CASE WHEN artist != 'Various Artists' THEN 0 ELSE 1 END, rowid
                             ) as rn
                      FROM album_tracks
                      WHERE album = ?
                  )
                  WHERE rn = 1
              )
            ORDER BY track_number ASC
            """,
            (canonical_album, canonical_album),
        ).fetchall()
    else:
        album_tracks = conn.execute(
            """
            SELECT track_number, track
            FROM album_tracks
            WHERE artist = ? AND album = ?
            ORDER BY track_number ASC
            """,
            (album_artist_name, canonical_album),
        ).fetchall()

    # Step 3: Find all scrobble albums that match the normalized album name
    all_scrobble_albums = conn.execute(
        """
        SELECT DISTINCT album
        FROM scrobble
        WHERE album_artist = ?
        """,
        (album_artist_name,),
    ).fetchall()

    # Get all matching scrobble album names
    matching_album_names = [album_name]  # Start with the input album
    for row in all_scrobble_albums:
        if _normalize_for_matching(row["album"]) == normalized_album and row["album"] != album_name:
            matching_album_names.append(row["album"])

    # Step 4: Get scrobble play counts for all matching albums (with optional date filtering)
    placeholders = ','.join(['?' for _ in matching_album_names])
    scrobble_query = f"""
        SELECT track, artist, COUNT(*) AS plays
        FROM scrobble
        WHERE album_artist = ?
          AND album IN ({placeholders})
    """
    scrobble_params = [album_artist_name] + matching_album_names

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        scrobble_query += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                               AND date(uts, 'unixepoch', 'localtime') <= ?"""
        scrobble_params.extend([start, end])

    scrobble_query += " GROUP BY track, artist"

    scrobbles = conn.execute(scrobble_query, scrobble_params).fetchall()

    conn.close()

    # Step 5: Match album_tracks with scrobbles using Python normalization
    # Build a dict of normalized track names to scrobble data
    # Key: normalized_track_name, Value: [(track, artist, plays), ...]
    scrobble_dict = {}
    for scrobble in scrobbles:
        normalized = _normalize_track_name_for_matching(scrobble["track"])
        key = (normalized, scrobble["artist"])
        if key not in scrobble_dict:
            scrobble_dict[key] = []
        scrobble_dict[key].append(scrobble)

    # Match album_tracks with scrobbles and build results
    results = []
    for track in album_tracks:
        normalized_track = _normalize_track_name_for_matching(track["track"])

        # For Various Artists, use the track artist from album_tracks directly
        if is_various_artists and "artist" in track.keys():
            track_artist = track["artist"]
            # Try to find matching scrobbles for this specific track + artist
            plays = 0
            key = (normalized_track, track_artist)
            if key in scrobble_dict:
                plays = sum(s["plays"] for s in scrobble_dict[key])
        else:
            # For regular albums, try to find a matching scrobble (prefer same artist, fall back to any artist)
            track_artist = album_artist_name
            plays = 0

            # First try with the album artist
            key_with_artist = (normalized_track, album_artist_name)
            if key_with_artist in scrobble_dict:
                plays = sum(s["plays"] for s in scrobble_dict[key_with_artist])
                # Use the first matching track name for display
                if scrobble_dict[key_with_artist]:
                    track_artist = scrobble_dict[key_with_artist][0]["artist"]
            else:
                # Try without artist restriction (for compilations)
                for key, scrobble_list in scrobble_dict.items():
                    if key[0] == normalized_track:
                        total_plays = sum(s["plays"] for s in scrobble_list)
                        if total_plays > plays:
                            plays = total_plays
                            track_artist = scrobble_list[0]["artist"]

        results.append({
            "track_number": track["track_number"],
            "track_name": track["track"],
            "track_artist": track_artist,
            "plays": plays,
        })

    # Sort by play count if requested
    if sort_by == "plays":
        results.sort(key=lambda x: (-x["plays"], x["track_number"]))

    # Convert to sqlite3.Row-like objects for compatibility
    class Row:
        def __init__(self, data):
            self._data = data
        def __getitem__(self, key):
            return self._data[key]
        def keys(self):
            return self._data.keys()
        def __iter__(self):
            return iter(self._data.values())

    return [Row(r) for r in results]

def _safe_slug(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]


def get_track_gaps(start: str = "", end: str = ""):
    """Tracks sorted by time since last play (longest gap first)."""
    conn = get_db_connection()

    # Normalize escaped characters in track names for proper grouping
    # Handles \!, \?, \[, \] etc. so "Muka!" and "Muka\!" are treated as same track
    # CHAR(92) is backslash - we remove all backslashes to normalize escaped characters
    normalized_track = "TRIM(REPLACE(REPLACE(REPLACE(REPLACE(track, CHAR(92), ''), CHAR(92), ''), CHAR(92), ''), CHAR(92), ''))"

    sql = f"""
        SELECT
            {normalized_track} AS track,
            artist,
            album,
            album_artist,
            MAX(uts) AS last_play_uts,
            COUNT(*) AS plays
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += f"""
        GROUP BY {normalized_track}, artist, album, album_artist
        ORDER BY last_play_uts ASC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Calculate seconds since last play for each track
    current_ts = int(datetime.now(timezone.utc).timestamp())
    result = []
    for row in rows:
        result.append({
            "track": row["track"],
            "artist": row["artist"],
            "album": row["album"],
            "album_artist": row["album_artist"],
            "last_play_uts": row["last_play_uts"],
            "plays": row["plays"],
            "seconds_since": current_ts - row["last_play_uts"],
        })

    return result

def _guess_ext_from_url(url: str) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"

def get_album_wikipedia_url(album_artist_name: str, album_name: str) -> str | None:
    """Get the Wikipedia URL for an album from the database."""
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT wikipedia_url
            FROM album_art
            WHERE artist = ?
              AND album  = ?
            LIMIT 1
            """,
            (album_artist_name, album_name),
        ).fetchone()
        if row and row["wikipedia_url"]:
            return row["wikipedia_url"]
        return None
    finally:
        conn.close()


def set_album_wikipedia_url(album_artist_name: str, album_name: str, wikipedia_url: str) -> bool:
    """Set the Wikipedia URL for an album in the database."""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE album_art
            SET wikipedia_url = ?
            WHERE artist = ?
              AND album  = ?
            """,
            (wikipedia_url, album_artist_name, album_name),
        )
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()


def ensure_album_art_cached(album_artist_name: str, album_name: str) -> str | None:
    """
    - Looks up album_art.image_xlarge for (artist_name, album_name)
    - Downloads it once into: <app static>/covers/<key>.<ext>
    - Returns a local static URL to be used in templates
    """
    conn = get_db_connection()

    art_row = conn.execute(
        """
        SELECT album_mbid, image_xlarge
        FROM album_art
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (album_artist_name, album_name),
    ).fetchone()

    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""
    cdn_url = (art_row["image_xlarge"] or "").strip() if art_row else ""

    # Prefer MBID for stable filename; otherwise slug artist+album
    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"

    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Check if any local file exists with this cache key (regardless of extension)
    # This handles the case where a user uploaded a cover with a different extension
    # than what's stored in the database (e.g., uploaded .jpg but DB has .png URL)
    # It also handles the case where a cover was uploaded but no album_art row exists
    logger.debug(f"ensure_album_art_cached: cache_key={cache_key}, static_folder={current_app.static_folder}")
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        abs_path = covers_abs_dir / f"{cache_key}{ext}"
        logger.debug(f"  Checking: {abs_path}, exists={abs_path.exists()}")
        if abs_path.exists() and abs_path.stat().st_size > 0:
            logger.debug(f"  Found local file: {cache_key}{ext}")
            return url_for("static", filename=f"covers/{cache_key}{ext}")

    # No local file found, proceed to download from CDN if available
    if not cdn_url:
        return None

    # No local file found, proceed to download
    ext = _guess_ext_from_url(cdn_url)
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    # Download once
    try:
        r = requests.get(
            cdn_url,
            timeout=12,
            stream=True,
            headers={"User-Agent": "Scrobbles/1.0"},
        )
        if r.status_code != 200:
            return None

        # Refine extension from Content-Type if needed
        ct = (r.headers.get("Content-Type") or "").lower()
        if "image/png" in ct:
            ext = ".png"
        elif "image/webp" in ct:
            ext = ".webp"
        elif "image/jpeg" in ct or "image/jpg" in ct:
            ext = ".jpg"

        filename = f"{cache_key}{ext}"
        abs_path = covers_abs_dir / filename

        with open(abs_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 64):
                if chunk:
                    f.write(chunk)

        if abs_path.exists() and abs_path.stat().st_size > 0:
            return url_for("static", filename=f"covers/{filename}")

        return None

    except requests.RequestException:
        return None


def save_uploaded_cover(album_artist_name: str, album_name: str, file_storage) -> dict:
    """
    Save an uploaded album cover image.

    Validates the file is an image, resizes to 220x220px, converts to JPG,
    and saves to the covers directory.

    Args:
        album_artist_name: The artist name
        album_name: The album name
        file_storage: Flask FileStorage object from request.files

    Returns:
        dict with "cover_url" on success, or {"error": "message"} on failure
    """
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
    ALLOWED_MIME_TYPES = {"image/jpeg", "image/jpg", "image/png", "image/webp"}
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    TARGET_SIZE = (220, 220)

    try:
        # Check file extension
        filename = file_storage.filename or ""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return {"error": f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"}

        # Check MIME type
        content_type = (file_storage.content_type or "").lower()
        if content_type not in ALLOWED_MIME_TYPES:
            return {"error": f"Invalid content type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}"}

        # Read file content
        file_content = file_storage.read()

        # Check file size
        if len(file_content) > MAX_FILE_SIZE:
            return {"error": f"File too large. Maximum size: {MAX_FILE_SIZE // (1024*1024)}MB"}

        # Validate it's actually an image by checking magic bytes
        if not _is_valid_image(file_content):
            return {"error": "File is not a valid image or is corrupted"}

        # Try to import Pillow for image processing
        try:
            from PIL import Image
        except ImportError:
            # Pillow not available - save as-is (will still have validated it's an image)
            logger.warning("Pillow not installed, saving cover without resizing/conversion")
            return _save_cover_as_is(album_artist_name, album_name, file_content, ext)

        # Process image with Pillow
        image = Image.open(io.BytesIO(file_content))

        # Convert to RGB (for PNG with alpha channel, etc.)
        if image.mode in ("RGBA", "LA", "P"):
            # Create white background for transparent images
            background = Image.new("RGB", image.size, (255, 255, 255))
            if image.mode == "P":
                image = image.convert("RGBA")
            if image.mode in ("RGBA", "LA"):
                background.paste(image, mask=image.split()[-1])  # Use alpha channel as mask
                image = background
            else:
                image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")

        # Resize to target size using high-quality resampling
        # Only resize if larger than target to avoid upscaling small images
        if image.width > TARGET_SIZE[0] or image.height > TARGET_SIZE[1]:
            image.thumbnail(TARGET_SIZE, Image.Resampling.LANCZOS)

        # Create canvas for exact 220x220 (center the image)
        final_image = Image.new("RGB", TARGET_SIZE, (255, 255, 255))
        paste_x = (TARGET_SIZE[0] - image.width) // 2
        paste_y = (TARGET_SIZE[1] - image.height) // 2
        final_image.paste(image, (paste_x, paste_y))

        # Save as JPG
        output = io.BytesIO()
        final_image.save(output, format="JPEG", quality=90, optimize=True)
        jpg_content = output.getvalue()

        # Save to file
        return _save_cover_to_disk(album_artist_name, album_name, jpg_content, ".jpg")

    except Exception as e:
        logger.error(f"Error processing uploaded cover: {e}", exc_info=True)
        return {"error": "Failed to process image"}


def _is_valid_image(file_content: bytes) -> bool:
    """
    Validate file is an actual image using magic bytes.
    This prevents uploading non-image files with image extensions.
    """
    # Magic bytes for common image formats
    magic_bytes = {
        b"\xFF\xD8\xFF": "jpg",  # JPEG
        b"\x89\x50\x4E\x47\x0D\x0A\x1A\x0A": "png",  # PNG
        b"RIFF": "webp",  # WEBP (RIFF...WEBP)
    }

    if len(file_content) < 8:
        return False

    # Check each magic byte pattern
    for magic, fmt in magic_bytes.items():
        if file_content.startswith(magic):
            # For WEBP, need to verify the WEBP marker
            if fmt == "webp" and len(file_content) >= 12:
                return file_content[8:12] == b"WEBP"
            return True

    return False


def _save_cover_as_is(album_artist_name: str, album_name: str, file_content: bytes, ext: str) -> dict:
    """Save cover image without processing (Pillow not available fallback)."""
    # Normalize extension
    if ext == ".jpeg":
        ext = ".jpg"

    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Use same naming scheme as ensure_album_art_cached
    art_row = get_album_art(album_artist_name, album_name)
    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""

    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    with open(abs_path, "wb") as f:
        f.write(file_content)

    if abs_path.exists() and abs_path.stat().st_size > 0:
        return {"cover_url": url_for("static", filename=f"covers/{filename}")}

    return {"error": "Failed to save image"}


def _save_cover_to_disk(album_artist_name: str, album_name: str, file_content: bytes, ext: str) -> dict:
    """Save processed cover image to disk."""
    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    # Use same naming scheme as ensure_album_art_cached
    art_row = get_album_art(album_artist_name, album_name)
    album_mbid = (art_row["album_mbid"] or "").strip() if art_row else ""

    cache_key = album_mbid if album_mbid else f"{_safe_slug(album_artist_name)}__{_safe_slug(album_name)}"
    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    with open(abs_path, "wb") as f:
        f.write(file_content)

    if abs_path.exists() and abs_path.stat().st_size > 0:
        return {"cover_url": url_for("static", filename=f"covers/{filename}")}

    return {"error": "Failed to save image"}