"""
Track-related database queries.
"""
import logging

from .connections import get_db_connection
from .entities import lookup_track_id

logger = logging.getLogger(__name__)


def get_track_stats():
    """Get overall track statistics."""
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT track_id) AS total_tracks,
            COUNT(*) AS total_scrobbles
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
          AND track_id IS NOT NULL
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
    """Get detailed statistics for a specific track.

    Matches by canonical track_id so variant/escaped spellings (case, accents,
    remastered suffixes) resolve to one track instead of defeating the old
    LOWER/REPLACE text matching.
    """
    conn = get_db_connection()
    track_id = lookup_track_id(conn, artist_name, track_name)
    if track_id is None:
        conn.close()
        # Mimic the old row shape: a Row with plays = 0
        return {"plays": 0}
    row = conn.execute(
        """
        SELECT COUNT(*) AS plays
        FROM scrobble
        WHERE track_id = ?
        """,
        (track_id,),
    ).fetchone()
    conn.close()
    return row


def get_recent_scrobbles_for_track(artist_name: str, track_name: str):
    """Get recent scrobbles for a specific track (matched by canonical track_id)."""
    conn = get_db_connection()
    track_id = lookup_track_id(conn, artist_name, track_name)
    if track_id is None:
        conn.close()
        return []
    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            album_artist,
            track,
            strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        WHERE track_id = ?
        ORDER BY uts DESC
        """,
        (track_id,),
    ).fetchall()
    conn.close()
    return rows


def get_top_tracks(start: str = "", end: str = "", search_term: str = ""):
    """Tracks sorted by plays (scrobbles) desc.

    Groups by canonical track_id so spelling, case, accent, and version aliases
    are presented as one track. Rows not yet linked to an entity fall back to
    case-insensitive text grouping. For compilations (Various Artists), shows
    the original artist instead when available.
    """
    conn = get_db_connection()

    # Filter first, then attach canonical entity names and a stable grouping
    # key. The text fallback keeps this query useful during/after migrations
    # where a small number of legacy rows may still have NULL entity ids.
    sql = """
        WITH filtered_scrobbles AS (
            SELECT
                track,
                track_id,
                artist_id,
                artist,
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
        ),
        normalized_scrobbles AS (
            SELECT
                COALESCE(t.title, fs.track) AS track,
                CASE
                    WHEN LOWER(fs.artist) != 'various artists'
                        THEN COALESCE(ar.name, fs.primary_artist)
                    ELSE fs.primary_artist
                END AS primary_artist,
                fs.album_artist,
                fs.album,
                fs.uts,
                CASE
                    WHEN fs.track_id IS NOT NULL THEN 'id:' || fs.track_id
                    ELSE 'text:' || LOWER(fs.track) || CHAR(31) || LOWER(fs.primary_artist)
                END AS track_group_key
            FROM filtered_scrobbles fs
            LEFT JOIN track t ON t.track_id = fs.track_id
            LEFT JOIN artist ar ON ar.artist_id = fs.artist_id
        ),
        album_counts AS (
            SELECT
                track_group_key,
                MAX(track) AS track,
                MAX(primary_artist) AS artist,
                MAX(album_artist) AS album_artist,
                album,
                COUNT(*) AS album_plays,
                MAX(uts) AS last_play
            FROM normalized_scrobbles
            GROUP BY track_group_key, album
        ),
        ranked_albums AS (
            SELECT
                *,
                SUM(album_plays) OVER (
                    PARTITION BY track_group_key
                ) AS plays,
                ROW_NUMBER() OVER (
                    PARTITION BY track_group_key
                    ORDER BY album_plays DESC,
                             last_play DESC,
                             (album IS NULL OR album = '') ASC,
                             album COLLATE NOCASE ASC
                ) AS album_rank
            FROM album_counts
        )
        SELECT
            track,
            artist,
            album_artist,
            album,
            plays
        FROM ranked_albums
        WHERE album_rank = 1
        ORDER BY plays DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_track_overview(artist_name: str, track_name: str):
    """Get overview statistics for a specific track (matched by canonical track_id)."""
    conn = get_db_connection()
    track_id = lookup_track_id(conn, artist_name, track_name)
    if track_id is None:
        conn.close()
        return None
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS plays,
            COUNT(DISTINCT album) AS albums
        FROM scrobble
        WHERE track_id = ?
        """,
        (track_id,),
    ).fetchone()
    conn.close()

    if row is None or row["plays"] == 0:
        return None

    return {
        "plays": row["plays"],
        "albums": row["albums"],
    }


def get_track_mbid(artist_name: str, track_name: str) -> str | None:
    """
    Get the MusicBrainz recording ID for a canonical track.

    Prefer the cached tracklist MBID belonging to the album on which the track
    has the most plays.  A recording can appear on multiple releases, and an
    arbitrary non-empty scrobble MBID may belong to a compilation rather than
    the representative album.  Fall back to entity/scrobble metadata when the
    preferred album has no cached recording ID.
    """
    conn = get_db_connection()
    try:
        track_id = lookup_track_id(conn, artist_name, track_name)
        if track_id is None:
            row = conn.execute(
                """
                SELECT track_mbid
                FROM scrobble
                WHERE artist = ? AND track = ?
                  AND track_mbid IS NOT NULL AND track_mbid != ''
                ORDER BY uts DESC, id DESC
                LIMIT 1
                """,
                (artist_name, track_name),
            ).fetchone()
            return row["track_mbid"] if row else None

        row = conn.execute(
            """
            WITH preferred_album AS (
                SELECT album_id
                FROM scrobble
                WHERE track_id = ? AND album_id IS NOT NULL
                GROUP BY album_id
                ORDER BY COUNT(*) DESC, MAX(uts) DESC, album_id ASC
                LIMIT 1
            )
            SELECT COALESCE(
                (
                    SELECT NULLIF(at.track_mbid, '')
                    FROM preferred_album pa
                    JOIN album_tracks at
                      ON at.album_id = pa.album_id AND at.track_id = ?
                    WHERE at.track_mbid IS NOT NULL AND at.track_mbid != ''
                    ORDER BY at.track_number
                    LIMIT 1
                ),
                (SELECT NULLIF(t.mbid, '') FROM track t WHERE t.track_id = ?),
                (
                    SELECT NULLIF(s.track_mbid, '')
                    FROM scrobble s
                    WHERE s.track_id = ?
                      AND s.track_mbid IS NOT NULL AND s.track_mbid != ''
                    ORDER BY s.uts DESC, s.id DESC
                    LIMIT 1
                )
            ) AS track_mbid
            """,
            (track_id, track_id, track_id, track_id),
        ).fetchone()
        return row["track_mbid"] if row and row["track_mbid"] else None
    finally:
        conn.close()
