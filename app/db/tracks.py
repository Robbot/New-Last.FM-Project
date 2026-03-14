"""
Track-related database queries.
"""
import logging

from .connections import get_db_connection

logger = logging.getLogger(__name__)


def get_track_stats():
    """Get overall track statistics."""
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
    """Get detailed statistics for a specific track."""
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
    """Get recent scrobbles for a specific track."""
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
    """Get overview statistics for a specific track."""
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
