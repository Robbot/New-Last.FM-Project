#!/usr/bin/env python3
"""
Batch assign compilation tracks to their original albums using a mapping file.
Create a CSV-like mapping file and apply it.
"""

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
MAPPINGS_FILE = BASE_DIR / "files" / "track_assignments.csv"


def export_unassigned(compilation_album: str):
    """Export unassigned tracks to a CSV file for editing."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT artist, track, COUNT(*) as count
        FROM scrobble
        WHERE album = ?
        GROUP BY artist, track
        ORDER BY count DESC
    """, (compilation_album,))

    tracks = cursor.fetchall()
    conn.close()

    with open(MAPPINGS_FILE, 'w', encoding='utf-8') as f:
        f.write("# Track assignments for compilation album\n")
        f.write("# Format: artist,track,target_album\n")
        f.write("# Leave target_album empty to skip (keep in compilation)\n")
        f.write("#\n")
        for t in tracks:
            f.write(f'{t["artist"]},{t["track"]},\n')

    print(f"Exported {len(tracks)} tracks to {MAPPINGS_FILE}")
    print("Edit the file and add target albums, then run with --import")


def import_assignments(compilation_album: str, dry_run: bool = True):
    """Import assignments from CSV file and apply them."""
    if not MAPPINGS_FILE.exists():
        print(f"Mappings file not found: {MAPPINGS_FILE}")
        print("Run with --export first to create it.")
        return

    assignments = []
    with open(MAPPINGS_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split(',', 2)
            if len(parts) == 3:
                artist, track, target_album = parts
                if target_album.strip():
                    assignments.append({
                        "artist": artist.strip(),
                        "track": track.strip(),
                        "target_album": target_album.strip()
                    })

    if not assignments:
        print("No assignments found in file.")
        return

    print(f"Found {len(assignments)} assignments to apply")

    if dry_run:
        print("\n[Dry run - use --execute to apply]")
        for a in assignments[:10]:
            print(f"  {a['artist']}: {a['track']} -> {a['target_album']}")
        if len(assignments) > 10:
            print(f"  ... and {len(assignments) - 10} more")
        return

    # Apply assignments
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    total_updated = 0
    failed = []

    for a in assignments:
        try:
            cursor.execute("""
                UPDATE scrobble
                SET album = ?
                WHERE artist = ? AND track = ? AND album = ?
            """, (a["target_album"], a["artist"], a["track"], compilation_album))

            updated = cursor.rowcount
            if updated > 0:
                total_updated += updated
                print(f"  ✓ {a['artist']}: {a['track']} -> {a['target_album']} ({updated} scrobbles)")
            else:
                failed.append(a)
        except Exception as e:
            print(f"  ✗ Error: {e}")
            failed.append(a)

    conn.commit()
    conn.close()

    print(f"\nUpdated {total_updated} scrobbles")
    if failed:
        print(f"Failed: {len(failed)}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage:")
        print("  python -m app.services.batch_assign_tracks \"Album Name\" --export")
        print("  python -m app.services.batch_assign_tracks \"Album Name\" --import")
        print("  python -m app.services.batch_assign_tracks \"Album Name\" --import --execute")
        sys.exit(1)

    compilation_album = sys.argv[1]

    if "--export" in sys.argv:
        export_unassigned(compilation_album)
    elif "--import" in sys.argv:
        dry_run = "--execute" not in sys.argv
        import_assignments(compilation_album, dry_run=dry_run)
    else:
        print("Please specify --export or --import")


if __name__ == "__main__":
    main()
