#!/usr/bin/env python3
"""
Clean existing Deluxe Edition suffixes from database.

This is a one-time migration script to remove artificial Deluxe Edition
suffixes from existing scrobble, album_art, and album_tracks records that
were inserted before the cleaning was added to sync_lastfm.py.

Run this after deploying the Deluxe Edition cleaning fix to clean historical data.
"""

import sqlite3
import re
import shutil
from pathlib import Path


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


# ---------- Regex patterns ----------
# Deluxe Edition variants
_DELUXE_PATTERNS = [
    # Standard dash-separated patterns
    r" -\s+(?:Deluxe Edition|deluxe edition)\s*$",
    r"\s+(?:Deluxe Edition|deluxe edition)\s*$",
    # Parenthetical patterns
    r"\s*[\(\[]\s*(?:Deluxe Edition|deluxe edition)\s*[\)\]]\s*$",
    # Slash separator patterns (e.g., "Soundtrack / Deluxe Edition")
    r"\s*/\s*(?:Deluxe Edition|deluxe edition)\s*[\)\]]*\s*$",
    r"\s+/ *(?:Deluxe Edition|deluxe edition)\s*$",
]


def clean_deluxe_suffix(title: str) -> str:
    """Remove artificial Deluxe Edition suffixes from a title."""
    if not title:
        return title

    cleaned = title
    for pattern in _DELUXE_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Fix unbalanced parentheses - if we have an opening ( but no closing ), remove it
    cleaned = re.sub(r'\s*\(\s*[^)]*$', "", cleaned.strip())

    return cleaned.strip()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def clean_scrobble_table(conn: sqlite3.Connection) -> int:
    """
    Clean album and track names in the scrobble table.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Get all unique (artist, album, track) combinations that have Deluxe Edition suffix
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE album LIKE '%Deluxe Edition%'
           OR album LIKE '%deluxe edition%'
           OR album LIKE '%(Deluxe Edition)%'
           OR track LIKE '%Deluxe Edition%'
           OR track LIKE '%deluxe edition%'
           OR track LIKE '%(Deluxe Edition)%'
    """)
    rows = cur.fetchall()

    updated_count = 0

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]

        # Clean album and track names
        cleaned_album = clean_deluxe_suffix(album)
        cleaned_track = clean_deluxe_suffix(track)

        # Skip if no changes needed
        if cleaned_album == album and cleaned_track == track:
            continue

        # Update all matching rows
        cur.execute("""
            UPDATE scrobble
            SET album = ?, track = ?
            WHERE artist = ? AND album = ? AND track = ?
        """, (cleaned_album, cleaned_track, artist, album, track))

        changes = cur.rowcount
        if changes > 0:
            updated_count += changes
            print(f"  Updated scrobble: {artist} | '{album}' -> '{cleaned_album}' | '{track}' -> '{cleaned_track}'")

    conn.commit()
    return updated_count


def clean_album_art_table(conn: sqlite3.Connection) -> int:
    """
    Clean album names in the album_art table.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Get all rows that need cleaning
    cur.execute("""
        SELECT * FROM album_art
        WHERE album LIKE '%Deluxe Edition%'
           OR album LIKE '%deluxe edition%'
           OR album LIKE '%(Deluxe Edition)%'
    """)
    rows = cur.fetchall()

    updated_count = 0
    albums_to_delete = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]

        # Clean album name
        cleaned_album = clean_deluxe_suffix(album)

        # Skip if no changes needed
        if cleaned_album == album:
            continue

        # Use INSERT OR REPLACE to handle cases where cleaned album already exists
        cur.execute("""
            INSERT OR REPLACE INTO album_art (
                artist, album, album_mbid, artist_mbid,
                image_small, image_medium, image_large, image_xlarge,
                last_updated, year_col
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            artist, cleaned_album, row["album_mbid"], row["artist_mbid"],
            row["image_small"], row["image_medium"], row["image_large"], row["image_xlarge"],
            row["last_updated"], row["year_col"]
        ))

        updated_count += 1
        print(f"  Updated album_art: {artist} | '{album}' -> '{cleaned_album}'")

        # Track old album for deletion
        albums_to_delete.append((artist, album))

    # Delete old entries (after all inserts to avoid conflicts)
    for artist, album in albums_to_delete:
        cur.execute("""
            DELETE FROM album_art
            WHERE artist = ? AND album = ?
        """, (artist, album))

    conn.commit()
    return updated_count


