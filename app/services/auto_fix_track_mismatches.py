#!/usr/bin/env python3
"""
Automatically fix track mismatches between scrobble and album_tracks tables.

This script finds scrobbles where the track name doesn't match the album tracklist
and attempts to fix them by finding the best matching track.
"""

import sqlite3
import sys
import unicodedata
from difflib import SequenceMatcher

DB_PATH = '/home/roju/New-Last.FM-Project/files/lastfmstats.sqlite'


def normalize_for_matching(name):
    """Normalize a name for fuzzy matching."""
    if not name:
        return ""

    # Normalize Unicode quotes/apostrophes to straight quotes
    name = name.replace('‘', "'")  # Left single quotation mark
    name = name.replace('’', "'")  # Right single quotation mark
    name = name.replace('“', '"')  # Left double quotation mark
    name = name.replace('”', '"')  # Right double quotation mark

    # Remove accents by converting to ASCII
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Convert to lowercase
    name = name.lower()
    # Replace hyphens with spaces
    name = name.replace('-', ' ')
    # Fix common typos
    name = name.replace('tiime', 'time')
    # Remove extra spaces
    name = ' '.join(name.split())
    return name


def similarity_score(str1, str2):
    """Calculate similarity score between two strings (0-100)."""
    s1 = normalize_for_matching(str1)
    s2 = normalize_for_matching(str2)
    return int(SequenceMatcher(None, s1, s2).ratio() * 100)


def find_best_match(scrobble_track, album_tracks):
    """Find the best matching track from album_tracks for a scrobble track."""
    best_match = None
    best_score = 0

    for track_info in album_tracks:
        track = track_info['track']
        score = similarity_score(scrobble_track, track)

        # Exact match (case insensitive)
        if scrobble_track.lower() == track.lower():
            return track, 100

        # Check if scrobble is a substring of album track or vice versa
        s1 = normalize_for_matching(scrobble_track)
        s2 = normalize_for_matching(track)
        if s1 in s2 or s2 in s1:
            # Prefer the longer string (album track usually has more detail)
            if len(s2) >= len(s1):
                score = max(score, 95)

        if score > best_score:
            best_score = score
            best_match = track

    return best_match, best_score


def get_track_mismatches(conn):
    """Get all track mismatches from notifications."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, details
        FROM notifications
        WHERE type = 'track_mismatch' AND dismissed_at IS NULL
    """)

    mismatches = []
    for row in cursor.fetchall():
        details = row['details']
        if not details:
            continue

        import json
        try:
            detail = json.loads(details)
            mismatches.append({
                'id': row['id'],
                'artist': detail.get('artist'),
                'album': detail.get('album'),
                'scrobble_track': detail.get('scrobble_track'),
                'track_mbid': detail.get('track_mbid'),
                'album_tracks': detail.get('album_tracks', [])
            })
        except json.JSONDecodeError:
            continue

    return mismatches


def fix_mismatches(conn, mismatches, confidence_threshold=85, dry_run=True):
    """Fix track mismatches by updating scrobble track names.

    Args:
        conn: Database connection
        mismatches: List of mismatch dictionaries
        confidence_threshold: Minimum similarity score to auto-fix (0-100)
        dry_run: If True, don't make any changes

    Returns:
        Tuple of (fixed_count, skipped_count)
    """
    cursor = conn.cursor()
    fixed = 0
    skipped = 0

    print(f"\n{'='*70}")
    print(f"DRY RUN MODE - No changes will be made" if dry_run else "LIVE MODE - Changes will be applied")
    print(f"Confidence threshold: {confidence_threshold}%")
    print(f"{'='*70}\n")

    for mismatch in mismatches:
        artist = mismatch['artist']
        album = mismatch['album']
        scrobble_track = mismatch['scrobble_track']
        album_tracks = mismatch['album_tracks']

        if not album_tracks:
            print(f"⚠ No album tracks available for {artist} - {album}")
            skipped += 1
            continue

        best_match, score = find_best_match(scrobble_track, album_tracks)

        if best_match and score >= confidence_threshold:
            print(f"✓ [{score}%] {artist} - {album}")
            print(f"  Scrobble:  '{scrobble_track}'")
            print(f"  Album TL:  '{best_match}'")

            if not dry_run:
                # Update scrobble track name
                cursor.execute("""
                    UPDATE scrobble
                    SET track = ?
                    WHERE artist = ? AND album = ? AND track = ?
                """, (best_match, artist, album, scrobble_track))

                # Mark notification as resolved
                cursor.execute("""
                    UPDATE notifications
                    SET dismissed_at = datetime('now')
                    WHERE id = ?
                """, (mismatch['id'],))

            fixed += 1
        else:
            print(f"✗ [{score if best_match else 0}%] {artist} - {album}")
            print(f"  Scrobble:  '{scrobble_track}'")
            print(f"  Best match: '{best_match}' (below threshold)")
            skipped += 1
        print()

    if not dry_run:
        conn.commit()

    return fixed, skipped


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Auto-fix track mismatches between scrobble and album_tracks'
    )
    parser.add_argument(
        '--confidence',
        type=int,
        default=85,
        help='Minimum similarity score to auto-fix (0-100, default: 85)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without making changes'
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Actually apply changes (default is dry-run)'
    )

    args = parser.parse_args()

    # Default to dry-run for safety
    dry_run = not args.apply

    print("="*70)
    print("TRACK MISMATCH AUTO-FIX TOOL")
    print("="*70)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Get mismatches from notifications
    print("Loading track mismatches from notifications...")
    mismatches = get_track_mismatches(conn)

    if not mismatches:
        print("No track mismatches found!")
        conn.close()
        return

    print(f"Found {len(mismatches)} track mismatches")

    # Fix mismatches
    fixed, skipped = fix_mismatches(
        conn,
        mismatches,
        confidence_threshold=args.confidence,
        dry_run=dry_run
    )

    print(f"\n{'='*70}")
    print(f"SUMMARY")
    print(f"{'='*70}")
    print(f"Total mismatches: {len(mismatches)}")
    print(f"Would fix: {fixed}")
    print(f"Would skip: {skipped}")

    if dry_run:
        print(f"\nTo apply changes, run with --apply flag")
    else:
        print(f"\n✓ Changes applied successfully!")

    conn.close()


if __name__ == '__main__':
    main()
