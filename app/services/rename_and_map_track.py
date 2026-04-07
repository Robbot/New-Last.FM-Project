#!/usr/bin/env python3
"""
Rename scrobbles in database AND add to Spotify mappings simultaneously.

This tool ensures that manual track renames are always added to the mappings
so they will be applied automatically during future syncs.

Usage:
    # Interactive mode
    python -m app.services.rename_and_map_track

    # Command line - renames all matching scrobbles AND adds mapping
    python -m app.services.rename_and_map_track "Artist" "Album" "Current Name" "Correct Name"
"""

import sqlite3
import json
import sys
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


def rename_and_add_mapping(artist, album, from_name, to_name, dry_run=False):
    """
    Rename scrobbles in database AND add to Spotify mappings.

    Returns:
        tuple: (scrobbles_renamed, mapping_added)
    """
    data = load_mappings()
    scrobbles_renamed = 0
    mapping_added = False

    # Step 1: Check/update mapping
    mapping_idx = None
    for i, m in enumerate(data["mappings"]):
        if (m.get("artist") == artist and
            m.get("album") == album and
            m.get("from") == from_name):
            mapping_idx = i
            break

    if mapping_idx is not None:
        # Update existing mapping
        if data["mappings"][mapping_idx]["to"] != to_name:
            print(f"Updating existing mapping: '{from_name}' -> '{to_name}'")
            data["mappings"][mapping_idx]["to"] = to_name
            mapping_added = True
        else:
            print(f"Mapping already exists: '{from_name}' -> '{to_name}'")
    else:
        # Add new mapping
        new_mapping = {
            "artist": artist,
            "album": album,
            "from": from_name,
            "to": to_name
        }
        data["mappings"].append(new_mapping)
        mapping_added = True
        print(f"Added new mapping: '{from_name}' -> '{to_name}'")

    if mapping_added and not dry_run:
        save_mappings(data)

    # Step 2: Rename scrobbles in database
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Count affected rows
    cursor.execute("""
        SELECT COUNT(*) FROM scrobble
        WHERE artist = ? AND album = ? AND track = ?
    """, (artist, album, from_name))
    count = cursor.fetchone()[0]

    if count > 0:
        if not dry_run:
            cursor.execute("""
                UPDATE scrobble
                SET track = ?
                WHERE artist = ? AND album = ? AND track = ?
            """, (to_name, artist, album, from_name))
            conn.commit()
            scrobbles_renamed = cursor.rowcount
        else:
            scrobbles_renamed = count
            print(f"[DRY RUN] Would rename {count} scrobble(s)")
    else:
        print(f"No scrobbles found matching '{from_name}'")

    conn.close()

    return scrobbles_renamed, mapping_added


def list_scrobble_variations(artist, album):
    """List all track name variations for a given artist/album."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT track, COUNT(*) as count
        FROM scrobble
        WHERE artist = ? AND album = ?
        GROUP BY track
        ORDER BY track
    """, (artist, album))

    variations = cursor.fetchall()
    conn.close()

    return variations


def main():
    if len(sys.argv) == 5:
        # Command line mode
        artist = sys.argv[1]
        album = sys.argv[2]
        from_name = sys.argv[3]
        to_name = sys.argv[4]

        print(f"Processing: {artist} - {album}")
        print(f"  '{from_name}' -> '{to_name}'")
        print()

        renamed, added = rename_and_add_mapping(artist, album, from_name, to_name)

        if renamed > 0:
            print(f"\n✓ Renamed {renamed} scrobble(s) in database")
        if added:
            print(f"✓ Updated spotify_track_mappings.json")

    elif len(sys.argv) == 1:
        # Interactive mode
        print("Track Rename & Mapping Tool")
        print("=" * 50)
        print("\nThis tool helps you:")
        print("  1. Rename scrobbles in the database")
        print("  2. Add the rename to Spotify mappings")
        print("  3. Future syncs will automatically apply this mapping\n")

        while True:
            print("\nOptions:")
            print("1. Rename & map a track")
            print("2. List variations for an album")
            print("3. List current mappings")
            print("4. Exit")
            choice = input("\nChoose option (1-4): ").strip()

            if choice == "1":
                artist = input("Artist: ").strip()
                album = input("Album: ").strip()

                # Show variations to help user
                print("\nCurrent variations in database:")
                variations = list_scrobble_variations(artist, album)
                for i, v in enumerate(variations, 1):
                    print(f"  {i}. '{v['track']}' ({v['count']} scrobbles)")

                from_name = input("\nCurrent/Wrong name: ").strip()
                to_name = input("Correct/Standard name: ").strip()

                if artist and album and from_name and to_name:
                    renamed, added = rename_and_add_mapping(artist, album, from_name, to_name)
                    if renamed > 0:
                        print(f"\n✓ Renamed {renamed} scrobble(s)")
                    if added:
                        print(f"✓ Updated mappings")
                else:
                    print("Error: All fields are required.")

            elif choice == "2":
                artist = input("Artist: ").strip()
                album = input("Album: ").strip()
                variations = list_scrobble_variations(artist, album)
                if variations:
                    print(f"\nTrack variations for {artist} - {album}:")
                    for i, v in enumerate(variations, 1):
                        print(f"  {i}. '{v['track']}' ({v['count']} scrobbles)")
                else:
                    print(f"No scrobbles found for {artist} - {album}")

            elif choice == "3":
                data = load_mappings()
                if data["mappings"]:
                    print(f"\nCurrent mappings ({len(data['mappings'])} total):")
                    for i, m in enumerate(data["mappings"], 1):
                        print(f"  {i}. {m['artist']} - {m['album']}")
                        print(f"     '{m['from']}' -> '{m['to']}'")
                else:
                    print("\nNo mappings defined.")

            elif choice == "4":
                print("Goodbye!")
                break

            else:
                print("Invalid option. Please choose 1-4.")
    else:
        print(__doc__)
        print("\nExample:")
        print('  python -m app.services.rename_and_map_track "Wolfsheim" "55578" "A Look into Your Heart" "A Look Into Your Heart (Different Version)"')


if __name__ == "__main__":
    main()
