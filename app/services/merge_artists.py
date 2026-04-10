#!/usr/bin/env python3
"""
Merge one artist name into another in the database.

Usage:
    python -m app.services.merge_artists "Smashing Pumpkins" "The Smashing Pumpkins"
"""
import sys
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def merge_artists(from_artist: str, to_artist: str) -> None:
    """
    Merge all scrobbles from one artist name to another.

    Updates the scrobble table in-place.
    """
    print(f"Merging artist: '{from_artist}' → '{to_artist}'")

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        # Check what we're about to change
        cur = conn.cursor()
        cur.execute(
            "SELECT COUNT(*) as count FROM scrobble WHERE artist = ?",
            (from_artist,)
        )
        count = cur.fetchone()["count"]

        if count == 0:
            print(f"No scrobbles found for '{from_artist}'")
            return

        # Show affected albums
        cur.execute(
            "SELECT DISTINCT album FROM scrobble WHERE artist = ?",
            (from_artist,)
        )
        albums = [row["album"] for row in cur.fetchall()]

        print(f"Found {count} scrobbles across {len(albums)} albums:")
        for album in albums:
            cur.execute(
                """SELECT COUNT(*) as count FROM scrobble
                   WHERE artist = ? AND album = ?""",
                (from_artist, album)
            )
            album_count = cur.fetchone()["count"]
            print(f"  - {album}: {album_count} scrobbles")

        # Confirm before proceeding
        response = input("\nProceed with merge? [y/N] ")
        if response.lower() != 'y':
            print("Aborted.")
            return

        # Update scrobbles
        cur.execute(
            "UPDATE scrobble SET artist = ? WHERE artist = ?",
            (to_artist, from_artist)
        )
        conn.commit()

        print(f"\n✓ Merged {cur.rowcount} scrobbles")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python -m app.services.merge_artists <from_artist> <to_artist>")
        print("Example: python -m app.services.merge_artists 'Smashing Pumpkins' 'The Smashing Pumpkins'")
        sys.exit(1)

    from_artist = sys.argv[1]
    to_artist = sys.argv[2]

    merge_artists(from_artist, to_artist)
