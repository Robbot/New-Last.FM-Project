#!/usr/bin/env python3
"""
Clean track name case inconsistencies from database.

This is a one-time migration script to normalize track names that have
inconsistent capitalization (e.g., "Of Wolf and Man" vs "Of Wolf And Man").
These variations cause the track gaps feature to treat them as separate tracks.

The script normalizes each track group to use the most common variant.
"""

import sqlite3
from pathlib import Path
from collections import Counter


# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def find_case_variants(conn: sqlite3.Connection):
    """
    Find all tracks with case variations.
    Returns a dict mapping (track_lower, artist, album) -> list of (track, play_count, last_play_uts)
    """
    cur = conn.cursor()

    # Get all distinct track variants with their play counts and last play time
    cur.execute("""
        SELECT
            track,
            artist,
            album,
            COUNT(*) as play_count,
            MAX(uts) as last_play_uts
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        GROUP BY track, artist, album
        ORDER BY track, artist, album
    """)
    rows = cur.fetchall()

    # Group by lowercase track name (within artist/album)
    variants = {}
    for row in rows:
        track = row["track"]
        artist = row["artist"]
        album = row["album"]
        key = (track.lower(), artist, album)

        if key not in variants:
            variants[key] = []
        variants[key].append({
            "track": track,
            "play_count": row["play_count"],
            "last_play_uts": row["last_play_uts"],
        })

    # Filter to only groups with multiple variants
    multi_variants = {k: v for k, v in variants.items() if len(v) > 1}
    return multi_variants


def choose_canonical_variant(variants: list) -> str:
    """
    Choose the canonical track name from a list of variants.
    Strategy: prefer the variant with the most plays.
    Tiebreaker: most recent play.
    Final tiebreaker: longer name (likely more "proper" capitalization).
    """
    # Sort by play count (desc), then last play (desc), then length (desc)
    sorted_variants = sorted(
        variants,
        key=lambda v: (v["play_count"], v["last_play_uts"], len(v["track"])),
        reverse=True
    )
    return sorted_variants[0]["track"]


def clean_scrobble_table(conn: sqlite3.Connection) -> int:
    """
    Clean track names in the scrobble table by normalizing case.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Find all case variants
    variants_map = find_case_variants(conn)

    if not variants_map:
        print("  No case inconsistencies found in scrobble table")
        return 0

    print(f"  Found {len(variants_map)} track groups with case variations")

    updated_count = 0

    for key, variants in variants_map.items():
        track_lower, artist, album = key

        # Choose the canonical variant
        canonical_track = choose_canonical_variant(variants)
        canonical_lower = canonical_track.lower()

        # Sanity check: all should have the same lowercase
        for v in variants:
            assert v["track"].lower() == canonical_lower, f"Mismatch: {v['track'].lower()} != {canonical_lower}"

        # Print what we're doing
        variant_names = [v["track"] for v in variants]
        print(f"  [{artist}] '{album}': {variant_names} -> '{canonical_track}'")

        # Update all non-canonical variants
        for v in variants:
            if v["track"] != canonical_track:
                old_track = v["track"]
                cur.execute("""
                    UPDATE scrobble
                    SET track = ?
                    WHERE artist = ? AND album = ? AND track = ?
                """, (canonical_track, artist, album, old_track))

                changes = cur.rowcount
                if changes > 0:
                    updated_count += changes

    conn.commit()
    return updated_count


def clean_album_tracks_table(conn: sqlite3.Connection) -> int:
    """
    Clean track names in the album_tracks table by normalizing case.
    Returns the number of rows updated.
    """
    cur = conn.cursor()

    # Find all case variants in album_tracks
    cur.execute("""
        SELECT
            track,
            artist,
            album,
            COUNT(*) as variant_count
        FROM album_tracks
        WHERE track IS NOT NULL AND track != ''
        GROUP BY track, artist, album
        ORDER BY track, artist, album
    """)
    rows = cur.fetchall()

    # Group by lowercase track name (within artist/album)
    variants = {}
    for row in rows:
        track = row["track"]
        artist = row["artist"]
        album = row["album"]
        key = (track.lower(), artist, album)

        if key not in variants:
            variants[key] = []
        variants[key].append(track)

    # Filter to only groups with multiple variants
    multi_variants = {k: v for k, v in variants.items() if len(v) > 1}

    if not multi_variants:
        print("  No case inconsistencies found in album_tracks table")
        return 0

    print(f"  Found {len(multi_variants)} track groups with case variations")

    updated_count = 0

    for key, variant_tracks in multi_variants.items():
        track_lower, artist, album = key

        # Choose canonical: use the one that matches scrobble table (most common)
        # Or just pick the first one with "proper" capitalization (first letter of each word capitalized)
        canonical_track = variant_tracks[0]  # Default to first
        for v in variant_tracks:
            # Prefer the version that looks more "title case"
            if v[0].isupper() and v == v.title():
                canonical_track = v
                break

        # Print what we're doing
        print(f"  [{artist}] '{album}': {variant_tracks} -> '{canonical_track}'")

        # Delete all non-canonical variants (to avoid UNIQUE constraint violations)
        # We delete them first, then update remaining if needed
        for old_track in variant_tracks:
            if old_track != canonical_track:
                cur.execute("""
                    DELETE FROM album_tracks
                    WHERE artist = ? AND album = ? AND track = ?
                """, (artist, album, old_track))

                changes = cur.rowcount
                if changes > 0:
                    updated_count += changes

    conn.commit()
    return updated_count


def main():
    print("Starting track case normalization cleanup...")
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

        # Clean album_tracks table
        print("\n--- Cleaning album_tracks table ---")
        album_tracks_updated = clean_album_tracks_table(conn)
        print(f"Album tracks table: {album_tracks_updated} rows updated")

        total_updated = scrobble_updated + album_tracks_updated
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
