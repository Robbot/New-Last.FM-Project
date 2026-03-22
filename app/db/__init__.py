"""
Database module - re-exports all functions for backward compatibility.

The db module has been split into submodules:
- connections: Database connection management and utility functions
- scrobbles: Scrobble-related queries
- artists: Artist-related queries
- albums: Album-related queries and album art management
- tracks: Track-related queries

All functions are re-exported here to maintain backward compatibility with
existing imports like:
    from app import db
    from app.db import get_db_connection
"""

# Import and re-export connections
from .connections import (
    get_db_connection,
    db_connection,
    _ymd_to_epoch_bounds,
    _normalize_for_matching,
    _normalize_track_name_for_matching,
    BASE_DIR,
    DB_PATH,
)

# Import and re-export scrobbles
from .scrobbles import (
    get_latest_scrobbles,
    average_scrobbles_per_day,
    get_track_gaps,
)

# Import and re-export artists
from .artists import (
    get_artist_overview,
    get_library_stats,
    get_artist_stats,
    get_artist_position,
    get_top_tracks_for_artist,
    get_artist_tracks_count,
    get_artists_details,
    get_artist_albums,
    get_artist_tracks,
    get_artist_info,
    set_artist_info,
    ensure_artist_info_cached,
)

# Import and re-export albums
from .albums import (
    get_album_stats,
    get_top_albums,
    get_album_total_plays,
    get_album_art,
    get_album_release_year,
    get_album_wikipedia_url,
    set_album_wikipedia_url,
    album_tracks_exist,
    upsert_album_tracks,
    get_album_tracks,
    ensure_album_art_cached,
    save_uploaded_cover,
)

# Import and re-export tracks
from .tracks import (
    get_track_stats,
    get_track_stats_detail,
    get_recent_scrobbles_for_track,
    get_top_tracks,
    get_track_overview,
    get_track_mbid,
)

__all__ = [
    # Connections
    "get_db_connection",
    "db_connection",
    "_ymd_to_epoch_bounds",
    "_normalize_for_matching",
    "_normalize_track_name_for_matching",
    "BASE_DIR",
    "DB_PATH",
    # Scrobbles
    "get_latest_scrobbles",
    "average_scrobbles_per_day",
    "get_track_gaps",
    # Artists
    "get_artist_overview",
    "get_library_stats",
    "get_artist_stats",
    "get_artist_position",
    "get_top_tracks_for_artist",
    "get_artist_tracks_count",
    "get_artists_details",
    "get_artist_albums",
    "get_artist_tracks",
    "get_artist_info",
    "set_artist_info",
    "ensure_artist_info_cached",
    # Albums
    "get_album_stats",
    "get_top_albums",
    "get_album_total_plays",
    "get_album_art",
    "get_album_release_year",
    "get_album_wikipedia_url",
    "set_album_wikipedia_url",
    "album_tracks_exist",
    "upsert_album_tracks",
    "get_album_tracks",
    "ensure_album_art_cached",
    "save_uploaded_cover",
    # Tracks
    "get_track_stats",
    "get_track_stats_detail",
    "get_recent_scrobbles_for_track",
    "get_top_tracks",
    "get_track_overview",
    "get_track_mbid",
]
