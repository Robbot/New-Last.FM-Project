#!/usr/bin/env python3
"""
Auto-detect and add Spotify track name mappings by comparing album_tracks (standard)
against scrobble table (may have Spotify variants).

This script finds tracks where the scrobble name differs from album_tracks
and automatically adds them to spotify_track_mappings.json.

Usage:
    # Dry run (show what would be added)
    python -m app.services.auto_add_spotify_mappings --dry-run

    # Auto-add all found mappings
    python -m app.services.auto_add_spotify_mappings

    # Interactive mode (ask for each mapping)
    python -m app.services.auto_add_spotify_mappings --interactive
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
MAPPINGS_FILE = BASE_DIR / "app" / "services" / "spotify_track_mappings.json"


def load_mappings():
    """Load existing mappings."""
    if MAPPINGS_FILE.exists():
        with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"mappings": [], "last_updated": ""}


def save_mappings(data):
    """Save mappings to JSON file."""
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def mapping_exists(data, artist, album, from_name):
    """Check if a mapping already exists."""
    for m in data["mappings"]:
        if (m.get("artist") == artist and
            m.get("album") == album and
            m.get("from") == from_name):
            return True
    return False


def find_discrepancies():
    """Find tracks where scrobble name differs from album_tracks (standard)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find all tracks that exist in both tables but have different names
    query = """
        SELECT DISTINCT
            s.artist,
            s.album,
            s.track as scrobble_track,
            at.track as standard_track
        FROM scrobble s
        INNER JOIN album_tracks at ON s.artist = at.artist AND s.album = at.album
        WHERE s.track != at.track
        ORDER BY s.artist, s.album, s.track
    """

    cursor.execute(query)
    discrepancies = cursor.fetchall()
    conn.close()

    return discrepancies


def main():
    parser = argparse.ArgumentParser(description="Auto-detect Spotify track name mappings")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be added without making changes")
    parser.add_argument("--interactive", "-i", action="store_true", help="Ask before adding each mapping")
    args = parser.parse_args()

    discrepancies = find_discrepancies()
    data = load_mappings()
    existing_count = len(data["mappings"])

    if not discrepancies:
        print("No discrepancies found between scrobble and album_tracks tables.")
        return

    print(f"Found {len(discrepancies)} discrepancies:\n")

    added = []
    for d in discrepancies:
        artist = d["artist"]
        album = d["album"]
        scrobble_track = d["scrobble_track"]
        standard_track = d["standard_track"]

        # Skip if mapping already exists
        if mapping_exists(data, artist, album, scrobble_track):
            print(f"⊘ Skipping (already exists): {artist} - {album}")
            print(f"   '{scrobble_track}' -> '{standard_track}'\n")
            continue

        print(f"Found: {artist} - {album}")
        print(f"  Scrobble: '{scrobble_track}'")
        print(f"  Standard: '{standard_track}'")

        should_add = True
        if args.interactive:
            response = input("  Add this mapping? [Y/n]: ").strip().lower()
            if response == 'n':
                should_add = False
                print("  Skipped.\n")

        if should_add and not args.dry_run:
            new_mapping = {
                "artist": artist,
                "album": album,
                "from": scrobble_track,
                "to": standard_track
            }
            data["mappings"].append(new_mapping)
            added.append(new_mapping)
            print("  Added.\n")
        elif args.dry_run:
            print("  [DRY RUN - would add]\n")
        else:
            print("  Skipped.\n")

    if added:
        save_mappings(data)
        print(f"Added {len(added)} new mappings to spotify_track_mappings.json")
        print(f"Total mappings: {existing_count} -> {len(data['mappings'])}")
    elif args.dry_run:
        print(f"\nDry run complete. Would add {len([d for d in discrepancies if not mapping_exists(data, d['artist'], d['album'], d['scrobble_track'])])} new mappings.")
    else:
        print("No new mappings added.")


if __name__ == "__main__":
    main()
