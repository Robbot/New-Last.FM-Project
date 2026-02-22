#!/usr/bin/env python3
"""
Clean small words capitalization from database.

This is a one-time migration script to fix capitalization of small words
like "for", "to", "and" in album and track names. These should be lowercase
except when they are the first or last word.

Examples:
    "Beatles For Sale" -> "Beatles for Sale"
    "Ride The Lightning" -> "Ride the Lightning"
    "Back And Forth" -> "Back and Forth" (last word stays capitalized)
"""

import sqlite3
import re
from pathlib import Path


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

# Small words that should be lowercase in titles (except first/last word)
_SMALL_WORDS = {
    'a', 'an', 'the', 'and', 'but', 'or', 'nor', 'for', 'so', 'yet',
    'at', 'by', 'from', 'in', 'into', 'of', 'off', 'on', 'onto', 'out',
    'over', 'to', 'up', 'with', 'as', 'but', 'via'
}


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def fix_small_words_case(title: str) -> str:
    """
    Fix capitalization of small words in titles to lowercase.
    These words should be lowercase except when they are the first or last word.
    """
    if not title:
        return title

    words = title.split()
    if not words:
        return title

    # Fix small words that are not first or last
    for i in range(1, len(words) - 1):
        word_lower = words[i].lower()
        if word_lower in _SMALL_WORDS:
            words[i] = word_lower

    return ' '.join(words)


def needs_fixing(title: str) -> bool:
    """Check if a title has small words that need fixing."""
    if not title:
        return False

    words = title.split()
    if len(words) < 3:  # Need at least 3 words to have a middle small word
        return False

    for i in range(1, len(words) - 1):
        word_lower = words[i].lower()
        if word_lower in _SMALL_WORDS and words[i] != word_lower:
            return True

    return False


def clean_album_names(conn: sqlite3.Connection) -> int:
    """
    Clean album names in the scrobble and album_art tables.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Get all unique albums that need fixing
    cur.execute("""
        SELECT DISTINCT artist, album
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY artist, album
    """)
    rows = cur.fetchall()

    updated_count = 0
    album_updates = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]

        if needs_fixing(album):
            new_album = fix_small_words_case(album)
            if new_album != album:
                album_updates.append((artist, album, new_album))

    if not album_updates:
        print("  No album names need fixing")
        return 0

    print(f"  Found {len(album_updates)} albums with small word capitalization issues")

    # Update scrobble table
    for artist, old_album, new_album in album_updates:
        print(f"  [{artist}] '{old_album}' -> '{new_album}'")
        cur.execute("""
            UPDATE scrobble
            SET album = ?
            WHERE artist = ? AND album = ?
        """, (new_album, artist, old_album))
        updated_count += cur.rowcount

    # Update album_art table using a simpler approach
    # For each update, we need to handle the PK constraint carefully
    # Strategy: Delete old row first, then insert new row (or update if exists)
    for artist, old_album, new_album in album_updates:
        # Get the old row data before deletion
        cur.execute("""
            SELECT * FROM album_art
            WHERE artist = ? AND album = ?
        """, (artist, old_album))
        old_row = cur.fetchone()

        if old_row:
            # Check if a row with the new album name already exists
            cur.execute("""
                SELECT * FROM album_art
                WHERE artist = ? AND album = ?
            """, (artist, new_album))
            existing_new_row = cur.fetchone()

            # Delete old row first
            cur.execute("""
                DELETE FROM album_art
                WHERE artist = ? AND album = ?
            """, (artist, old_album))

            # Handle optional columns
            wikipedia_url = old_row["wikipedia_url"] if "wikipedia_url" in old_row.keys() else None

            if existing_new_row:
                # A row with the new name already exists - merge data by updating the existing row
                # Use COALESCE to prefer non-null values from either row
                cur.execute("""
                    UPDATE album_art SET
                        album_mbid = COALESCE(?, album_mbid),
                        artist_mbid = COALESCE(?, artist_mbid),
                        image_small = COALESCE(?, image_small),
                        image_medium = COALESCE(?, image_medium),
                        image_large = COALESCE(?, image_large),
                        image_xlarge = COALESCE(?, image_xlarge),
                        last_updated = COALESCE(?, last_updated),
                        year_col = COALESCE(?, year_col),
                        wikipedia_url = COALESCE(?, wikipedia_url)
                    WHERE artist = ? AND album = ?
                """, (
                    old_row["album_mbid"], old_row["artist_mbid"],
                    old_row["image_small"], old_row["image_medium"],
                    old_row["image_large"], old_row["image_xlarge"],
                    old_row["last_updated"], old_row["year_col"],
                    wikipedia_url,
                    artist, new_album
                ))
            else:
                # No existing row with new name - insert fresh
                cur.execute("""
                    INSERT INTO album_art (
                        artist, album, album_mbid, artist_mbid,
                        image_small, image_medium, image_large, image_xlarge,
                        last_updated, year_col, wikipedia_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    artist, new_album,
                    old_row["album_mbid"], old_row["artist_mbid"],
                    old_row["image_small"], old_row["image_medium"],
                    old_row["image_large"], old_row["image_xlarge"],
                    old_row["last_updated"], old_row["year_col"],
                    wikipedia_url
                ))
            updated_count += 1

    conn.commit()
    return updated_count


def clean_track_names(conn: sqlite3.Connection) -> int:
    """
    Clean track names in the scrobble and album_tracks tables.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Get all unique tracks that need fixing
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        GROUP BY artist, album, track
    """)
    rows = cur.fetchall()

    updated_count = 0
    track_updates = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]

        if needs_fixing(track):
            new_track = fix_small_words_case(track)
            if new_track != track:
                track_updates.append((artist, album, track, new_track))

    if not track_updates:
        print("  No track names need fixing")
        return 0

    print(f"  Found {len(track_updates)} tracks with small word capitalization issues")

    # Update scrobble table
    for artist, album, old_track, new_track in track_updates:
        print(f"  [{artist}] '{album}': '{old_track}' -> '{new_track}'")
        cur.execute("""
            UPDATE scrobble
            SET track = ?
            WHERE artist = ? AND album = ? AND track = ?
        """, (new_track, artist, album, old_track))
        updated_count += cur.rowcount

    # Update album_tracks table
    for artist, album, old_track, new_track in track_updates:
        cur.execute("""
            SELECT * FROM album_tracks
            WHERE artist = ? AND album = ? AND track = ?
        """, (artist, album, old_track))
        old_row = cur.fetchone()

        if old_row:
            cur.execute("""
                UPDATE album_tracks
                SET track = ?
                WHERE artist = ? AND album = ? AND track = ?
            """, (new_track, artist, album, old_track))
            updated_count += cur.rowcount

    conn.commit()
    return updated_count


def main():
    print("Starting small words capitalization cleanup...")
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
        # Clean album names
        print("\n--- Cleaning album names ---")
        album_updated = clean_album_names(conn)
        print(f"Album tables: {album_updated} rows updated")

        # Clean track names
        print("\n--- Cleaning track names ---")
        track_updated = clean_track_names(conn)
        print(f"Track tables: {track_updated} rows updated")

        total_updated = album_updated + track_updated
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
