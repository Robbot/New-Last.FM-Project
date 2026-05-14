#!/usr/bin/env python3
"""
Fix vinyl/cassette style track numbers in the album_tracks table.

Converts track numbers like "A1", "A2", "B1" to sequential integers 1, 2, 3...
"""

import sqlite3
import logging
from app.logging_config import get_logger
from app.db.connections import DB_PATH

logger = get_logger(__name__)


def get_db_path():
    """Return the database path."""
    return DB_PATH


def fix_track_numbers_for_album(artist: str, album: str) -> bool:
    """
    Fix track numbers for a specific album by renumbering sequentially.

    Args:
        artist: Artist name
        album: Album name

    Returns True if successful, False otherwise.
    """
    db_path = get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all tracks for this album ordered by current track_number
        cursor.execute(
            """
            SELECT track, track_mbid FROM album_tracks
            WHERE artist = ? AND album = ?
            ORDER BY track_number
            """,
            (artist, album)
        )
        tracks = cursor.fetchall()

        # Update each track with sequential numbering
        for idx, track in enumerate(tracks, start=1):
            cursor.execute(
                """
                UPDATE album_tracks
                SET track_number = ?
                WHERE artist = ? AND album = ? AND track = ?
                """,
                (idx, artist, album, track["track"])
            )

        conn.commit()
        conn.close()
        logger.info(f"Fixed {len(tracks)} tracks for {artist} - {album}")
        return True

    except sqlite3.Error as e:
        logger.error(f"Database error fixing track numbers for {artist} - {album}: {e}")
        return False


def find_and_fix_all_vinyl_tracks() -> dict[str, list[tuple[str, str]]]:
    """
    Find all albums with vinyl/cassette style track numbers and fix them.

    Returns:
        Dictionary with 'fixed' and 'failed' keys containing lists of (artist, album) tuples
    """
    db_path = get_db_path()
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Find all unique albums with non-numeric track numbers
        cursor.execute(
            """
            SELECT DISTINCT artist, album
            FROM album_tracks
            WHERE track_number GLOB '*[A-Za-z]*'
            ORDER BY artist, album
            """
        )
        albums = [(row["artist"], row["album"]) for row in cursor.fetchall()]
        conn.close()

        logger.info(f"Found {len(albums)} albums with vinyl/cassette style track numbers")

        results = {"fixed": [], "failed": []}

        for artist, album in albums:
            if fix_track_numbers_for_album(artist, album):
                results["fixed"].append((artist, album))
            else:
                results["failed"].append((artist, album))

        logger.info(f"Fixed {len(results['fixed'])} albums, {len(results['failed'])} failed")
        return results

    except sqlite3.Error as e:
        logger.error(f"Database error finding vinyl tracks: {e}")
        return {"fixed": [], "failed": []}


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fix vinyl/cassette style track numbers')
    parser.add_argument('--artist', help='Artist name (to fix specific album)')
    parser.add_argument('--album', help='Album name (to fix specific album)')
    parser.add_argument('--list', action='store_true', help='List albums with vinyl track numbers without fixing')

    args = parser.parse_args()

    if args.list:
        # Just list the albums
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT DISTINCT artist, album
            FROM album_tracks
            WHERE track_number GLOB '*[A-Za-z]*'
            ORDER BY artist, album
            """
        )

        print("Albums with vinyl/cassette style track numbers:")
        for row in cursor.fetchall():
            print(f"  {row['artist']} - {row['album']}")

        conn.close()

    elif args.artist and args.album:
        # Fix specific album
        if fix_track_numbers_for_album(args.artist, args.album):
            print(f"Successfully fixed track numbers for {args.artist} - {args.album}")
        else:
            print(f"Failed to fix track numbers for {args.artist} - {args.album}")

    else:
        # Fix all
        results = find_and_fix_all_vinyl_tracks()

        print(f"\nFixed {len(results['fixed'])} albums:")
        for artist, album in results['fixed']:
            print(f"  ✓ {artist} - {album}")

        if results['failed']:
            print(f"\nFailed to fix {len(results['failed'])} albums:")
            for artist, album in results['failed']:
                print(f"  ✗ {artist} - {album}")


if __name__ == "__main__":
    main()
