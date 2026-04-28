"""
Artist-related database queries.
"""
import logging
from datetime import timedelta

from .connections import get_db_connection, _normalize_for_matching

logger = logging.getLogger(__name__)

# Cache expiry for MusicBrainz releases (30 days)
MB_CACHE_EXPIRY_DAYS = 30


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


def get_artist_info(artist_name: str) -> dict | None:
    """
    Get artist information from the database.

    Returns a dict with keys: image_url, bio, wikipedia_url, last_updated
    Returns None if no info found.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT image_url, bio, wikipedia_url, last_updated
            FROM artist_info
            WHERE artist_name = ?
            LIMIT 1
            """,
            (artist_name,),
        ).fetchone()

        if row:
            return {
                "image_url": row["image_url"],
                "bio": row["bio"],
                "wikipedia_url": row["wikipedia_url"],
                "last_updated": row["last_updated"],
            }
        return None
    finally:
        conn.close()


def set_artist_info(artist_name: str, image_url: str | None, bio: str | None, wikipedia_url: str | None) -> bool:
    """
    Store or update artist information in the database.

    Returns True on success, False on failure.
    """
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO artist_info (artist_name, image_url, bio, wikipedia_url, last_updated)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            (artist_name, image_url, bio, wikipedia_url),
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting artist info for {artist_name}: {e}", exc_info=True)
        return False
    finally:
        conn.close()


def ensure_artist_info_cached(artist_name: str) -> dict | None:
    """
    Ensure artist info is cached in the database, fetching from Wikipedia if needed.

    Follows the same lazy-loading pattern as ensure_album_art_cached().

    Returns a dict with image_url, bio, wikipedia_url keys, or None if unavailable.
    """
    # First, try to get from database
    cached_info = get_artist_info(artist_name)
    # Only use cached info if bio is present
    if cached_info and cached_info.get("bio"):
        return cached_info

    # Bio not in database or missing, fetch from Wikipedia
    from app.services.fetch_artist_info import fetch_artist_info

    fetched_info = fetch_artist_info(artist_name)

    if fetched_info is None:
        # Error occurred during fetch
        return None

    # Store in database for future use (even if all values are None, this marks as "searched")
    set_artist_info(
        artist_name,
        fetched_info.get("image_url"),
        fetched_info.get("bio"),
        fetched_info.get("wikipedia_url"),
    )

    return fetched_info


