#!/usr/bin/env python3
"""
Add or update Spotify track name mappings.

This script helps maintain the spotify_track_mappings.json file by providing
an easy way to add new mappings for Spotify-specific track name variations.

Usage:
    # Interactive mode
    python -m app.services.add_spotify_mapping

    # Command line arguments
    python -m app.services.add_spotify_mapping "Artist" "Album" "Wrong Name" "Correct Name"
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "app" / "services" / "spotify_track_mappings.json"


def load_mappings():
    """Load existing mappings from JSON file."""
    if MAPPINGS_FILE.exists():
        with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"mappings": [], "last_updated": ""}


def save_mappings(data):
    """Save mappings to JSON file."""
    from datetime import datetime
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_mapping(artist, album, from_name, to_name):
    """Add or update a mapping."""
    data = load_mappings()

    # Check if this exact mapping already exists
    for i, m in enumerate(data["mappings"]):
        if (m.get("artist") == artist and
            m.get("album") == album and
            m.get("from") == from_name):
            # Update existing mapping
            data["mappings"][i]["to"] = to_name
            print(f"Updated existing mapping: {artist} - {album}")
            print(f"  '{from_name}' -> '{to_name}'")
            save_mappings(data)
            return

    # Add new mapping
    new_mapping = {
        "artist": artist,
        "album": album,
        "from": from_name,
        "to": to_name
    }
    data["mappings"].append(new_mapping)
    print(f"Added new mapping: {artist} - {album}")
    print(f"  '{from_name}' -> '{to_name}'")
    save_mappings(data)


def list_mappings():
    """List all current mappings."""
    data = load_mappings()
    if not data["mappings"]:
        print("No mappings defined.")
        return

    print(f"Current mappings ({len(data['mappings'])} total):")
    print(f"Last updated: {data.get('last_updated', 'Unknown')}\n")

    for i, m in enumerate(data["mappings"], 1):
        print(f"{i}. {m['artist']} - {m['album']}")
        print(f"   '{m['from']}' -> '{m['to']}'")


def main():
    if len(sys.argv) == 5:
        # Command line mode: artist album from_name to_name
        artist = sys.argv[1]
        album = sys.argv[2]
        from_name = sys.argv[3]
        to_name = sys.argv[4]
        add_mapping(artist, album, from_name, to_name)
    elif len(sys.argv) == 2 and sys.argv[1] in ["--list", "-l"]:
        # List mappings
        list_mappings()
    elif len(sys.argv) == 1:
        # Interactive mode
        print("Spotify Track Mapping Editor")
        print("=" * 40)
        print()

        while True:
            print("\nOptions:")
            print("1. Add new mapping")
            print("2. List all mappings")
            print("3. Exit")
            choice = input("\nChoose option (1-3): ").strip()

            if choice == "1":
                artist = input("Artist: ").strip()
                album = input("Album: ").strip()
                from_name = input("Current/Wrong name: ").strip()
                to_name = input("Correct/Standard name: ").strip()

                if artist and album and from_name and to_name:
                    add_mapping(artist, album, from_name, to_name)
                else:
                    print("Error: All fields are required.")

            elif choice == "2":
                list_mappings()

            elif choice == "3":
                print("Goodbye!")
                break

            else:
                print("Invalid option. Please choose 1-3.")
    else:
        print(__doc__)
        print("\nExamples:")
        print('  python -m app.services.add_spotify_mapping "Wolfsheim" "55578" "A Look into Your Heart" "A Look Into Your Heart (Different Version)"')
        print('  python -m app.services.add_spotify_mapping --list')


if __name__ == "__main__":
    main()
