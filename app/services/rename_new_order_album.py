#!/usr/bin/env python3
"""
Rename New Order's album "Power corruption and lies" to "Power, Corruption and Lies".

This is a one-time script to fix the incorrect album name across all database tables.
"""

import sqlite3
from pathlib import Path
import shutil


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

# The rename mapping
ARTIST = "New Order"
OLD_ALBUM = "Power corruption and lies"
NEW_ALBUM = "Power, Corruption and Lies"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def update_scrobble_table(conn: sqlite3.Connection) -> int:
    """Update album name in scrobble table."""
    cur = conn.cursor()

    cur.execute("""
        UPDATE scrobble
        SET album = ?
        WHERE artist = ? AND album = ?
    """, (NEW_ALBUM, ARTIST, OLD_ALBUM))

    count = cur.rowcount
    conn.commit()
    return count


def update_album_art_table(conn: sqlite3.Connection) -> int:
    """
    Update album name in album_art table.
    Since the correct version may already exist, we need to handle merging.
    """
    cur = conn.cursor()

    # Check if the correct album already exists
    cur.execute("""
        SELECT * FROM album_art
        WHERE artist = ? AND album = ?
    """, (ARTIST, NEW_ALBUM))
    existing = cur.fetchone()

    # Get the old entry
    cur.execute("""
        SELECT * FROM album_art
        WHERE artist = ? AND album = ?
    """, (ARTIST, OLD_ALBUM))
    old_entry = cur.fetchone()

    if not old_entry:
        return 0

    count = 1

    if existing:
        # Merge: prefer the new entry, but update if old has missing data
        # For simplicity, just delete the old one since the correct one exists
        cur.execute("""
            DELETE FROM album_art
            WHERE artist = ? AND album = ?
        """, (ARTIST, OLD_ALBUM))
        print(f"  Deleted duplicate album_art: {ARTIST} | '{OLD_ALBUM}' (correct version already exists)")
    else:
        # Rename the entry
        cur.execute("""
            UPDATE album_art
            SET album = ?
            WHERE artist = ? AND album = ?
        """, (NEW_ALBUM, ARTIST, OLD_ALBUM))
        print(f"  Renamed album_art: {ARTIST} | '{OLD_ALBUM}' -> '{NEW_ALBUM}'")

    conn.commit()
    return count


def update_album_tracks_table(conn: sqlite3.Connection) -> int:
    """
    Update album name in album_tracks table.
    Since the correct version may already have the same tracks, we need to
    delete duplicates to avoid UNIQUE constraint violations.
    """
    cur = conn.cursor()

    # Check which tracks exist in both old and new album
    cur.execute("""
        SELECT track FROM album_tracks
        WHERE artist = ? AND album = ?
    """, (ARTIST, NEW_ALBUM))
    existing_tracks = set(row["track"] for row in cur.fetchall())

    # Get tracks from old album
    cur.execute("""
        SELECT * FROM album_tracks
        WHERE artist = ? AND album = ?
    """, (ARTIST, OLD_ALBUM))
    old_tracks = cur.fetchall()

    count = 0
    for track_row in old_tracks:
        track_name = track_row["track"]
        track_number = track_row["track_number"]

        if track_name in existing_tracks:
            # Track already exists in correct album, delete duplicate
            cur.execute("""
                DELETE FROM album_tracks
                WHERE artist = ? AND album = ? AND track = ? AND track_number = ?
            """, (ARTIST, OLD_ALBUM, track_name, track_number))
            print(f"  Deleted duplicate album_tracks: {ARTIST} | '{OLD_ALBUM}' | track: '{track_name}' (already in correct album)")
        else:
            # Track doesn't exist in correct album, move it
            cur.execute("""
                UPDATE album_tracks
                SET album = ?
                WHERE artist = ? AND album = ? AND track = ? AND track_number = ?
            """, (NEW_ALBUM, ARTIST, OLD_ALBUM, track_name, track_number))
            print(f"  Moved album_tracks: {ARTIST} | '{OLD_ALBUM}' | track: '{track_name}' -> '{NEW_ALBUM}'")

        count += 1

    conn.commit()
    return count


def main():
    print(f"Renaming album: {ARTIST} - '{OLD_ALBUM}' -> '{NEW_ALBUM}'")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    # Backup the database before making changes
    backup_path = DB_PATH.with_suffix(".sqlite.backup")
    print(f"\nCreating backup at: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print("Backup created successfully.")

    conn = get_conn()

    try:
        # Update scrobble table
        print("\n--- Updating scrobble table ---")
        scrobble_updated = update_scrobble_table(conn)
        print(f"Scrobble table: {scrobble_updated} rows updated")

        # Update album_art table
        print("\n--- Updating album_art table ---")
        album_art_updated = update_album_art_table(conn)
        print(f"Album art table: {album_art_updated} rows updated")

        # Update album_tracks table
        print("\n--- Updating album_tracks table ---")
        album_tracks_updated = update_album_tracks_table(conn)
        print(f"Album tracks table: {album_tracks_updated} rows updated")

        total_updated = scrobble_updated + album_art_updated + album_tracks_updated
        print(f"\nDone. Total rows updated: {total_updated}")
        print(f"Backup saved at: {backup_path}")

    except Exception as e:
        print(f"\nERROR during update: {e}")
        import traceback
        traceback.print_exc()
        print("\nRolling back changes...")
        conn.rollback()
        print("Changes rolled back. You can restore from backup if needed.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
