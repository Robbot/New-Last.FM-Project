#!/usr/bin/env python3
"""
Interactive tool to research and assign compilation tracks to their original albums.
For tracks that couldn't be automatically reassigned, this helps find the correct album.
"""

import sqlite3
import sys
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def get_unassigned_tracks(compilation_album: str):
    """Get tracks that couldn't be automatically reassigned."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all unique tracks from the compilation
    cursor.execute("""
        SELECT artist, track, COUNT(*) as count
        FROM scrobble
        WHERE album = ?
        GROUP BY artist, track
        ORDER BY count DESC
    """, (compilation_album,))

    all_tracks = cursor.fetchall()

    unassigned = []
    for track in all_tracks:
        artist = track["artist"]
        track_name = track["track"]

        # Check if exact match exists in other albums
        cursor.execute("""
            SELECT COUNT(*) as cnt
            FROM scrobble
            WHERE artist = ? AND track = ? AND album != ?
        """, (artist, track_name, compilation_album))

        if cursor.fetchone()["cnt"] == 0:
            unassigned.append({
                "artist": artist,
                "track": track_name,
                "count": track["count"]
            })

    conn.close()
    return unassigned


def search_tracks_by_artist(artist: str, compilation_album: str):
    """Find all albums/tracks by this artist (excluding compilation)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT album, track, COUNT(*) as count
        FROM scrobble
        WHERE artist = ? AND album != ?
        GROUP BY album, track
        ORDER BY count DESC
        LIMIT 50
    """, (artist, compilation_album))

    results = cursor.fetchall()
    conn.close()

    # Group by album
    by_album = defaultdict(list)
    for r in results:
        by_album[r["album"]].append({"track": r["track"], "count": r["count"]})

    return dict(by_album)


def show_artist_catalog(artist: str, compilation_album: str, target_track: str):
    """Show all albums/tracks by artist to help identify the correct one."""
    print(f"\n{'=' * 60}")
    print(f"Artist: {artist}")
    print(f"Looking for: {target_track}")
    print(f"{'=' * 60}\n")

    catalog = search_tracks_by_artist(artist, compilation_album)

    if not catalog:
        print("No other albums found for this artist in the database.")
        print("You may need to add the original album first.")
        return None

    print("Albums in database (with track counts):")
    for i, (album, tracks) in enumerate(catalog.items(), 1):
        print(f"\n{i}. {album}")
        for t in tracks[:5]:
            print(f"   - {t['track']} ({t['count']} plays)")
        if len(tracks) > 5:
            print(f"   ... and {len(tracks) - 5} more tracks")

    return catalog


def interactive_assign(compilation_album: str):
    """Interactive session to assign unassigned tracks."""
    unassigned = get_unassigned_tracks(compilation_album)

    if not unassigned:
        print("All tracks have been assigned!")
        return

    print(f"\n=== Interactive Track Assignment ===")
    print(f"Unassigned tracks: {len(unassigned)}")
    print(f"Type 'skip' to skip a track, 'done' to finish\n")

    assignments = []
    skipped = []

    for i, track_info in enumerate(unassigned, 1):
        artist = track_info["artist"]
        track_name = track_info["track"]
        count = track_info["count"]

        print(f"\n[{i}/{len(unassigned)}] {artist}: {track_name} ({count} plays)")

        # Show catalog
        catalog = show_artist_catalog(artist, compilation_album, track_name)

        if not catalog:
            response = input(f"\nEnter target album (or 'skip'): ").strip()
        else:
            print(f"\nEnter album number, album name, or 'skip':")
            response = input("> ").strip()

        if response.lower() == 'skip':
            skipped.append(track_info)
            continue
        elif response.lower() == 'done':
            break
        elif response.isdigit() and catalog:
            album_num = int(response) - 1
            album_names = list(catalog.keys())
            if 0 <= album_num < len(album_names):
                target_album = album_names[album_num]
                assignments.append({
                    "artist": artist,
                    "track": track_name,
                    "target_album": target_album,
                    "count": count
                })
                print(f"  → Assigned to: {target_album}")
            else:
                print("  Invalid number, skipping.")
                skipped.append(track_info)
        elif response:
            # Use exact album name
            assignments.append({
                "artist": artist,
                "track": track_name,
                "target_album": response,
                "count": count
            })
            print(f"  → Assigned to: {response}")
        else:
            skipped.append(track_info)

    return assignments, skipped


def apply_assignments(compilation_album: str, assignments: list, dry_run: bool = True):
    """Apply the assignments to the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    summary = {"updated": 0, "failed": 0}

    for assignment in assignments:
        artist = assignment["artist"]
        track = assignment["track"]
        target_album = assignment["target_album"]

        try:
            if dry_run:
                summary["updated"] += assignment["count"]
            else:
                cursor.execute("""
                    UPDATE scrobble
                    SET album = ?
                    WHERE artist = ? AND track = ? AND album = ?
                """, (target_album, artist, track, compilation_album))

                updated = cursor.rowcount
                summary["updated"] += updated
                print(f"  Moved {updated} scrobbles: {track} → {target_album}")

        except Exception as e:
            print(f"  ERROR: {e}")
            summary["failed"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    return summary


def show_unassigned_summary(compilation_album: str):
    """Show summary of unassigned tracks grouped by reason."""
    unassigned = get_unassigned_tracks(compilation_album)

    # Group by potential reasons
    one_hit_wonders = []
    collaborations = []
    other = []

    for t in unassigned:
        # Check if it's a collaboration (contains &, feat., etc.)
        track = t["track"]
        artist = t["artist"]

        if "&" in artist or "feat" in artist.lower() or "featuring" in artist.lower():
            collaborations.append(t)
        elif t["count"] <= 5:
            one_hit_wonders.append(t)
        else:
            other.append(t)

    print(f"\n=== Unassigned Tracks Summary ===")
    print(f"Total unassigned: {len(unassigned)} ({sum(t['count'] for t in unassigned)} scrobbles)")
    print()

    if collaborations:
        print(f"Collaborations ({len(collaborations)} tracks):")
        for t in collaborations[:10]:
            print(f"  - {t['artist']}: {t['track']} ({t['count']} plays)")
        if len(collaborations) > 10:
            print(f"  ... and {len(collaborations) - 10} more")
        print()

    if one_hit_wonders:
        print(f"One-hit wonders / Rare tracks ({len(one_hit_wonders)} tracks):")
        for t in one_hit_wonders[:10]:
            print(f"  - {t['artist']}: {t['track']} ({t['count']} plays)")
        if len(one_hit_wonders) > 10:
            print(f"  ... and {len(one_hit_wonders) - 10} more")
        print()

    if other:
        print(f"Other ({len(other)} tracks):")
        for t in other[:10]:
            print(f"  - {t['artist']}: {t['track']} ({t['count']} plays)")
        if len(other) > 10:
            print(f"  ... and {len(other) - 10} more")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage:")
        print("  python -m app.services.assign_compilation_tracks \"Album Name\"")
        print("  python -m app.services.assign_compilation_tracks \"Album Name\" --summary")
        sys.exit(1)

    compilation_album = sys.argv[1]

    if "--summary" in sys.argv:
        show_unassigned_summary(compilation_album)
    else:
        print("Interactive track assignment mode")
        print("This will help you find the correct albums for unassigned tracks.\n")

        assignments, skipped = interactive_assign(compilation_album)

        print(f"\n{'=' * 60}")
        print(f"Session complete!")
        print(f"Assigned: {len(assignments)} tracks ({sum(a['count'] for a in assignments)} scrobbles)")
        print(f"Skipped: {len(skipped)} tracks ({sum(s['count'] for s in skipped)} scrobbles)")

        if assignments:
            print(f"\nTo apply these changes, run:")
            print(f"  python -m app.services.assign_compilation_tracks \"{compilation_album}\" --execute")


if __name__ == "__main__":
    main()
