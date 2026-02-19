#!/usr/bin/env python3
"""
Clean existing remastered/remaster and expanded edition suffixes from database.

This is a one-time migration script to remove artificial remastered/remaster
and expanded edition suffixes from existing scrobble, album_art, and album_tracks
records that were inserted before the cleaning was added to sync_lastfm.py.

Run this after deploying the remaster/expanded cleaning fix to clean historical data.
"""

import sqlite3
import re
from pathlib import Path


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


# ---------- Regex patterns ----------
# Same patterns used in sync_lastfm.py
# Order matters: more specific patterns (with year) must come before less specific ones
_REMASTER_PATTERNS = [
    # Year + Remaster/Remastered + Version (most specific - must be first)
    r"\s*[\(\[]\s*\d{4}\s+-\s+(?:Remastered|Remaster|remastered|remaster)\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*[\)\]]\s*$",
    # Year + Remastered/Remaster with "Version" suffix
    r" -\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*$",
    r"\s+-\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*$",
    r" -\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    r"\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    # Word BEFORE year (less specific - comes after)
    r" -\s+(?:Remastered|Remaster|remastered|remaster)(?:\s+-\s+\d{4})?\s*$",
    r" -\s+(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*$",
    r"\s+(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*$",
    r"\s*[\(\[]\s*(?:Remastered|Remaster|remastered|remaster)(?:\s+-\s+\d{4})?\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*[\)\]]\s*$",
    # Digital Remaster variants
    r"\s+(?:\d{4}\s+)?(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*$",
    r"\s*[\(\[]\s*(?:\d{4}\s+)?(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*[\)\]]\s*$",
    # Expanded Edition variants (including just "Expanded")
    r" -\s+(?:Expanded\s+Edition|Expanded)\s*$",
    r"\s+(?:Expanded\s+Edition|Expanded)\s*$",
    r"\s*[\(\[]\s*(?:Expanded\s+Edition|expanded\s+edition|Expanded)\s*[\)\]]\s*$",
    # Expanded Version
    r"\s*[\(\[]\s*Expanded\s+Version\s*[\)\]]\s*$",
    # Mix/version suffixes (e.g., "2007 Stereo Mix", "2009 Remaster", "2011 Mix")
    r" -\s+\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*$",
    r"\s+[\(\[]\s*\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*[\)\]]\s*$",
    r"\s+\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*$",
    # Single Version, Album Version, Remix variations (without year)
    r" -\s+(?:Single\s+Version|Album\s+Version|Remix|Mix)\s*$",
    r"\s*[\(\[]\s*(?:Single\s+Version|Album\s+Version|Remix|Mix)\s*[\)\]]\s*$",
    # (Remastered) without year
    r"\s*[\(\[]\s*Remastered\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*Remaster\s*[\)\]]\s*$",
    # Semicolon-separated remaster suffixes (e.g., "Track; 2006 Remaster")
    r";\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*$",
    r";\s*(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*$",
    r";\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    # Remastered LP/CD Version patterns
    r"\s*[\(\[]\s*Remastered\s+(?:LP|CD)\s+Version\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*\d{4}\s+Remastered\s+Version\s*[\)\]]\s*$",
    # Suffix with "Remaster" at the end after semicolon
    r";\s*(?:\d{4}\s+)?[Rr]emaster(?:ed)?\s*$",
    # Semicolon without space
    r";\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    # Slash separator patterns (e.g., "Version / Remastered")
    r"/\s*Remastered\s*$",
    r"\s*/\s*[Rr]emaster(?:ed)?\s*$",
    # Remastered + Edit/UK Release/Mono etc.
    r"\s*[\(\[]\s*Remastered\s+(?:Edit|UK\s+Release|Digital\s+Release|Version)\s*[\)\]]?\s*$",
    r" -\s+Remastered\s+(?:Edit|UK\s+Release|Digital\s+Release)\s*$",
    r" -\s+Remastered\s+Edit\s*$",
    r"\s+Remastered\s+Edit\s*$",
    # Year before Remaster (reverse order)
    r" -\s+Remastered\s+\d{4}\s*(?:/|;)\s*\w+\s*$",
    # 24-Bit Digitally Remaster patterns
    r"\s*[\(\[]\s*\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s+\d+\s*[\)\]]?\s*$",
    r"\s*[\(\[]\s*\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s*[\)\]]?\s*$",
    # Bracket patterns with dash (e.g., "[2009 Remaster - Mono]")
    r"\s*[\(\[]\s*\d{4}\s+[Rr]emaster(?:ed)?\s*-\s*\w+\s*[\)\]]\s*$",
    # Digitally Remaster with year at end
    r"\s*[\(\[]\s*(?:Digitally\s+)?[Rr]emaster(?:ed)?\s+\d+\s*[\)\]]?\s*$",
    # Semicolon without space and "Remaster" at end
    r";\d{4}\s+Remaster\s*\)*\s*$",
    r";\d{4}\s+(?:Digitally\s+)?Remaster\s*\)*\s*$",
    # Prefix before semicolon+remaster (e.g., "Dub; 2005 Digital Remaster")
    r"\s*[\(\[]\s*[\w\s]+;\s+\d{4}\s+(?:Digitally\s+)?[Rr]emaster(?:ed)?\s*\)*\s*[\)\]]?\s*$",
    r";\s+\d{4}\s+(?:Digitally\s+)?[Rr]emaster(?:ed)?\s*\)*\s*$",
    # "Version / Remastered" or "Version / Remaster" patterns
    r"Version\s*/\s*[Rr]emaster(?:ed)?\s*\)*\s*[\)\]]?\s*$",
    r"Version\s*/\s*[Rr]emaster(?:ed)?\s*\)*\s*$",
    # "Remastered / ..." patterns (remove from slash onwards)
    r"\s+[Rr]emastered\s*/.*$",
    r"\s+/[Rr]emastered\s*\)*\s*$",
    r"\s+/[Rr]emaster\s*\)*\s*$",
    # Collection versions
    r" -\s+(?:Platinum Collection Version|Platinum Collection)\s*$",
    r"\s+(?:Platinum Collection Version|Platinum Collection)\s*$",
    r"\s*[\(\[]\s*(?:Platinum Collection Version|Platinum Collection)\s*[\)\]]\s*$",
    # "24-Bit Digitally Remastered 02" - has number suffix
    r"\s*[\(\[]\s*\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s+\d+\s*[\)\]]\s*$",
    r" -\s+\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s+\d+\s*\)*\s*$",
    r" -\s+Digitally\s+Remastered\s+\d+;\s*\)*\s*$",
    r" -\s+Digitally\s+Remastered\s+\d+;\s*$",
    # "Live 2015 Remastered Version" pattern
    r" -\s+Live\s+\d{4}\s+Remastered\s+Version\s*\)*\s*$",
    r" -\s+Live\s+\d{4}\s+Remastered\s*\)*\s*$",
    # Missing closing parenthesis
    r"\s*[\(\[]\s*Remastered\s+(?:LP|CD)\s+Version\s*$",
    # Complex bracket patterns (e.g., "[Single Version - 2009 Remaster - Mono]")
    r"\s*[\(\[]\s*[\w\s]+\s+-\s+\d{4}\s+[Rr]emaster(?:ed)?\s*-\s*\w+\s*[\)\]]\s*$",
    r"\s+-\s+\d{4}\s+[Rr]emaster(?:ed)?\s*-\s*\w+\s*$",
    # Additional patterns for tricky cases
    # "Dub; 2005 Digital Remaster)" inside parentheses - simple pattern
    r"\s*\([^)]*;\s+\d{4}\s+Digital\s+Remaster\)\s*$",
    r"\s*\([^)]*;\s+\d{4}\s+Remaster\)\s*$",
    # "/ Remastered)" at end - simple pattern
    r"\s*/\s*Remastered\s*\)\s*$",
    # "24-Bit Digitally Remastered 02)" pattern - simple pattern
    r"\s*\(24-Bit\s+Digitally\s+Remastered\s+\d+\)\s*$",
    r"\s*\(\d{4}-Bit\s+Digitally\s+Remastered\s+\d+\)\s*$",
    # "Remastered / From" pattern - remove entire parenthesis content from "Remastered /" onwards
    r"\s*\(.*Remastered\s+/.*\)\s*$",
    r"\s*\(.*Remastered\s+/.*$",
]


