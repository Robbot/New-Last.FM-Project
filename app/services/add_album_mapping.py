#!/usr/bin/env python3
"""
Add or update album name mappings.

This script helps maintain the album_name_mappings.json file by providing
an easy way to add new mappings for incorrect album names from Last.fm/Spotify.

Usage:
    # Interactive mode
    python -m app.services.add_album_mapping

    # Command line arguments
    python -m app.services.add_album_mapping "Artist" "Wrong Album Name" "Correct Album Name"
"""

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "app" / "services" / "album_name_mappings.json"


def load_mappings():
    """Load existing mappings from JSON file."""
    if MAPPINGS_FILE.exists():
        with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"mappings": [], "last_updated": "", "notes": ""}


def save_mappings(data):
    """Save mappings to JSON file."""
    from datetime import datetime
    data["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_mapping(artist, from_name, to_name, reason=""):
    """Add or update an album name mapping."""
    data = load_mappings()

    # Check if this exact mapping already exists
    for i, m in enumerate(data["mappings"]):
        if (m.get("artist") == artist and
            m.get("from") == from_name):
            # Update existing mapping
            data["mappings"][i]["to"] = to_name
            if reason:
                data["mappings"][i]["reason"] = reason
            print(f"✓ Updated existing mapping: {artist} - '{from_name}' -> '{to_name}'")
            save_mappings(data)
            return True

    # Add new mapping
    new_mapping = {
        "artist": artist,
        "from": from_name,
        "to": to_name,
        "reason": reason or "Manual correction"
    }
    data["mappings"].append(new_mapping)
    print(f"✓ Added new mapping: {artist} - '{from_name}' -> '{to_name}'")
    save_mappings(data)
    return True


def list_mappings():
    """List all existing mappings."""
    data = load_mappings()
    mappings = data.get("mappings", [])

    if not mappings:
        print("No album name mappings found.")
        return

    print(f"\nFound {len(mappings)} album name mappings:\n")
    for i, m in enumerate(mappings, 1):
        reason = f" ({m.get('reason', '')})" if m.get('reason') else ""
        from_name = m['from']; to_name = m['to']; reason = f" ({m.get('reason', '')})" if m.get('reason') else ""; print(f"{i}. {m['artist']}: '{from_name}' -> '{to_name}'{reason}")

    print(f"\nLast updated: {data.get('last_updated', 'Unknown')}")


def interactive_mode():
    """Run in interactive mode."""
    print("Album Name Mapping - Interactive Mode")
    print("=" * 40)

    # Show existing mappings first
    list_mappings()

    print("\nOptions:")
    print("  1. Add new mapping")
    print("  2. Exit")

    choice = input("\nEnter choice (1-2): ").strip()

    if choice == "1":
        artist = input("Artist name: ").strip()
        from_name = input("Incorrect album name (as it appears from Last.fm/Spotify): ").strip()
        to_name = input("Correct album name: ").strip()
        reason = input("Reason (optional, press Enter to skip): ").strip()

        if artist and from_name and to_name:
            add_mapping(artist, from_name, to_name, reason)
            print("\n✓ Mapping saved successfully!")
        else:
            print("Error: Artist, 'from' name, and 'to' name are required.")
    else:
        print("Exiting.")


if __name__ == "__main__":
    if len(sys.argv) == 5:
        # Command line mode: python -m app.services.add_album_mapping "Artist" "From" "To" "Reason"
        artist, from_name, to_name = sys.argv[1], sys.argv[2], sys.argv[3]
        reason = sys.argv[4] if len(sys.argv) > 4 else ""
        add_mapping(artist, from_name, to_name, reason)
    elif len(sys.argv) == 4:
        # Command line mode without reason
        artist, from_name, to_name = sys.argv[1], sys.argv[2], sys.argv[3]
        add_mapping(artist, from_name, to_name)
    elif len(sys.argv) == 2 and sys.argv[1] in ["-l", "--list"]:
        # List mappings
        list_mappings()
    else:
        # Interactive mode
        interactive_mode()
