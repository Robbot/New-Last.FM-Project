#!/usr/bin/env python3
"""
Backfill album_mbid in album_tracks table.

This script updates album_tracks entries that are missing album_mbid
by copying the MBID from the scrobble or album_art table.
"""

import sqlite3
from pathlib import Path


def get_db_path() -> str:
    """Get the path to the SQLite database."""
    db_path_env = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path_env.exists():
        return str(db_path_env)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_conn():
    """Get a database connection."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def backfill_album_tracks_mbid(conn: sqlite3.Connection) -> int:
    """
    Backfill album_mbid in album_tracks table from scrobble and album_art tables.

    Returns:
        Number of album_tracks entries updated
    """
    # First, get MBIDs from album_art table (most reliable source)
    album_art_mbids = conn.execute(
        """
        SELECT artist, album, album_mbid
        FROM album_art
        WHERE album_mbid IS NOT NULL AND album_mbid != ''
        """
    ).fetchall()

    print(f"Found {len(album_art_mbids)} albums with MBIDs in album_art table")

    # Update album_tracks from album_art
    updated = 0
    for row in album_art_mbids:
        artist = row["artist"]
        album = row["album"]
        mbid = row["album_mbid"]

        cursor = conn.execute(
            """
            UPDATE album_tracks
            SET album_mbid = ?
            WHERE artist = ? AND album = ? AND (album_mbid IS NULL OR album_mbid = '')
            """,
            (mbid, artist, album),
        )
        updated += cursor.rowcount

    conn.commit()
    print(f"Updated {updated} album_tracks entries from album_art table")

    # Second, for remaining entries, try to get MBID from scrobble table
    # Group by (artist, album) to get one MBID per album
    remaining_rows = conn.execute(
        """
        SELECT DISTINCT at.artist, at.album
        FROM album_tracks at
        LEFT JOIN album_art aa ON at.artist = aa.artist AND at.album = aa.album
        WHERE (at.album_mbid IS NULL OR at.album_mbid = '')
          AND (aa.album_mbid IS NULL OR aa.album_mbid = '')
        """
    ).fetchall()

    print(f"Found {len(remaining_rows)} album_tracks entries still missing MBID")

    updated_from_scrobbles = 0
    for row in remaining_rows:
        artist = row["artist"]
        album = row["album"]

        # Get MBID from scrobbles for this artist/album
        scrobble_row = conn.execute(
            """
            SELECT album_mbid
            FROM scrobble
            WHERE artist = ? AND album = ? AND album_mbid IS NOT NULL AND album_mbid != ''
            LIMIT 1
            """,
            (artist, album),
        ).fetchone()

        if scrobble_row:
            mbid = scrobble_row["album_mbid"]
            cursor = conn.execute(
                """
                UPDATE album_tracks
                SET album_mbid = ?
                WHERE artist = ? AND album = ?
                """,
                (mbid, artist, album),
            )
            updated_from_scrobbles += cursor.rowcount

    conn.commit()
    print(f"Updated {updated_from_scrobbles} album_tracks entries from scrobble table")

    return updated + updated_from_scrobbles


def print_mbid_stats(conn: sqlite3.Connection) -> None:
    """Print statistics about MBID coverage."""
    total = conn.execute(
        "SELECT COUNT(*) as total FROM album_tracks"
    ).fetchone()

    with_mbid = conn.execute(
        "SELECT COUNT(*) as count FROM album_tracks WHERE album_mbid IS NOT NULL AND album_mbid != ''"
    ).fetchone()

    without_mbid = conn.execute(
        "SELECT COUNT(*) as count FROM album_tracks WHERE album_mbid IS NULL OR album_mbid = ''"
    ).fetchone()

    print(f"\nalbum_tracks MBID coverage:")
    print(f"  Total entries: {total['total']}")
    print(f"  With MBID: {with_mbid['count']} ({100 * with_mbid['count'] // total['total'] if total['total'] > 0 else 0}%)")
    print(f"  Without MBID: {without_mbid['count']}")


def main():
    """Run the backfill process."""
    print("Starting album_tracks album_mbid backfill...\n")

    conn = get_conn()

    # Show current state
    print_mbid_stats(conn)

    # Perform backfill
    print("\nBackfilling MBIDs...")
    updated = backfill_album_tracks_mbid(conn)

    # Show final state
    print("\nFinal state:")
    print_mbid_stats(conn)

    print(f"\nTotal updates: {updated}")
    print("Backfill complete!")

    conn.close()


if __name__ == "__main__":
    main()