def clean_remastered_suffix(title: str) -> str:
    """Remove artificial remastered/remaster and expanded edition suffixes from a title."""
    if not title:
        return title

    cleaned = title
    for pattern in _REMASTER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Fix unbalanced parentheses - if we have an opening ( but no closing ), remove it
    # This handles cases like "(Re-Version;2006 Remaster)" -> "(Re-Version" -> should be ""
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

    # Get all unique (artist, album, track) combinations
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
    """)
    rows = cur.fetchall()

    updated_count = 0

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]

        # Clean album and track names
        cleaned_album = clean_remastered_suffix(album)
        cleaned_track = clean_remastered_suffix(track)

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
        WHERE album LIKE '%Remaster%' OR album LIKE '%remaster%'
           OR album LIKE '%Remastered%' OR album LIKE '%remastered%'
           OR album LIKE '%Expanded Edition%' OR album LIKE '%expanded edition%'
           OR album LIKE '%Expanded Version%' OR album LIKE '%expanded version%'
           OR album LIKE '%(Expanded)%' OR album LIKE '%(expanded)%'
           OR album LIKE '%Stereo Mix%' OR album LIKE '%Mono Mix%'
           OR album LIKE '% - Remix%' OR album LIKE '%(Remix)%'
           OR album LIKE '% - Mix%' OR album LIKE '%(Mix)%'
           OR album LIKE '%Single Version%' OR album LIKE '%Album Version%'
           OR album LIKE '%Platinum Collection%' OR album LIKE '%platinum collection%'
    """)
    rows = cur.fetchall()

    updated_count = 0
    albums_to_delete = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]

        # Clean album name
        cleaned_album = clean_remastered_suffix(album)

        # Skip if no changes needed
        if cleaned_album == album:
            continue

        # Use INSERT OR REPLACE to handle cases where cleaned album already exists
        # This will merge data if (artist, cleaned_album) already exists
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
        WHERE track LIKE '%Remaster%' OR track LIKE '%remaster%'
           OR track LIKE '%Remastered%' OR track LIKE '%remastered%'
           OR track LIKE '%Expanded Edition%' OR track LIKE '%expanded edition%'
           OR track LIKE '%Expanded Version%' OR track LIKE '%expanded version%'
           OR track LIKE '%(Expanded)%' OR track LIKE '%(expanded)%'
           OR track LIKE '%Stereo Mix%' OR track LIKE '%Mono Mix%'
           OR track LIKE '% - Remix%' OR track LIKE '%(Remix)%'
           OR track LIKE '% - Mix%' OR track LIKE '%(Mix)%'
           OR track LIKE '%Single Version%' OR track LIKE '%Album Version%'
           OR album LIKE '%Remaster%' OR album LIKE '%remaster%'
           OR album LIKE '%Remastered%' OR album LIKE '%remastered%'
           OR album LIKE '%Expanded Edition%' OR album LIKE '%expanded edition%'
           OR album LIKE '%Expanded Version%' OR album LIKE '%expanded version%'
           OR album LIKE '%(Expanded)%' OR album LIKE '%(expanded)%'
           OR track LIKE '%Platinum Collection%' OR track LIKE '%platinum collection%'
           OR album LIKE '%Platinum Collection%' OR album LIKE '%platinum collection%'
    """)
    rows = cur.fetchall()

    updated_count = 0
    tracks_to_delete = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]
        track_number = row["track_number"]
        # Check if duration column exists (may not be in all rows)
        duration = row["duration"] if "duration" in row.keys() else None

        # Clean both track and album names
        cleaned_track = clean_remastered_suffix(track)
        cleaned_album = clean_remastered_suffix(album)

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
    print("Starting remaster cleanup...")
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
