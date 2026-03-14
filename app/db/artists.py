"""
Artist-related database queries.
"""
import logging

from .connections import get_db_connection

logger = logging.getLogger(__name__)


def get_artist_overview(artist_name: str):
    """Get overview statistics for an artist."""
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
    """Get overall library statistics."""
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
    """Get statistics for an artist, optionally filtered by date range."""
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


def get_artist_position(artist_name: str, start: str = "", end: str = "") -> int | None:
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
        limit: int = 50,
        offset: int = 0
    ):
    """Get top tracks for an artist with pagination."""
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
        LIMIT ? OFFSET ?
    """
    params.extend([limit, offset])

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_artist_tracks_count(artist_name: str, start: str = "", end: str = "") -> int:
    """Get the total number of unique tracks for an artist."""
    conn = get_db_connection()

    sql = """
        SELECT COUNT(DISTINCT track) AS total
        FROM scrobble
        WHERE artist = ?
    """
    params = [artist_name]

    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row["total"] if row else 0


def get_artists_details(start: str = "", end: str = "", sort_by: str = "plays", sort_order: str = "desc", search_term: str = ""):
    """Get detailed list of artists with sorting and filtering options."""
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
    """Get albums for an artist, optionally filtered by date range."""
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
    """Get all tracks for an artist with play counts."""
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
