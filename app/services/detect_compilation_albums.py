#!/usr/bin/env python3
"""
Detect and mark compilation albums by setting album_artist to 'Various Artists'.

This script identifies albums that are compilations (various artists on one album)
and updates all scrobbles to have album_artist = 'Various Artists'.

A compilation is detected when:
1. An album has tracks by multiple different artists (not all the same)
2. The album doesn't already have album_artist set to a single artist name
"""

import sqlite3
from pathlib import Path
from collections import defaultdict


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_album_artist_stats(conn: sqlite3.Connection) -> dict[tuple[str, str], list[str]]:
    """
    Get all unique artists per (artist, album) combination.
    Returns dict mapping (artist, album) -> list of unique track artists.
    """
    cur = conn.cursor()

    # Get all unique (artist, album, track_artist) combinations
    # Note: 'artist' is the track artist, 'album' is the album name
    cur.execute("""
        SELECT DISTINCT artist, album, album_artist
        FROM scrobble
        ORDER BY album, artist
    """)

    rows = cur.fetchall()

    # Group by album
    album_artists = defaultdict(list)
    for row in rows:
        album = row["album"]
        track_artist = row["artist"]
        album_artist = row["album_artist"]

        # Use album as key, collect track artists
        album_artists[album].append((track_artist, album_artist))

    return album_artists


def find_compilation_albums(album_artists: dict[tuple[str, str], list[tuple[str, str]]]) -> set[str]:
    """
    Identify compilation albums from the artist stats.
    Returns set of album names that are compilations.
    """
    compilation_albums = set()

    for album, artist_list in album_artists.items():
        # Get unique track artists for this album
        track_artists = set(artist for artist, _ in artist_list)

        # Get unique album_artist values for this album
        album_artists_set = set(aa for _, aa in artist_list if aa)

        # Skip if already all marked as Various Artists
        if album_artists_set == {"Various Artists"}:
            continue

        # If there's only one unique track artist, it's probably not a compilation
        # (unless it's already marked as Various Artists)
        if len(track_artists) == 1:
            single_artist = list(track_artists)[0]
            # Skip if the single artist matches all album_artist values
            if all(aa in (single_artist, "Various Artists", None, "") for _, aa in artist_list):
                continue

        # If we have multiple different track artists, it's a compilation
        if len(track_artists) > 1:
            compilation_albums.add(album)
        # Also check if album_artist values are inconsistent
        elif len(album_artists_set) > 1:
            compilation_albums.add(album)

    return compilation_albums


def update_compilation_albums(conn: sqlite3.Connection, compilation_albums: set[str]) -> int:
    """
    Update all scrobbles for compilation albums to have album_artist = 'Various Artists'.
    Returns the number of rows updated.
    """
    cur = conn.cursor()
    total_updated = 0

    for album in sorted(compilation_albums):
        # Update all scrobbles for this album
        cur.execute("""
            UPDATE scrobble
            SET album_artist = 'Various Artists'
            WHERE album = ? AND album_artist != 'Various Artists'
        """, (album,))

        changes = cur.rowcount
        if changes > 0:
            total_updated += changes
            # Show a sample of artists for this album
            cur.execute("""
                SELECT DISTINCT artist
                FROM scrobble
                WHERE album = ?
                LIMIT 5
            """, (album,))
            sample_artists = [row["artist"] for row in cur.fetchall()]
            artists_str = ", ".join(sample_artists)
            if len(sample_artists) < cur.execute("SELECT COUNT(DISTINCT artist) FROM scrobble WHERE album = ?", (album,)).fetchone()[0]:
                artists_str += ", ..."
            print(f"  Updated '{album}': {changes} scrobbles (artists: {artists_str})")

    conn.commit()
    return total_updated


def main():
    print("Detecting compilation albums...")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    conn = get_conn()

    # Backup the database before making changes
    backup_path = DB_PATH.with_suffix(".sqlite.backup")
    print(f"\nCreating backup at: {backup_path}")
    import shutil
    shutil.copy2(DB_PATH, backup_path)
    print("Backup created successfully.")

    try:
        # Get album artist statistics
        print("\nAnalyzing albums for compilation detection...")
        album_artists = get_album_artist_stats(conn)

        # Find compilation albums
        compilation_albums = find_compilation_albums(album_artists)

        if not compilation_albums:
            print("No compilation albums found that need updating.")
            return

        print(f"Found {len(compilation_albums)} compilation album(s) to update:")
        for album in sorted(compilation_albums):
            # Count unique artists
            cur = conn.cursor()
            cur.execute("""
                SELECT COUNT(DISTINCT artist) as count
                FROM scrobble
                WHERE album = ?
            """, (album,))
            artist_count = cur.fetchone()["count"]
            print(f"  - '{album}' ({artist_count} artists)")

        # Update compilation albums
        print("\nUpdating scrobbles...")
        total_updated = update_compilation_albums(conn, compilation_albums)

        print(f"\nDone. Updated {total_updated} scrobble(s) across {len(compilation_albums)} album(s).")
        print(f"Backup saved at: {backup_path}")

    except Exception as e:
        print(f"\nERROR during compilation detection: {e}")
        import traceback
        traceback.print_exc()
        print("\nRolling back changes...")
        conn.rollback()
        print("Changes rolled back. You can restore from backup if needed.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
