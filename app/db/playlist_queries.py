"""
Playlist-specific database queries for Spotify playlist generation.

Provides specialized queries to identify tracks and albums for different
playlist types: forgotten albums, top tracks, deep cuts, high rotation, etc.
"""

import logging
from datetime import datetime, timezone, timedelta
from .connections import get_db_connection

logger = logging.getLogger(__name__)


def get_forgotten_albums(days_threshold: int = 180, limit: int = 50) -> list:
    """
    Get albums that haven't been played in a long time.

    Args:
        days_threshold: Days since last play to consider "forgotten"
        limit: Maximum number of albums to return

    Returns:
        list: Dicts with artist, album, last_play_uts, days_since, play_count
    """
    conn = get_db_connection()

    threshold_ts = int((datetime.now(timezone.utc) - timedelta(days=days_threshold)).timestamp())

    rows = conn.execute(
        f"""
        SELECT
            artist,
            album,
            MAX(uts) as last_play_uts,
            COUNT(*) as play_count,
            CAST((strftime('%s', 'now') - MAX(uts)) / 86400 AS INTEGER) as days_since
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY artist, album
        HAVING MAX(uts) < ?
        ORDER BY MAX(uts) ASC
        LIMIT ?
    """,
        (threshold_ts, limit),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_top_tracks_by_period(period_days: int = 30, limit: int = 50) -> list:
    """
    Get most played tracks in a recent time period.

    Args:
        period_days: Number of days to look back
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, play_count
    """
    conn = get_db_connection()

    period_start_ts = int((datetime.now(timezone.utc) - timedelta(days=period_days)).timestamp())

    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            track,
            COUNT(*) as play_count
        FROM scrobble
        WHERE uts >= ?
        GROUP BY artist, album, track
        ORDER BY play_count DESC
        LIMIT ?
    """,
        (period_start_ts, limit),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_deep_cuts(min_plays: int = 3, max_plays: int = 20, limit: int = 50) -> list:
    """
    Get lesser-played tracks from top artists (deep cuts).

    Finds artists with high total play counts, then returns their
    lesser-played tracks for discovery.

    Args:
        min_plays: Minimum times track must have been played
        max_plays: Maximum times track must have been played
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, play_count, artist_total_plays
    """
    conn = get_db_connection()

    # First get top artists (by total plays)
    artist_rows = conn.execute(
        """
        SELECT
            artist,
            COUNT(*) as total_plays
        FROM scrobble
        GROUP BY artist
        ORDER BY total_plays DESC
        LIMIT 50
    """
    ).fetchall()

    top_artists = [row["artist"] for row in artist_rows]

    if not top_artists:
        return []

    # Then get tracks from these artists with play counts in the specified range
    placeholders = ",".join("?" * len(top_artists))

    rows = conn.execute(
        f"""
        SELECT
            artist,
            album,
            track,
            COUNT(*) as play_count
        FROM scrobble
        WHERE artist IN ({placeholders})
        GROUP BY artist, album, track
        HAVING play_count >= ? AND play_count <= ?
        ORDER BY play_count ASC
        LIMIT ?
    """,
        top_artists + [min_plays, max_plays, limit],
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_high_rotation(days: int = 7, min_plays: int = 3, limit: int = 50) -> list:
    """
    Get tracks played frequently in recent days.

    Args:
        days: Number of days to look back
        min_plays: Minimum number of plays in the period
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, play_count
    """
    conn = get_db_connection()

    period_start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            track,
            COUNT(*) as play_count
        FROM scrobble
        WHERE uts >= ?
        GROUP BY artist, album, track
        HAVING play_count >= ?
        ORDER BY play_count DESC
        LIMIT ?
    """,
        (period_start_ts, min_plays, limit),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_track_gaps(limit: int = 50) -> list:
    """
    Get tracks sorted by time since last play (longest gap first).

    This is useful for rediscovery playlists.

    Args:
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, last_play_uts, play_count, days_since
    """
    conn = get_db_connection()

    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            track,
            MAX(uts) as last_play_uts,
            COUNT(*) as play_count,
            CAST((strftime('%s', 'now') - MAX(uts)) / 86400 AS INTEGER) as days_since
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        GROUP BY artist, album, track
        ORDER BY MAX(uts) ASC
        LIMIT ?
    """,
        (limit,),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_recent_discoveries(days: int = 30, limit: int = 50) -> list:
    """
    Get tracks first played recently (new discoveries).

    Args:
        days: Number of days to look back
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, first_play_uts, play_count
    """
    conn = get_db_connection()

    period_start_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            track,
            MIN(uts) as first_play_uts,
            COUNT(*) as play_count
        FROM scrobble
        WHERE uts >= ?
        GROUP BY artist, album, track
        ORDER BY MIN(uts) DESC
        LIMIT ?
    """,
        (period_start_ts, limit),
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_tracks_for_multiple_scrobbles(tracks: list, limit: int = 50) -> list:
    """
    Get additional tracks from the same artists as the provided tracks.

    Useful for "similar to" playlist generation.

    Args:
        tracks: List of dicts with 'artist' key
        limit: Maximum number of tracks to return

    Returns:
        list: Dicts with artist, album, track, play_count
    """
    if not tracks:
        return []

    # Extract unique artists
    artists = list(set(t.get("artist") for t in tracks if t.get("artist")))

    if not artists:
        return []

    conn = get_db_connection()

    placeholders = ",".join("?" * len(artists))

    rows = conn.execute(
        f"""
        SELECT
            artist,
            album,
            track,
            COUNT(*) as play_count
        FROM scrobble
        WHERE artist IN ({placeholders})
        GROUP BY artist, album, track
        ORDER BY play_count DESC
        LIMIT ?
    """,
        artists + [limit],
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_listening_patterns(hours: int = 24) -> dict:
    """
    Analyze listening patterns by time of day.

    Args:
        hours: Number of hours to analyze

    Returns:
        dict: Hour of day (0-23) -> play count
    """
    conn = get_db_connection()

    period_start_ts = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())

    rows = conn.execute(
        """
        SELECT
            CAST(strftime('%H', datetime(uts, 'unixepoch', 'localtime')) AS INTEGER) as hour,
            COUNT(*) as play_count
        FROM scrobble
        WHERE uts >= ?
        GROUP BY hour
        ORDER BY hour
    """,
        (period_start_ts,),
    ).fetchall()

    conn.close()

    # Convert to dict with all hours
    pattern = {i: 0 for i in range(24)}
    for row in rows:
        pattern[row["hour"]] = row["play_count"]

    return pattern


def get_album_cohort(album: str, artist: str) -> list:
    """
    Get tracks that are frequently played around the same time as a specific album.

    This helps identify "vibe" or mood associations.

    Args:
        album: Album name
        artist: Artist name

    Returns:
        list: Dicts with artist, album, track, correlation_score
    """
    conn = get_db_connection()

    # Get timestamps when this album was played
    album_timestamps = conn.execute(
        """
        SELECT uts
        FROM scrobble
        WHERE album = ? AND artist = ?
        ORDER BY uts DESC
        LIMIT 100
    """,
        (album, artist),
    ).fetchall()

    if not album_timestamps:
        return []

    # Look for tracks played within 30 minutes of these album plays
    timestamps = [t["uts"] for t in album_timestamps]

    # Build OR clause for time ranges
    time_conditions = []
    params = []

    for ts in timestamps:
        time_conditions.append("(uts >= ? AND uts <= ?)")
        params.extend([ts - 1800, ts + 1800])  # 30 minutes before/after

    # Exclude the original album
    params.extend([artist, album])

    query = f"""
        SELECT
            s.artist,
            s.album,
            s.track,
            COUNT(*) as correlation_score
        FROM scrobble s
        WHERE ({' OR '.join(time_conditions)})
        AND (s.artist != ? OR s.album != ?)
        GROUP BY s.artist, s.album, s.track
        ORDER BY correlation_score DESC
        LIMIT 50
    """

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]