def clean_album_tracks_table(conn: sqlite3.Connection) -> int:
    """
    Clean track names AND album names in the album_tracks table.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Get all rows that need cleaning (check both track and album columns)
    cur.execute("""
        SELECT * FROM album_tracks
        WHERE track LIKE '%Deluxe Edition%'
           OR track LIKE '%deluxe edition%'
           OR track LIKE '%(Deluxe Edition)%'
           OR album LIKE '%Deluxe Edition%'
           OR album LIKE '%deluxe edition%'
           OR album LIKE '%(Deluxe Edition)%'
    """)
    rows = cur.fetchall()

    updated_count = 0

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]
        track_number = row["track_number"]
        # Check if duration column exists
        duration = row["duration"] if "duration" in row.keys() else None

        # Clean both track and album names
        cleaned_track = clean_deluxe_suffix(track)
        cleaned_album = clean_deluxe_suffix(album)

        # Skip if no changes needed
        if cleaned_track == track and cleaned_album == album:
            continue

        # Use INSERT OR REPLACE to handle cases where cleaned track already exists
        # First, delete the old entry if we're going to replace it
        cur.execute("""
            DELETE FROM album_tracks
            WHERE artist = ? AND album = ? AND track_number = ?
        """, (artist, album, track_number))

        # Insert the cleaned version
        if duration is not None:
            cur.execute("""
                INSERT OR REPLACE INTO album_tracks (artist, album, track, track_number, duration)
                VALUES (?, ?, ?, ?, ?)
            """, (artist, cleaned_album, cleaned_track, track_number, duration))
        else:
            cur.execute("""
                INSERT OR REPLACE INTO album_tracks (artist, album, track, track_number)
                VALUES (?, ?, ?, ?)
            """, (artist, cleaned_album, cleaned_track, track_number))

        updated_count += 1
        print(f"  Updated album_tracks: {artist} | '{album}' -> '{cleaned_album}' | '{track}' -> '{cleaned_track}'")

    conn.commit()
    return updated_count


def main():
    print("Starting Deluxe Edition cleanup...")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    # Show preview of what will be cleaned
    print("\n--- Preview of albums to be cleaned ---")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT album, artist FROM scrobble
        WHERE album LIKE '%Deluxe Edition%'
           OR album LIKE '%deluxe edition%'
           OR album LIKE '%(Deluxe Edition)%'
        ORDER BY album
        LIMIT 20
    """)
    preview_rows = cur.fetchall()
    if preview_rows:
        for row in preview_rows:
            print(f"  - {row['artist']}: '{row['album']}'")
    else:
        print("  No Deluxe Edition suffixes found in database.")

    conn.close()

    if not preview_rows:
        print("\nNo cleanup needed. Exiting.")
        return

    # Create backup
    conn = get_conn()
    backup_path = DB_PATH.with_suffix(".sqlite.backup")
    print(f"\nCreating backup at: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print("Backup created successfully.")

    try:
        # Clean scrobble table
        print("\n--- Cleaning scrobble table ---")
        scrobble_updated = clean_scrobble_table(conn)
        print(f"Scrobble table: {scrobble_updated} rows updated")

        # Clean album_art table
        print("\n--- Cleaning album_art table ---")
        album_art_updated = clean_album_art_table(conn)
        print(f"Album art table: {album_art_updated} rows updated")

        # Clean album_tracks table
        print("\n--- Cleaning album_tracks table ---")
        album_tracks_updated = clean_album_tracks_table(conn)
        print(f"Album tracks table: {album_tracks_updated} rows updated")

        total_updated = scrobble_updated + album_art_updated + album_tracks_updated
        print(f"\nDone. Total rows updated: {total_updated}")
        print(f"Backup saved at: {backup_path}")

    except Exception as e:
        print(f"\nERROR during cleanup: {e}")
        import traceback
        traceback.print_exc()
        print("\nRolling back changes...")
        conn.rollback()
        print("Changes rolled back. You can restore from backup if needed.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
