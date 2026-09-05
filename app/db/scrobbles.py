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
        SELECT s.artist,
               COALESCE(a.title, s.album) AS album,
               s.album_artist,
               s.track,
               strftime('%Y-%m-%d %H:%M:%S', s.uts, 'unixepoch', 'localtime') AS date
        FROM scrobble s
        LEFT JOIN album a ON a.album_id = s.album_id
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ WHERE date(s.uts, 'unixepoch', 'localtime') >= ?
                   AND date(s.uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    # Order chronologically when filtering by date, reverse chronologically otherwise
    if start and end:
        sql += " ORDER BY s.uts ASC"
    else:
        sql += " ORDER BY s.uts DESC"

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
    """Tracks sorted by time since last play (longest gap first).

    Grouped by canonical ``track_id`` (falling back to the normalized track text
    and artist for scrobbles that have no ``track_id`` yet) and canonical
    ``album_id`` (falling back to normalized album text). This prevents raw
    track or album spelling variants from leaving stale duplicate gap rows.
    """
    conn = get_db_connection()

    # Normalize escaped characters in track names for proper grouping
    # Handles \!, \?, \[, \] etc. so "Muka!" and "Muka\!" are treated as same track
    # CHAR(92) is backslash - we remove all backslashes to normalize escaped characters
    normalized_track = "TRIM(REPLACE(REPLACE(REPLACE(REPLACE(s.track, CHAR(92), ''), CHAR(92), ''), CHAR(92), ''), CHAR(92), ''))"

    normalized_artist = "LOWER(TRIM(s.artist))"
    normalized_album = "LOWER(TRIM(REPLACE(s.album, CHAR(92), '')))"
    normalized_album_artist = "LOWER(TRIM(COALESCE(s.album_artist, s.artist)))"

    # Prefix keys with their source so a numeric-looking text value cannot
    # collide with an entity ID. Artist identity is only needed for unresolved
    # tracks because a canonical track already belongs to one artist.
    track_group_key = (
        "CASE WHEN s.track_id IS NOT NULL "
        "THEN 'id:' || s.track_id "
        f"ELSE 'text:' || LOWER({normalized_track}) || '|artist:' || {normalized_artist} END"
    )
    album_group_key = (
        "CASE WHEN s.album_id IS NOT NULL "
        "THEN 'id:' || s.album_id "
        f"ELSE 'text:' || {normalized_album} || '|album_artist:' || {normalized_album_artist} END"
    )

    sql = f"""
        SELECT
            COALESCE(ct.title, {normalized_track}) AS track,
            s.artist,
            COALESCE(ca.title, s.album) AS album,
            s.album_artist,
            MAX(CAST(s.uts AS INTEGER)) AS last_play_uts,
            COUNT(*) AS plays
        FROM scrobble s
        LEFT JOIN track ct ON ct.track_id = s.track_id
        LEFT JOIN album ca ON ca.album_id = s.album_id
        WHERE s.track IS NOT NULL AND s.track != ''
    """
    params = []

    # Use SQLite's date function to filter by local date, not UTC
    if start and end:
        sql += """ AND date(s.uts, 'unixepoch', 'localtime') >= ?
                   AND date(s.uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += f"""
        GROUP BY {track_group_key}, {album_group_key}
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
