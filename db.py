import sqlite3
import re
from pathlib import Path
from urllib.parse import urlparse
import requests
from flask import current_app, url_for
from datetime import datetime, timezone, timedelta


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

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

def get_latest_scrobbles():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT artist,
               album,
               track,
               strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        ORDER BY uts DESC
        """
    ).fetchall()
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

    start_epoch, end_epoch = _ymd_to_epoch_bounds(start, end)

    sql = """
        SELECT
            COUNT(*) AS scrobbles,
            COUNT(DISTINCT album) AS albums,
            COUNT(DISTINCT track) AS tracks
        FROM scrobble
        WHERE artist = ?
    """
                       
    params = [artist_name]

    # Apply date filter only when both start/end are present
    if start_epoch is not None and end_epoch is not None:
        sql += " AND uts >= ? AND uts < ?"
        params.extend([start_epoch, end_epoch])

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
    start_epoch, end_epoch = _ymd_to_epoch_bounds(start, end)

    sql = """
        SELECT
            artist,
            track,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
    """
    params = [artist_name]

   
    if start_epoch is not None and end_epoch is not None:
        sql += " AND uts >= ? AND uts < ?"
        params.extend([start_epoch, end_epoch])

    sql += """
        GROUP BY artist, track
        ORDER BY plays DESC, track ASC
        LIMIT ?
    """
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows

def get_artists_details():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT artist, COUNT(*) AS plays
        FROM scrobble
        GROUP BY artist
        ORDER BY plays DESC
        """
    ).fetchall()
    conn.close()
    return rows


def get_artist_albums(artist_name: str, start: str = "", end: str = ""):
    conn = get_db_connection()

    start_epoch, end_epoch = _ymd_to_epoch_bounds(start, end)

    sql = """
        SELECT
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
        """
    params = [artist_name]
    
    if start_epoch is not None and end_epoch is not None:
        sql += " AND uts >= ? AND uts < ?"
        params.extend([start_epoch, end_epoch])

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

def get_top_albums():
    """Albums sorted by plays (scrobbles) desc."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            album,
            artist,
            COUNT(*) AS plays
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY album, artist
        ORDER BY plays DESC
        """,
    ).fetchall()
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


def get_top_tracks():
    """Tracks sorted by plays (scrobbles) desc."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            track,
            artist,
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        GROUP BY track, artist, album
        ORDER BY plays DESC
        """,
    ).fetchall()
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
def get_album_total_plays(artist_name, album_name):
    
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT COUNT(*) AS total
        FROM scrobble
        WHERE artist = ?
          AND album  = ?
        """,
        (artist_name, album_name),
    ).fetchone()
 
    return row["total"] if row else 0

    # 3) Album art MBID lookup from album_art table
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

def get_album_tracks(artist_name: str, album_name: str):
    """
    Returns exactly ONE row per track, ordered by album track number,
    with correct play counts.
    """
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            at.track_number,
            at.track AS track_name,
            COALESCE(p.plays, 0) AS plays
        FROM album_tracks at
        LEFT JOIN (
            SELECT
                track,
                COUNT(*) AS plays
            FROM scrobble
            WHERE artist = ?
              AND album  = ?
            GROUP BY track
        ) p
          ON p.track = at.track
        WHERE at.artist = ?
          AND at.album  = ?
        ORDER BY at.track_number ASC
        """,
        (artist_name, album_name, artist_name, album_name),
    ).fetchall()
    conn.close()
    return rows

def _safe_slug(text: str) -> str:
    """Convert text to safe filename slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text[:100]


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