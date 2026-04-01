#!/usr/bin/env python3
"""
Refresh MusicBrainz releases cache.

This script clears and refetches MusicBrainz release data for artists.
Useful after updating the fetch logic or to get fresh data.

Usage:
    # Refresh all artists
    python -m app.services.refresh_musicbrainz_cache

    # Refresh specific artist
    python -m app.services.refresh_musicbrainz_cache "Daft Punk"
"""
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.db.artists import (
    get_musicbrainz_releases,
    set_musicbrainz_releases,
    ensure_musicbrainz_releases_cached,
)
from app.db.connections import get_db_connection
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_all_artists_with_mbid():
    """Get all artists that have a MusicBrainz ID."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT artist, artist_mbid
            FROM scrobble
            WHERE artist_mbid IS NOT NULL AND artist_mbid != ''
            ORDER BY artist ASC
            """
        ).fetchall()
        return [(row["artist"], row["artist_mbid"]) for row in rows]
    finally:
        conn.close()


def clear_artist_cache(artist_name: str) -> bool:
    """Clear MusicBrainz releases cache for an artist."""
    conn = get_db_connection()
    try:
        conn.execute(
            "DELETE FROM musicbrainz_releases WHERE artist_name = ?",
            (artist_name,)
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error clearing cache for {artist_name}: {e}")
        return False
    finally:
        conn.close()


def refresh_artist(artist_name: str, artist_mbid: str) -> dict:
    """Refresh MusicBrainz data for a single artist.

    Returns:
        dict with 'success', 'artist', 'count', 'error' keys
    """
    result = {
        "success": False,
        "artist": artist_name,
        "count": 0,
        "error": None
    }

    try:
        # Clear existing cache
        clear_artist_cache(artist_name)

        # Fetch fresh data
        releases = ensure_musicbrainz_releases_cached(artist_mbid, artist_name)
        result["count"] = len(releases)
        result["success"] = True

        logger.info(f"Refreshed {len(releases)} releases for {artist_name}")

    except Exception as e:
        result["error"] = str(e)
        logger.error(f"Error refreshing {artist_name}: {e}", exc_info=True)

    return result


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Refresh MusicBrainz releases cache"
    )
    parser.add_argument(
        "artist",
        nargs="?",
        help="Artist name to refresh (if omitted, refreshes all)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of artists to refresh (for testing)"
    )

    args = parser.parse_args()

    if args.artist:
        # Refresh single artist
        conn = get_db_connection()
        try:
            row = conn.execute(
                "SELECT artist_mbid FROM scrobble WHERE artist = ? AND artist_mbid IS NOT NULL AND artist_mbid != '' LIMIT 1",
                (args.artist,)
            ).fetchone()
        finally:
            conn.close()

        if not row:
            logger.error(f"Artist '{args.artist}' not found in database or has no MusicBrainz ID")
            sys.exit(1)

        artist_mbid = row["artist_mbid"]

        result = refresh_artist(args.artist, artist_mbid)

        if result["success"]:
            print(f"✓ Refreshed {result['count']} releases for {args.artist}")
        else:
            print(f"✗ Error: {result['error']}")
            sys.exit(1)

    else:
        # Refresh all artists
        artists = get_all_artists_with_mbid()
        print(f"Found {len(artists)} artists with MusicBrainz IDs")

        if args.limit:
            artists = artists[:args.limit]
            print(f"Limiting to first {args.limit} artists")

        success_count = 0
        total_releases = 0

        for i, (artist_name, artist_mbid) in enumerate(artists, 1):
            print(f"[{i}/{len(artists)}] Refreshing {artist_name}...", end=" ")
            result = refresh_artist(artist_name, artist_mbid)

            if result["success"]:
                print(f"✓ {result['count']} releases")
                success_count += 1
                total_releases += result["count"]
            else:
                print(f"✗ {result['error']}")

        print(f"\nCompleted: {success_count}/{len(artists)} artists, {total_releases} total releases")


if __name__ == "__main__":
    main()