def get_artist_mbid(artist_name: str) -> str | None:
    """
    Get the MusicBrainz ID for an artist from the scrobble table.
    Returns the MBID if found, None otherwise.
    """
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT artist_mbid
            FROM scrobble
            WHERE artist = ?
              AND artist_mbid IS NOT NULL
              AND artist_mbid != ''
            LIMIT 1
            """,
            (artist_name,),
        ).fetchone()
        return row["artist_mbid"] if row else None
    finally:
        conn.close()


def get_musicbrainz_releases(artist_mbid: str, artist_name: str) -> tuple[list[dict], str | None]:
    """
    Get all releases for an artist from the musicbrainz_releases cache.

    Returns:
        A tuple of (releases, last_updated) where releases is a list of dicts
        with keys: album_title, release_year, album_mbid, release_type, primary_type, secondary_types, and
        last_updated is the most recent update timestamp or None.
    """
    conn = get_db_connection()
    try:
        # Try to find by MBID first
        if artist_mbid:
            rows = conn.execute(
                """
                SELECT album_title, release_year, album_mbid, release_type, primary_type, secondary_types, last_updated
                FROM musicbrainz_releases
                WHERE artist_mbid = ?
                ORDER BY release_year ASC, album_title ASC
                """,
                (artist_mbid,),
            ).fetchall()

            if rows:
                releases = [dict(row) for row in rows]
                last_updated = max((r.get("last_updated") for r in releases), default=None)
                return releases, last_updated

        # Fallback: try to find by artist name (MBID may have changed)
        rows = conn.execute(
            """
            SELECT album_title, release_year, album_mbid, release_type, primary_type, secondary_types, last_updated, artist_mbid
            FROM musicbrainz_releases
            WHERE artist_name = ?
            ORDER BY release_year ASC, album_title ASC
            """,
            (artist_name,),
        ).fetchall()

        releases = [dict(row) for row in rows]
        last_updated = max((r.get("last_updated") for r in releases), default=None)
        return releases, last_updated

    finally:
        conn.close()


def set_musicbrainz_releases(artist_mbid: str, artist_name: str, releases: list[dict]) -> bool:
    """
    Store or update releases for an artist in the musicbrainz_releases table.

    Args:
        artist_mbid: The MusicBrainz ID of the artist
        artist_name: The name of the artist
        releases: A list of dicts with keys: title, year, mbid, release_type, primary_type, secondary_types

    Returns:
        True on success, False on failure.
    """
    if not releases:
        return True

    conn = get_db_connection()
    try:
        # Insert or replace releases
        for release in releases:
            # Handle secondary_types - convert list to JSON string for storage
            secondary_types = release.get("secondary_types", [])
            if isinstance(secondary_types, list):
                import json
                secondary_types_json = json.dumps(secondary_types)
            else:
                secondary_types_json = ""

            conn.execute(
                """
                INSERT OR REPLACE INTO musicbrainz_releases
                (artist_mbid, artist_name, album_title, release_year, album_mbid, release_type, primary_type, secondary_types, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    artist_mbid,
                    artist_name,
                    release.get("title", ""),
                    release.get("year"),
                    release.get("mbid", ""),
                    release.get("release_type", ""),
                    release.get("primary_type", ""),
                    secondary_types_json,
                ),
            )

        conn.commit()
        logger.info(f"Stored {len(releases)} releases for artist {artist_name}")
        return True

    except Exception as e:
        logger.error(f"Error storing MusicBrainz releases for {artist_name}: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


def ensure_musicbrainz_releases_cached(artist_mbid: str, artist_name: str) -> list[dict]:
    """
    Ensure MusicBrainz releases are cached, fetching from API if needed.

    This follows the same lazy-loading pattern as ensure_artist_info_cached().

    Args:
        artist_mbid: The MusicBrainz ID of the artist
        artist_name: The name of the artist

    Returns:
        A list of dicts with keys: album_title, release_year, album_mbid, release_type.
        Returns empty list if unavailable.
    """
    from datetime import datetime

    if not artist_mbid:
        return []

    # First, try to get from database (returns releases and last_updated timestamp)
    cached_releases, last_updated = get_musicbrainz_releases(artist_mbid, artist_name)

    # Only use cached data if we have results and it's recent
    if cached_releases and last_updated:
        try:
            updated_dt = datetime.fromisoformat(last_updated)
            if datetime.now() - updated_dt < timedelta(days=MB_CACHE_EXPIRY_DAYS):
                return cached_releases
        except (ValueError, TypeError):
            # Invalid timestamp, continue to fetch from API
            pass

    # Data not in database or stale, fetch from MusicBrainz
    from app.services.fetch_musicbrainz_releases import fetch_artist_releases_from_musicbrainz

    fetched_releases = fetch_artist_releases_from_musicbrainz(artist_mbid)

    if not fetched_releases:
        # Error occurred or no releases found
        return cached_releases  # Return whatever we have in cache

    # Store in database for future use
    set_musicbrainz_releases(artist_mbid, artist_name, fetched_releases)

    return fetched_releases


def get_artist_albums_with_years(
    album_artist_name: str,
    artist_mbid: str | None = None,
    start: str = "",
    end: str = "",
    sort_by: str = "plays",
    sort_order: str = "desc"
) -> list[dict]:
    """
    Get albums for an artist with release years from MusicBrainz.
    Includes both played albums (from scrobbles) and unplayed albums (from MusicBrainz).

    Args:
        album_artist_name: The name of the artist
        artist_mbid: The MusicBrainz ID of the artist (optional)
        start: Start date for filtering scrobbles
        end: End date for filtering scrobbles
        sort_by: How to sort albums ("plays" or "year")
        sort_order: Sort order ("asc" or "desc")

    Returns:
        A list of dicts with keys: album, album_artist, plays, year, has_scrobbles, release_type, is_pure_album
    """
    import json

    # Get played albums from scrobbles
    conn = get_db_connection()

    sql = """
        SELECT
            album,
            album_artist,
            MAX(album_mbid) AS album_mbid,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
    """
    params = [album_artist_name]

    if start and end:
        sql += """ AND date(uts, 'unixepoch', 'localtime') >= ?
                   AND date(uts, 'unixepoch', 'localtime') <= ?"""
        params.extend([start, end])

    sql += """
        GROUP BY album
    """

    rows = conn.execute(sql, params).fetchall()
    played_albums = {row["album"]: dict(row) for row in rows}
    conn.close()

    # Get all releases from MusicBrainz
    mb_releases = []
    if artist_mbid:
        mb_releases = ensure_musicbrainz_releases_cached(artist_mbid, album_artist_name)

    # Parse secondary_types from JSON and determine if pure album
    for release in mb_releases:
        if "secondary_types" in release and isinstance(release["secondary_types"], str):
            try:
                release["secondary_types"] = json.loads(release["secondary_types"])
            except json.JSONDecodeError:
                release["secondary_types"] = []

        # Determine if this is a pure album (Album or EP without secondary types)
        release["is_pure_album"] = (
            release.get("primary_type") in ("Album", "EP") and
            not release.get("secondary_types")
        )

    # Pre-normalize MusicBrainz releases for efficient lookup
    mb_lookup = {
        _normalize_for_matching(r["album_title"]): r
        for r in mb_releases
    }

    # Pre-normalize played album names for efficient lookup
    played_normalized = {
        _normalize_for_matching(album): album
        for album in played_albums.keys()
    }

    # Combine played albums with MusicBrainz releases
    albums_with_years = []

    # Add played albums with year from MusicBrainz if available
    for album_name, album_data in played_albums.items():
        normalized_name = _normalize_for_matching(album_name)
        release = mb_lookup.get(normalized_name)
        year = release["release_year"] if release else None
        release_type = release.get("release_type", "") if release else ""
        is_pure_album = release.get("is_pure_album", False) if release else False

        albums_with_years.append({
            "album": album_name,
            "album_artist": album_data.get("album_artist") or album_artist_name,
            "plays": album_data["plays"],
            "year": year,
            "has_scrobbles": True,
            "release_type": release_type,
            "is_pure_album": is_pure_album,
        })

    # Add unplayed albums from MusicBrainz (pure Albums and EPs)
    for release in mb_releases:
        # Only add unplayed albums that are pure "Album" or "EP" type
        if not release.get("is_pure_album", False):
            continue

        normalized_title = _normalize_for_matching(release["album_title"])
        if normalized_title not in played_normalized:
            albums_with_years.append({
                "album": release["album_title"],
                "album_artist": album_artist_name,
                "plays": 0,
                "year": release["release_year"],
                "has_scrobbles": False,
                "release_type": release.get("release_type", ""),
                "is_pure_album": True,
            })

    # Sort the results
    if sort_by == "year":
        albums_with_years.sort(
            key=lambda x: (x["year"] is None, x["year"] or 0, x["album"].lower()),
            reverse=(sort_order == "desc")
        )
    else:  # sort_by == "plays"
        albums_with_years.sort(
            key=lambda x: (x["plays"], x["album"].lower()),
            reverse=(sort_order == "desc")
        )

    return albums_with_years
