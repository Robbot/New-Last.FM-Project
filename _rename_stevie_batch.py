#!/usr/bin/env python3
"""One-off batch rename of 3 Stevie Wonder track variants on The Definitive Collection."""
from app.services.rename_and_map_track import rename_and_add_mapping

ARTIST = "Stevie Wonder"
ALBUM = "The Definitive Collection"

RENAMES = [
    # (from_name, to_name)
    ("Fingertips Pts. 1 & 2 - Live at the Regal Theater, Chicago/1962",
     "Fingertips, Pts. 1 & 2"),
    ("Fingertips, Part 2 - Live At The Regal Theater/1963/ Single Version",
     "Fingertips, Pts. 1 & 2"),
    ("He's Misstra Know-It-All",
     "He's Misstra Know It All"),
]

if __name__ == "__main__":
    for from_name, to_name in RENAMES:
        print("=" * 60)
        renamed, added = rename_and_add_mapping(ARTIST, ALBUM, from_name, to_name)
        print(f"  renamed={renamed}, mapping_added={added}")
