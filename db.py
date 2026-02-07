import sqlite3
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import current_app, url_for
from datetime import datetime, timezone, timedelta
import unicodedata


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


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

    # Replace hyphens with spaces (important for "Four-Calendar" → "Four Calendar")
    text = re.sub(r'[–—\-]+', ' ', text)

    # Remove common punctuation and special chars
    text = re.sub(r'[\'".,:;!?(){}\[\]<>/]+', '', text)

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

def get_db_connection() ->sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def get_album_release_year(artist_name: str, album_name: str, table: str = "album_art", col: str ="year_col") -> str | None:
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
            (artist_name, album_name),
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

def get_artists_details(start: str = "", end: str = "", sort_by: str = "plays", sort_order: str = "desc"):
    conn = get_db_connection()

    print(f"DB get_artists_details - Input: start={start}, end={end}, sort_by={sort_by}, sort_order={sort_order}")

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

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ WHERE date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])
        print(f"DB get_artists_details - Using date filter")
    else:
        print(f"DB get_artists_details - NO date filter applied")

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


def get_artist_albums(artist_name: str, start: str = "", end: str = ""):
    conn = get_db_connection()

    sql = """
        SELECT
            album,
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

def get_top_albums(start: str = "", end: str = ""):
    """Albums sorted by plays (scrobbles) desc."""
    conn = get_db_connection()

    sql = """
        SELECT
            album,
            artist,
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

    sql += """
        GROUP BY album, artist
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
        WHERE lower(trim(artist)) = lower(trim(?)) and lower(trim(track)) = lower(trim(?))
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
            track,
            strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        WHERE
            LOWER(TRIM(artist)) = LOWER(TRIM(?))
            AND LOWER(TRIM(track))  = LOWER(TRIM(?))
        ORDER BY uts DESC
        """,
        (artist_name, track_name),
    ).fetchall()
    conn.close()
    return rows


def get_top_tracks(start: str = "", end: str = ""):
    """Tracks sorted by plays (scrobbles) desc."""
    conn = get_db_connection()

    sql = """
        SELECT
            track,
            artist,
            album,
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

    sql += """
        GROUP BY track, artist, album
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
def get_album_total_plays(artist_name, album_name, start: str = "", end: str = ""):

    conn = get_db_connection()

    sql = """
        SELECT COUNT(*) AS total
        FROM scrobble
        WHERE artist = ?
          AND album  = ?
    """
    params = [artist_name, album_name]

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()

    return row["total"] if row else 0

    # 3) Album art lookup from album_art table
def get_album_art(artist_name, album_name):

    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT album_mbid, image_xlarge
        FROM album_art
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (artist_name, album_name),
    ).fetchone()
    conn.close()
    return rows

def album_tracks_exist(artist_name, album_name):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT 1
        FROM album_tracks
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (artist_name, album_name),
    ).fetchone()
    return row is not None

def upsert_album_tracks(artist_name, album_name, tracks):
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
        [(artist_name, album_name, t["track"], t["track_number"]) for t in tracks],
    )
    conn.commit()

