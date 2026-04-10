#!/usr/bin/env python3
"""
Clean ALL edition suffixes from database.

This comprehensive script removes artificial edition suffixes including:
- Remaster/Remastered (with or without hyphens like "Re-Mastered")
- Deluxe Edition/Deluxe Version/Just "Deluxe"
- Special Edition
- Standard Edition
- Limited Edition
- Collector's Edition
- Legacy Edition
- Super Deluxe
- International versions
- Bonus track versions
- And more

Run this to clean historical data with ALL edition suffixes.
"""

import sqlite3
import re
import shutil
from pathlib import Path


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


# ---------- Regex patterns ----------
# COMPREHENSIVE edition suffix patterns - ORDER MATTERS (more specific first)
_EDITION_PATTERNS = [
    # ========== Year + Remaster patterns ==========
    # Re-Mastered/Re-Master (with hyphen) + year - MUST COME FIRST before regular Remastered
    r"\s*[\(\[]\s*\d{4}\s+(?:Re-?Mastered|Re-?Master|re-?mastered|re-?master)\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*(?:Re-?Mastered|Re-?Master|re-?mastered|re-?master)\s+\d{4}\s*[\)\]]\s*$",
    r" -\s+\d{4}\s+(?:Re-?Mastered|Re-?Master)\s*$",
    r" -\s+(?:Re-?Mastered|Re-?Master)(?:\s+\d{4})?\s*$",
    # Regular Remastered/Remaster with year
    r"\s*[\(\[]\s*\d{4}\s+-\s+(?:Remastered|Remaster|remastered|remaster)\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*[\)\]]\s*$",
    r" -\s+\d{4}\s+(?:Remastered|Remaster)\s+Version\s*$",
    r" -\s+\d{4}\s+(?:Remastered|Remaster)\s*$",
    r"\s+\d{4}\s+(?:Remastered|Remaster)\s*$",
    # Remastered/Remaster without year
    r" -\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    r"\s+(?:Remastered|Remaster|remastered|remaster)\s*$",
    r"\s*[\(\[]\s*(?:Remastered|Remaster|remastered|remaster)(?:\s+\d{4})?\s*[\)\]]\s*$",

    # ========== Digital Remaster patterns ==========
    r"\s+(?:\d{4}\s+)?(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*$",
    r"\s*[\(\[]\s*(?:\d{4}\s+)?(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*[\)\]]\s*$",
    r";\s*\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s+Version\s*$",
    r";\s*(?:Digitally\s+)?[Dd]igital\s+[Rr]emaster(?:ed)?\s*$",
    r";\s+\d{4}\s+(?:Remastered|Remaster|remastered|remaster)\s*$",

    # ========== Deluxe Edition patterns ==========
    r" -\s+(?:Deluxe\s+Edition|Deluxe\s+Version|Deluxe\s+Reissue|Deluxe)\s*$",
    r"\s+(?:Deluxe\s+Edition|Deluxe\s+Version|Deluxe\s+Reissue|Deluxe)\s*$",
    r"\s*[\(\[]\s*(?:Deluxe\s+Edition|Deluxe\s+Version|Deluxe\s+Reissue|deluxe\s+edition|deluxe\s+version|Deluxe)\s*[\)\]]\s*$",
    # Bracketed Deluxe at end
    r"\s*\[Deluxe\]\s*$",
    r"\s*\(Deluxe\)\s*$",

    # ========== Special Edition patterns ==========
    r" -\s+(?:Special\s+Edition|Special\s+Version|Special)\s*$",
    r"\s+(?:Special\s+Edition|Special\s+Version|Special)\s*$",
    r"\s*[\(\[]\s*(?:Special\s+Edition|Special\s+Version|special\s+edition|special\s+version|Special)\s*[\)\]]\s*$",

    # ========== Reissue patterns ==========
    r" -\s+(?:Reissue|Re-?Issue)\s*$",
    r"\s+(?:Reissue|Re-?Issue)\s*$",
    r"\s*[\(\[]\s*(?:Reissue|Re-?Issue)\s*[\)\]]\s*$",

    # ========== Anniversary Edition patterns ==========
    r" -\s+(?:\d+\s+Year\s+(?:Anniversary\s+(?:Edition|Version)?|Anniversary))\s*$",
    r"\s+(?:\d+\s+Year\s+(?:Anniversary\s+(?:Edition|Version)?|Anniversary))\s*$",
    r"\s*[\(\[]\s*(?:\d+\s+Year\s+(?:Anniversary\s+(?:Edition|Version)?|Anniversary))\s*[\)\]]\s*$",

    # ========== Bonus/Super patterns ==========
    r" -\s+(?:Super\s+Bonus\s+Edition|Super\s+Bonus|Bonus\s+Edition|Bonus)\s*$",
    r"\s+(?:Super\s+Bonus\s+Edition|Super\s+Bonus|Bonus\s+Edition|Bonus)\s*$",
    r"\s*[\(\[]\s*(?:Super\s+Bonus\s+Edition|Super\s+Bonus|Bonus\s+Edition|Bonus)\s*[\)\]]\s*$",

    # ========== Standard Edition patterns ==========
    r" -\s+(?:Standard\s+Edition|Standard\s+Version)\s*$",
    r"\s+(?:Standard\s+Edition|Standard\s+Version)\s*$",
    r"\s*[\(\[]\s*(?:Standard\s+Edition|Standard\s+Version|standard\s+edition|standard\s+version)\s*[\)\]]\s*$",

    # ========== Limited Edition patterns ==========
    r" -\s+(?:Limited\s+Edition|Limited\s+Version|Limited)\s*$",
    r"\s+(?:Limited\s+Edition|Limited\s+Version|Limited)\s*$",
    r"\s*[\(\[]\s*(?:Limited\s+Edition|Limited\s+Version|limited\s+edition|limited\s+version|Limited)\s*[\)\]]\s*$",

    # ========== Collector's Edition patterns ==========
    r" -\s+(?:Collector'?s?\s+Edition|Collector'?s?\s+Version)\s*$",
    r"\s+(?:Collector'?s?\s+Edition|Collector'?s?\s+Version)\s*$",
    r"\s*[\(\[]\s*(?:Collector'?s?\s+Edition|Collector'?s?\s+Version)\s*[\)\]]\s*$",

    # ========== Legacy Edition patterns ==========
    r" -\s+(?:Legacy\s+Edition|Legacy\s+Version)\s*$",
    r"\s+(?:Legacy\s+Edition|Legacy\s+Version)\s*$",
    r"\s*[\(\[]\s*(?:Legacy\s+Edition|Legacy\s+Version)\s*[\)\]]\s*$",

    # ========== Super Deluxe patterns ==========
    r" -\s+(?:Super\s+Deluxe|Super\s+Deluxe\s+Edition)\s*$",
    r"\s+(?:Super\s+Deluxe|Super\s+Deluxe\s+Edition)\s*$",
    r"\s*[\(\[]\s*(?:Super\s+Deluxe|Super\s+Deluxe\s+Edition)\s*[\)\]]\s*$",

    # ========== Expanded Edition patterns ==========
    r" -\s+(?:Expanded\s+Edition|Expanded\s+Version|Expanded)\s*$",
    r"\s+(?:Expanded\s+Edition|Expanded\s+Version|Expanded)\s*$",
    r"\s*[\(\[]\s*(?:Expanded\s+Edition|Expanded\s+Version|expanded\s+edition|expanded\s+version|Expanded)\s*[\)\]]\s*$",

    # ========== International Version patterns ==========
    r" -\s+(?:International\s+(?:Special\s+)?(?:Edition|Version))\s*$",
    r"\s+(?:International\s+(?:Special\s+)?(?:Edition|Version))\s*$",
    r"\s*[\(\[]\s*International\s+Special\s+Edition\s+Version\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*International\s+(?:Special\s+)?(?:Edition|Version)\s*[\)\]]\s*$",

    # ========== Platinum Collection patterns ==========
    r" -\s+(?:Platinum\s+Collection\s+Version|Platinum\s+Collection)\s*$",
    r"\s+(?:Platinum\s+Collection\s+Version|Platinum\s+Collection)\s*$",
    r"\s*[\(\[]\s*(?:Platinum\s+Collection\s+Version|Platinum\s+Collection)\s*[\)\]]\s*$",

    # ========== Bonus/Extra tracks patterns ==========
    r" -\s+(?:Bonus\s+(?:Track)?\s*Version|Bonus\s+(?:Track)?\s*Edition)\s*$",
    r"\s+(?:Bonus\s+(?:Track)?\s*Version|Bonus\s+(?:Track)?\s*Edition)\s*$",
    r"\s*[\(\[]\s*(?:Bonus\s+(?:Track)?\s*(?:Version|Edition))\s*[\)\]]\s*$",

    # ========== Original Soundtrack patterns ==========
    r"\s*[\(\[]\s*(?:The\s+)?Original\s+(?:Motion\s+Picture\s+)?Soundtrack\s*[\)\]]\s*$",

    # ========== Version patterns ==========
    r" -\s+(?:Single\s+Version|Album\s+Version|Remix|Mix)\s*$",
    r"\s*[\(\[]\s*(?:Single\s+Version|Album\s+Version|Remix|Mix)\s*[\)\]]\s*$",

    # ========== Mix/Remix patterns ==========
    r" -\s+\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*$",
    r"\s+[\(\[]\s*\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*[\)\]]\s*$",
    r"\s+\d{4}\s+(?:Stereo\s+Mix|Mono\s+Mix|Remix|Mix|Version)\s*$",

    # ========== Slash separator patterns ==========
    r"\s*/\s*(?:Remastered|Remaster|Deluxe|Special|Standard|Limited)\s*\)*\s*$",
    r"Version\s*/\s*[Rr]emaster(?:ed)?\s*\)*\s*[\)\]]?\s*$",
    r"\s+[Rr]emastered\s*/.*$",
    r"\s+/[Rr]emastered\s*\)*\s*$",
    r"\s+/[Rr]emaster\s*\)*\s*$",

    # ========== Complex bracket patterns ==========
    r"\s*\(.*Remastered\s+/.*\)\s*$",
    r"\s*\(.*Remastered\s+/.*$",
    r"\s*\([^)]*;\s+\d{4}\s+Digital\s+Remaster\)\s*$",
    r"\s*\([^)]*;\s+\d{4}\s+Remaster\)\s*$",
    r"\s*\(24-Bit\s+Digitally\s+Remastered\s+\d+\)\s*$",
    r"\s*\(\d{4}-Bit\s+Digitally\s+Remastered\s+\d+\)\s*$",
    r"\s*\([^)]*;\s+\d{4}\s+(?:Digitally\s+)?Remaster(?:ed)?\)\s*$",

    # ========== 24-Bit patterns ==========
    r"\s*[\(\[]\s*\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s+\d+\s*[\)\]]?\s*$",
    r"\s*[\(\[]\s*\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s*[\)\]]?\s*$",
    r" -\s+\d{4}-Bit\s+[Dd]igitally\s+[Rr]emaster(?:ed)?\s+\d+\s*\)*\s*$",

    # ========== Live remaster patterns ==========
    r" -\s+Live\s+\d{4}\s+Remastered\s+Version\s*\)*\s*$",
    r" -\s+Live\s+\d{4}\s+Remastered\s*\)*\s*$",

    # ========== Bracket patterns with dash ==========
    r"\s*[\(\[]\s*[\w\s]+\s+-\s+\d{4}\s+[Rr]emaster(?:ed)?\s*-\s*\w+\s*[\)\]]\s*$",
    r"\s+-\s+\d{4}\s+[Rr]emaster(?:ed)?\s*-\s*\w+\s*$",

    # ========== Catch-all edition patterns ==========
    r"\s*[\(\[]\s*(?:\w+\s+)?Edition\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*(?:\w+\s+)?Version\s*[\)\]]\s*$",
    r"\s*[\(\[]\s*(?:Re-?)?(?:Master|Mastered)\s*[\)\]]\s*$",
]


