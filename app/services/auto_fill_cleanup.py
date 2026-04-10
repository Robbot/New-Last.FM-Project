#!/usr/bin/env python3
"""
Final cleanup for remaining 15 tracks with encoding issues and special cases.
"""

import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
MAPPINGS_FILE = BASE_DIR / "files" / "track_assignments.csv"

# Final cleanup mappings
CLEANUP_ALBUMS = {
    # These need exact artist/track matching due to encoding
    ("Die Ärzte", "Männer Sind Schweine"): "Die Ärzte",
    ("Enigma", "Sadeness (Part I)"): "MCMXC a.D.",
    ("Queen", "Flash"): "Flash Gordon",
    ("The Connells", "'74-'75"): "Ring",
    ("Ayman", "Du Bist Mein Stern"): "Alles Anders",
    ("Die Fantastischen Vier", "Sie Ist Weg"): "4 Gewinnt",
    ("Die Ärzte", "Ein Song Namens Schunder"): "Die Bestie in Menschengestalt",
    ("Die Ärzte", "Schrei Nach Liebe"): "Die Bestie in Menschengestalt",
    ("Herbert Grönemeyer", "Bleibt Alles Anders"): "Chaos",
    ("Herbert Grönemeyer", "Was Soll Das"): "So gut",
    ("Londonbeat", "I've Been Thinking About You"): "Londonbeat",
    ("Pras Michel", "Ghetto Supastar"): "Ghetto Supastar",
    ("Sinéad O'Connor", "Nothing Compares 2 U"): "I Do Not Want What I Haven't Got",
    ("Suzanne Vega", "Tom's Diner"): "Solitude Standing",
    ("Tom Jones", "Sexbomb"): "Reload",
}


def normalize_for_matching(text: str) -> str:
    """Simple normalization for matching."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text


def auto_fill_cleanup():
    """Final cleanup auto-fill."""
    if not MAPPINGS_FILE.exists():
        print(f"Error: {MAPPINGS_FILE} not found.")
        return

    filled = 0
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    output_lines = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            output_lines.append(line)
            continue

        parts = line.strip().split(',')
        if len(parts) < 3:
            output_lines.append(line)
            continue

        artist = parts[0].strip()
        track = parts[1].strip()
        target_album = parts[2].strip() if len(parts) > 2 else ""

        if target_album:
            output_lines.append(line)
            continue

        # Try exact match
        key = (artist, track)
        if key in CLEANUP_ALBUMS:
            output_lines.append(f"{artist},{track},{CLEANUP_ALBUMS[key]}\n")
            filled += 1
            print(f"✓ {artist}: {track} → {CLEANUP_ALBUMS[key]}")
            continue

        # Try fuzzy match (handle encoding variations)
        norm_track = normalize_for_matching(track)
        for (kb_artist, kb_track), album in CLEANUP_ALBUMS.items():
            # Normalize both for comparison
            norm_kb_artist = normalize_for_matching(kb_artist)
            norm_kb_track = normalize_for_matching(kb_track)

            if (normalize_for_matching(artist) == norm_kb_artist and
                norm_track == norm_kb_track):
                output_lines.append(f"{artist},{track},{album}\n")
                filled += 1
                print(f"~ {artist}: {track} → {album} (fuzzy)")
                break
        else:
            output_lines.append(line)

    # Write back
    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        f.writelines(output_lines)

    print(f"\nAuto-filled: {filled}")


if __name__ == "__main__":
    auto_fill_cleanup()