def get_album_tracks(artist_name: str, album_name: str, start: str = "", end: str = "", sort_by: str = "tracklist"):
    """
    Returns exactly ONE row per track, ordered by album track number (default)
    or by play count (if sort_by='plays'), with correct play counts.
    """
    conn = get_db_connection()

    # Normalize the album name for fuzzy matching
    normalized_album = _normalize_for_matching(album_name)

    # Step 1: Find all album name variations in album_tracks that match the normalized name
    album_track_albums = conn.execute(
        """
        SELECT DISTINCT album
        FROM album_tracks
        WHERE artist = ?
        """,
        (artist_name,),
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

    # Step 2: Find all scrobble albums that match the normalized album name
    all_scrobble_albums = conn.execute(
        """
        SELECT DISTINCT album
        FROM scrobble
        WHERE artist = ?
        """,
        (artist_name,),
    ).fetchall()

    # Get all matching scrobble album names
    matching_album_names = [album_name]  # Start with the input album
    for row in all_scrobble_albums:
        if _normalize_for_matching(row["album"]) == normalized_album and row["album"] != album_name:
            matching_album_names.append(row["album"])

    # Common suffixes to strip for fuzzy matching (order matters - longer first)
    # These will be removed from both album_tracks and scrobble track names
    suffixes = [
        " - Single Version",
        " (Single Version)",
        " - Album Version",
        " (Album Version)",
        " - Original Version",
        " (Original Version)",
        " - Original Mix",
        " (Original Mix)",
        " - Radio Edit",
        " (Radio Edit)",
        " - Remastered",
        " (Remastered)",
        " - Remastered Version",
        " (Remastered Version)",
        " - 200",
        " (200",
        " - Rem",
        " (Rem)",
        " - Remix",
        " (Remix)",
        " - Edit",
        " (Edit)",
    ]

    # Build SQL to normalize track name by stripping suffixes
    # We chain REPLACE calls: REPLACE(REPLACE(track, suffix1, ''), suffix2, '')
    normalize_sql = "LOWER(track)"
    for suffix in suffixes:
        normalize_sql = f"REPLACE({normalize_sql}, LOWER('{suffix}'), '')"

    # Build the play count subquery with optional date filtering
    # Include normalized track name for matching
    # Use IN clause to get scrobbles from all matching album name variations
    placeholders = ','.join(['?' for _ in matching_album_names])
    play_count_sql = f"""
            SELECT
                track,
                {normalize_sql} AS normalized_track,
                COUNT(*) AS plays
            FROM scrobble
            WHERE artist = ?
              AND album IN ({placeholders})
    """
    play_count_params = [artist_name] + matching_album_names

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        play_count_sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                               AND date(uts, 'unixepoch', 'localtime') <= ?"""
        play_count_params.extend([start, end])

    play_count_sql += " GROUP BY normalized_track"

    # Also normalize album_tracks track name for matching
    normalize_at_sql = "LOWER(at.track)"
    for suffix in suffixes:
        normalize_at_sql = f"REPLACE({normalize_at_sql}, LOWER('{suffix}'), '')"

    rows = conn.execute(
        f"""
        SELECT
            at.track_number,
            at.track AS track_name,
            COALESCE(p.plays, 0) AS plays
        FROM album_tracks at
        LEFT JOIN (
            {play_count_sql}
        ) p
          ON {normalize_at_sql} = p.normalized_track
        WHERE at.artist = ?
          AND at.album  = ?
        ORDER BY { 'at.track_number ASC' if sort_by == 'tracklist' else 'COALESCE(p.plays, 0) DESC, at.track_number ASC' }
        """,
        (*play_count_params, artist_name, canonical_album),
    ).fetchall()
    conn.close()
    return rows

def _safe_slug(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]


def get_track_gaps(start: str = "", end: str = ""):
    """Tracks sorted by time since last play (longest gap first)."""
    conn = get_db_connection()

    sql = """
        SELECT
            track,
            artist,
            album,
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

    sql += """
        GROUP BY track, artist, album
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

def ensure_album_art_cached(artist_name: str, album_name: str) -> str | None:
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
        (artist_name, album_name),
    ).fetchone()

    if not art_row:
        return None

    cdn_url = (art_row["image_xlarge"] or "").strip()
    if not cdn_url:
        return None

    album_mbid = (art_row["album_mbid"] or "").strip()

    # Prefer MBID for stable filename; otherwise slug artist+album
    cache_key = album_mbid if album_mbid else f"{_safe_slug(artist_name)}__{_safe_slug(album_name)}"
    ext = _guess_ext_from_url(cdn_url)

    covers_rel_dir = Path("covers")
    covers_abs_dir = Path(current_app.static_folder) / covers_rel_dir
    covers_abs_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{cache_key}{ext}"
    abs_path = covers_abs_dir / filename

    # Already cached
    if abs_path.exists() and abs_path.stat().st_size > 0:
        return url_for("static", filename=f"covers/{filename}")

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