def clean_edition_suffix(title: str) -> str:
    """Remove ALL artificial edition suffixes from a title."""
    if not title:
        return title

    cleaned = title
    for pattern in _EDITION_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Fix unbalanced parentheses - if we have an opening ( but no closing ), remove it
    cleaned = re.sub(r'\s*\(\s*[^)]*$', "", cleaned.strip())

    # Also handle unbalanced brackets
    cleaned = re.sub(r'\s*\[[^\]]*$', "", cleaned.strip())

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

    # Get all unique (artist, album, track) combinations that might have edition suffixes
    cur.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE album LIKE '%(%'
           OR album LIKE '%[%'
           OR album LIKE '% - %'
           OR track LIKE '%(%'
           OR track LIKE '%[%'
           OR track LIKE '% - %'
    """)
    rows = cur.fetchall()

    updated_count = 0

    for row in rows:
        artist = row["artist"]
        album = row["album"]
        track = row["track"]

        # Clean album and track names
        cleaned_album = clean_edition_suffix(album)
        cleaned_track = clean_edition_suffix(track)

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

    # Get all rows that might need cleaning
    cur.execute("""
        SELECT * FROM album_art
        WHERE album LIKE '%(%'
           OR album LIKE '%[%'
           OR album LIKE '% - %'
    """)
    rows = cur.fetchall()

    updated_count = 0
    albums_to_delete = []

    for row in rows:
        artist = row["artist"]
        album = row["album"]

        # Clean album name
        cleaned_album = clean_edition_suffix(album)

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

    # Get all rows that might need cleaning
    cur.execute("""
        SELECT * FROM album_tracks
        WHERE track LIKE '%(%'
           OR track LIKE '%[%'
           OR track LIKE '% - %'
           OR album LIKE '%(%'
           OR album LIKE '%[%'
           OR album LIKE '% - %'
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
        cleaned_track = clean_edition_suffix(track)
        cleaned_album = clean_edition_suffix(album)

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
    print("Starting ALL EDITION cleanup...")
    print(f"Database: {DB_PATH}")

    if not DB_PATH.exists():
        print(f"ERROR: Database file not found at {DB_PATH}")
        return

    # Show preview of what will be cleaned
    print("\n--- Preview of albums to be cleaned (first 30) ---")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT album, artist FROM scrobble
        WHERE album LIKE '%(%'
           OR album LIKE '%[%'
           OR album LIKE '% - %'
        ORDER BY album
        LIMIT 30
    """)
    preview_rows = cur.fetchall()
    if preview_rows:
        for row in preview_rows:
            cleaned = clean_edition_suffix(row['album'])
            if cleaned != row['album']:
                print(f"  - {row['artist']}: '{row['album']}' -> '{cleaned}'")
    else:
        print("  No edition suffixes found in database.")

    conn.close()

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
