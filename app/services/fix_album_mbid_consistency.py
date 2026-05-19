#!/usr/bin/env python3
"""
Fix album_mbid consistency across album_art and scrobble tables.

1. Backfill missing album_mbid in album_art from scrobbles
2. Update scrobble MBIDs to match album_art (where album_art has the canonical MBID)
"""
import sqlite3
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connections import get_db_connection


def fix_missing_album_art_mbids():
    """Backfill missing album_mbid in album_art from scrobbles."""
    conn = get_db_connection()

    # Find albums where album_art has no MBID but scrobbles do
    query = """
        SELECT
            aa.artist,
            aa.album,
            s.album_mbid as scrobble_mbid,
            COUNT(*) as scrobble_count
        FROM album_art aa
        JOIN scrobble s ON s.artist = aa.artist AND s.album = aa.album
        WHERE (aa.album_mbid IS NULL OR aa.album_mbid = '' OR TRIM(aa.album_mbid) = '')
          AND s.album_mbid IS NOT NULL
          AND TRIM(s.album_mbid) != ''
        GROUP BY aa.artist, aa.album, s.album_mbid
        ORDER BY scrobble_count DESC
    """

    rows = conn.execute(query).fetchall()

    if not rows:
        print("No albums with missing album_mbid in album_art found.")
        return 0

    updated = 0
    for row in rows:
        artist = row["artist"]
        album = row["album"]
        mbid = row["scrobble_mbid"]
        count = row["scrobble_count"]

        print(f"Updating {artist} - {album} with MBID {mbid} ({count} scrobbles)")

        conn.execute(
            "UPDATE album_art SET album_mbid = ? WHERE artist = ? AND album = ?",
            (mbid, artist, album)
        )
        updated += 1

    conn.commit()
    conn.close()
    return updated


def fix_scrobble_mbids_to_match_album_art():
    """Update scrobble MBIDs to match album_art (canonical source)."""
    conn = get_db_connection()

    # Find albums where album_art has MBID but scrobbles have different MBIDs
    # Update scrobbles to use the album_art MBID
    query = """
        SELECT
            aa.artist,
            aa.album,
            aa.album_mbid as art_mbid,
            s.album_mbid as scrobble_mbid,
            COUNT(*) as scrobble_count
        FROM album_art aa
        JOIN scrobble s ON s.artist = aa.artist AND s.album = aa.album
        WHERE aa.album_mbid IS NOT NULL
          AND TRIM(aa.album_mbid) != ''
          AND s.album_mbid IS NOT NULL
          AND TRIM(s.album_mbid) != ''
          AND s.album_mbid != aa.album_mbid
        GROUP BY aa.artist, aa.album, aa.album_mbid, s.album_mbid
        ORDER BY scrobble_count DESC
    """

    rows = conn.execute(query).fetchall()

    if not rows:
        print("No albums with MBID mismatches found.")
        return 0

    updated_albums = set()
    total_scrobbles = 0

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        art_mbid = row["art_mbid"]
        scrobble_mbid = row["scrobble_mbid"]
        count = row["scrobble_count"]

        print(f"Updating {artist} - {album}: {scrobble_mbid} → {art_mbid} ({count} scrobbles)")

        # Update all scrobbles for this album to use the album_art MBID
        conn.execute(
            """
            UPDATE scrobble
            SET album_mbid = ?
            WHERE artist = ? AND album = ? AND album_mbid = ?
            """,
            (art_mbid, artist, album, scrobble_mbid)
        )

        updated_albums.add(f"{artist} - {album}")
        total_scrobbles += count

    conn.commit()
    conn.close()

    print(f"\nUpdated {total_scrobbles} scrobbles across {len(updated_albums)} albums")
    return len(updated_albums)


def main():
    print("=== Fixing album_mbid consistency ===\n")

    print("Step 1: Backfill missing album_mbid in album_art from scrobbles")
    print("-" * 60)
    album_art_updated = fix_missing_album_art_mbids()
    print(f"Updated {album_art_updated} album_art entries\n")

    print("\nStep 2: Update scrobble MBIDs to match album_art")
    print("-" * 60)
    albums_updated = fix_scrobble_mbids_to_match_album_art()
    print(f"Updated scrobbles for {albums_updated} albums\n")

    print("\n=== Summary ===")
    print(f"album_art entries updated: {album_art_updated}")
    print(f"Albums with scrobble MBIDs updated: {albums_updated}")


if __name__ == "__main__":
    main()
