#!/usr/bin/env python3
"""
Fix compilation tracks that incorrectly have "Various Artists" as the track artist.

For compilations, the album_artist should be "Various Artists" but each track
should have its actual artist (Linkin Park, Marilyn Manson, etc.).

This script:
1. Finds compilations where album_tracks has "Various Artists" as the track artist
2. Deletes those entries so they can be re-fetched from MusicBrainz with correct artists
3. Or fixes them by querying scrobbles for the actual artist names

Usage:
    python -m app.services.fix_compilation_tracks --dry-run    # Preview changes
    python -m app.services.fix_compilation_tracks              # Apply fixes
    python -m app.services.fix_compilation_tracks --album "Album Name"  # Fix specific album
"""

import sqlite3
import argparse
from pathlib import Path
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.fetch_tracklist_musicbrainz import fetch_album_tracklist_by_mbid
from app.db.albums import upsert_album_tracks
from app.logging_config import get_logger

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


def get_compilations_with_various_artists_tracks():
    """Find compilations where tracks have 'Various Artists' as the artist."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find compilations with track artist = 'Various Artists'
    cursor.execute("""
        SELECT DISTINCT at.album, at.album_mbid, COUNT(*) as track_count
        FROM album_tracks at
        INNER JOIN (
            SELECT DISTINCT album
            FROM scrobble
            WHERE album_artist = 'Various Artists'
        ) s ON at.album = s.album
        WHERE at.artist = 'Various Artists'
          AND (at.album_mbid IS NULL OR at.album_mbid = '')
        GROUP BY at.album, at.album_mbid
        ORDER BY at.album
    """)

    results = cursor.fetchall()
    conn.close()

    return results


def fix_album_by_scrobble_data(album_name: str, dry_run: bool = False):
    """Fix album_tracks by using artist names from scrobbles."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Delete all entries where artist = 'Various Artists' (they're duplicates/incorrect)
    # Keep only entries with actual artist names
    cursor.execute("""
        SELECT COUNT(*) as count
        FROM album_tracks
        WHERE album = ? AND artist = 'Various Artists'
    """, (album_name,))

    count_row = cursor.fetchone()
    delete_count = count_row["count"] if count_row else 0

    if delete_count > 0:
        if not dry_run:
            cursor.execute("""
                DELETE FROM album_tracks
                WHERE album = ? AND artist = 'Various Artists'
            """, (album_name,))
            print(f"  Deleted {delete_count} 'Various Artists' entries")
        else:
            print(f"  Would delete {delete_count} 'Various Artists' entries (dry run)")

    # Now deduplicate remaining entries (keep first occurrence of each track_number)
    cursor.execute("""
        SELECT track_number, track, COUNT(*) as count
        FROM album_tracks
        WHERE album = ?
        GROUP BY track_number, track
        HAVING count > 1
    """, (album_name,))

    duplicates = cursor.fetchall()
    fixed_count = delete_count

    for dup in duplicates:
        track_number = dup["track_number"]
        track = dup["track"]
        dup_count = dup["count"]

        # Keep the first entry (lowest rowid), delete the rest
        if not dry_run:
            cursor.execute("""
                DELETE FROM album_tracks
                WHERE album = ? AND track_number = ? AND track = ?
                  AND rowid NOT IN (
                      SELECT rowid FROM album_tracks
                      WHERE album = ? AND track_number = ? AND track = ?
                      ORDER BY rowid
                      LIMIT 1
                  )
            """, (album_name, track_number, track, album_name, track_number, track))

        print(f"  Deduplicated: Track {track_number} '{track}' - removed {dup_count - 1} duplicates")
        fixed_count += dup_count - 1

    if not dry_run:
        conn.commit()

    conn.close()
    return fixed_count


def fix_album_by_musicbrainz(album_name: str, album_mbid: str, dry_run: bool = False):
    """Fix album_tracks by re-fetching from MusicBrainz."""
    if not album_mbid:
        print(f"  Skipping {album_name}: No MBID available")
        return 0

    print(f"  Fetching from MusicBrainz for MBID: {album_mbid}")

    if not dry_run:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # Delete existing tracks for this album
        cursor.execute("""
            DELETE FROM album_tracks
            WHERE album = ? AND (album_mbid IS NULL OR album_mbid = '')
        """, (album_name,))
        deleted_count = cursor.rowcount

        conn.close()

        # Fetch from MusicBrainz
        tracks = fetch_album_tracklist_by_mbid(album_mbid)
        if tracks:
            upsert_album_tracks("Various Artists", album_name, tracks, album_mbid)
            print(f"  Fetched {len(tracks)} tracks from MusicBrainz")
            return len(tracks)
        else:
            print(f"  Failed to fetch from MusicBrainz")
            return 0
    else:
        print(f"  Would re-fetch from MusicBrainz (dry run)")
        return 0


def main():
    parser = argparse.ArgumentParser(description='Fix compilation tracks with Various Artists as track artist')
    parser.add_argument('--dry-run', action='store_true', help='Preview changes without applying them')
    parser.add_argument('--album', type=str, help='Fix only this specific album')
    parser.add_argument('--method', choices=['auto', 'scrobble', 'musicbrainz'], default='auto',
                       help='Fix method: auto=use MusicBrainz if MBID exists else scrobble data')

    args = parser.parse_args()

    if args.album:
        # Fix specific album
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute("""
            SELECT album_mbid
            FROM scrobble
            WHERE album = ? AND album_artist = 'Various Artists'
            LIMIT 1
        """, (args.album,))

        row = cursor.fetchone()
        conn.close()

        album_mbid = row["album_mbid"] if row else None

        print(f"Fixing album: {args.album}")
        if album_mbid:
            print(f"  MBID: {album_mbid}")

        if args.method in ['auto', 'musicbrainz'] and album_mbid:
            fix_album_by_musicbrainz(args.album, album_mbid, args.dry_run)
        else:
            fix_album_by_scrobble_data(args.album, args.dry_run)
    else:
        # Fix all compilations
        compilations = get_compilations_with_various_artists_tracks()

        if not compilations:
            print("No compilations found with Various Artists as track artist")
            return

        print(f"Found {len(compilations)} compilations with Various Artists as track artist:")
        for comp in compilations:
            print(f"  - {comp['album']} ({comp['track_count']} tracks)")

        if not args.dry_run:
            response = input(f"\nFix {len(compilations)} compilations? (y/n): ")
            if response.lower() != 'y':
                print("Aborted")
                return

        total_fixed = 0
        for comp in compilations:
            album_name = comp['album']
            album_mbid = comp['album_mbid']

            print(f"\nFixing: {album_name}")
            if args.method in ['auto', 'musicbrainz'] and album_mbid:
                total_fixed += fix_album_by_musicbrainz(album_name, album_mbid, args.dry_run)
            else:
                total_fixed += fix_album_by_scrobble_data(album_name, args.dry_run)

        print(f"\nTotal tracks fixed: {total_fixed}")


if __name__ == "__main__":
    main()
