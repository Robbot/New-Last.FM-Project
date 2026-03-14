"""
Scrobble-related database queries.
"""
import logging
from datetime import datetime, timezone

from .connections import get_db_connection

logger = logging.getLogger(__name__)


def get_latest_scrobbles(start: str = "", end: str = ""):
    """Get latest scrobbles, optionally filtered by date range."""
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
    """Calculate average scrobbles per day."""
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

    return int(row["per_day_rounded"])


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
            MAX(CAST(uts AS INTEGER)) AS last_play_uts,
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
