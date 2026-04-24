#!/usr/bin/env python3
"""
Rename all scrobbles and associated data from one album name to another.

Usage:
    python -m app.services.rename_album "Artist" "Old Album Name" "New Album Name"
"""

import sys
import sqlite3
from pathlib import Path
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


def rename_album(artist: str, old_album: str, new_album: str, dry_run: bool = False):
    """
    Rename all scrobbles and associated data from one album name to another.

    Args:
        artist: Artist name to filter by (optional, use '*' for all artists)
        old_album: Current album name to rename
        new_album: New album name
        dry_run: If True, show what would be changed without making changes
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # First, let's see what we're working with
    if artist == "*":
        cursor.execute(
            "SELECT COUNT(*) as count, album FROM scrobble WHERE album = ? GROUP BY artist",
            (old_album,)
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) as count FROM scrobble WHERE artist = ? AND album = ?",
            (artist, old_album)
        )

    result = cursor.fetchone()
    count = result["count"] if result else 0

    if count == 0:
        logger.info(f"No scrobbles found matching artist='{artist}', album='{old_album}'")
        conn.close()
        return

    logger.info(f"Found {count} scrobble(s) with album='{old_album}'" + (f" for artist='{artist}'" if artist != "*" else ""))

    if dry_run:
        logger.info("[DRY RUN] Would make the following changes:")
        logger.info(f"  scrobble table: {count} rows")
        logger.info(f"  album_art table: unknown")
        logger.info(f"  album_tracks table: unknown")
        conn.close()
        return

    # Update scrobble table
    if artist == "*":
        cursor.execute(
            "UPDATE scrobble SET album = ? WHERE album = ?",
            (new_album, old_album)
        )
    else:
        cursor.execute(
            "UPDATE scrobble SET album = ? WHERE artist = ? AND album = ?",
            (new_album, artist, old_album)
        )
    scrobble_updated = cursor.rowcount
    logger.info(f"Updated {scrobble_updated} scrobble(s)")

    # Update album_art table
    if artist == "*":
        cursor.execute(
            "UPDATE album_art SET album = ? WHERE album = ?",
            (new_album, old_album)
        )
    else:
        cursor.execute(
            "UPDATE album_art SET album = ? WHERE artist = ? AND album = ?",
            (new_album, artist, old_album)
        )
    art_updated = cursor.rowcount
    logger.info(f"Updated {art_updated} album_art row(s)")

    # Update album_tracks table
    if artist == "*":
        cursor.execute(
            "UPDATE album_tracks SET album = ? WHERE album = ?",
            (new_album, old_album)
        )
    else:
        cursor.execute(
            "UPDATE album_tracks SET album = ? WHERE artist = ? AND album = ?",
            (new_album, artist, old_album)
        )
    tracks_updated = cursor.rowcount
    logger.info(f"Updated {tracks_updated} album_tracks row(s)")

    conn.commit()
    conn.close()

    logger.info(f"Successfully renamed '{old_album}' to '{new_album}'")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m app.services.rename_album <old_album> <new_album> [artist]")
        print("Example: python -m app.services.rename_album 'Led Zeppelin I' 'Led Zeppelin' 'Led Zeppelin'")
        print("Use '*' for artist to rename across all artists")
        sys.exit(1)

    old_album = sys.argv[1]
    new_album = sys.argv[2]
    artist = sys.argv[3] if len(sys.argv) > 3 else "*"

    # Confirm before proceeding
    print(f"About to rename album '{old_album}' to '{new_album}'" + (f" for artist '{artist}'" if artist != "*" else " (all artists)"))
    response = input("Continue? (y/N): ")
    if response.lower() != 'y':
        print("Cancelled")
        sys.exit(0)

    rename_album(artist, old_album, new_album)
