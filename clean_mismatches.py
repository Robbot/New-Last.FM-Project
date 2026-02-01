#!/usr/bin/env python3
"""
Interactive script to clean up mismatches between scrobble and album_tracks tables.

Each mismatch must be approved before applying changes to the database.
"""

import sqlite3
import re
import sys
from collections import defaultdict

# Database path
DB_PATH = '/home/roju/New-Last.FM-Project/files/lastfmstats.sqlite'

# Common suffix patterns that cause mismatches (for normalization)
SUFFIX_PATTERNS = [
    r'\s*-\s*Remastered(\s+\d{4})?',
    r'\s*-\s*\d{4}\s+Remastered',
    r'\s*-\s*\d{4}\s+Remaster',
    r'\s*\(Remastered(\s+\d{4})?\)',
    r'\s*\(Remaster\)',
    r'\s*-\s*Expanded\s+Edition',
    r'\s*\(Expanded\s+Edition\)',
    r'\s*-\s*Deluxe\s+Edition',
    r'\s*\(Deluxe\s+Edition\)',
    r'\s*-\s*Deluxe',
    r'\s*\(Deluxe\)',
    r'\s*-\s*Special\s+Edition',
    r'\s*\(Special\s+Edition\)',
    r'\s*-\s*Limited\s+Edition',
    r'\s*\(Limited\s+Edition\)',
    r'\s*-\s*Collector\'?s?\s+Edition',
    r'\s*\(Collector\'?s?\s+Edition\)',
    r'\s*-\s*Bonus\s+Track',
    r'\s*\(Bonus\s+Track\)',
    r'\s*\(Bonus\s+Tracks\)',
    r'\s*\[Bonus.*?\]',
    r'\s*-\s*Single\s+Version',
    r'\s*\(Single\s+Version\)',
    r'\s*-\s*Album\s+Version',
    r'\s*\(Album\s+Version\)',
    r'\s*-\s*Radio\s+Edit',
    r'\s*\(Radio\s+Edit\)',
    r'\s*-\s*Original.*?\)',
    r'\s*\(Original.*?\)',
    r'\s*\(feat\..*?\)',
    r'\s*\(with.*?\)',
    r'\s*\(from.*?\)',
    r'\s*\(z\s+filmu.*?\)',  # Polish: "from the movie"
    r'\s*-\s*z\s+filmu.*?\)',  # Polish variation
    r'\s*\(demo.*?\)',
    r'\s*-\s*demo.*?',
    r'\s*-\s*\d{4}\s+Version',
    r'\s*\[Explicit\]',
    r'\s*\(Live.*?\)',
    r'\s*-\s*Live',
    r'\s*\(.*?Remix.*?\)',
    r'\s*-\s*.*?Remix',
    r'\s*\(Bonus Track Version\)',
    r'\s*\(Spotify Exclusive\)',
]

# Patterns to detect duplicate suffixes (e.g., "(z filmu X) (z filmu X)")
DUPLICATE_SUFFIX_PATTERNS = [
    (r'(\s*\(z\s+filmu[^(]+\))\1', r'\1'),  # Duplicate Polish film credits
    (r'(\s*\([^)]+\))\1', r'\1'),  # General duplicate parentheses
]

# Case variations that should be normalized
CASE_VARIATIONS = [
    (r'\bDeepest Purple\b', 'Deepest Purple'),
    (r'\bDeep Purple\b', 'Deep Purple'),
]


def normalize_name(name):
    """Normalize a name by removing common suffixes."""
    original = name
    for pattern in SUFFIX_PATTERNS:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    name = name.strip()
    # Remove duplicate suffixes
    for pattern, replacement in DUPLICATE_SUFFIX_PATTERNS:
        name = re.sub(pattern, replacement, name, flags=re.IGNORECASE)
    return name.strip()


def similarity_score(str1, str2):
    """Calculate a similarity score between two strings."""
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()
    if s1 == s2:
        return 100
    if s1 in s2 or s2 in s1:
        return 80
    return 0


def get_similarity_type(s_name, a_name):
    """Determine the type of mismatch."""
    s_lower = s_name.lower()
    a_lower = a_name.lower()

    # Check for remastered/deluxe suffix in album_tracks but not in scrobble
    for pattern in SUFFIX_PATTERNS[:20]:  # Check main suffix patterns
        if re.search(pattern, a_name, re.IGNORECASE) and not re.search(pattern, s_name, re.IGNORECASE):
            # Check if s_name + suffix matches a_name
            test = s_name + re.search(pattern, a_name, re.IGNORECASE).group(0)
            if test.lower() == a_lower:
                return f"album_tracks has suffix, scrobble cleaned"

    # Check for remastered/deluxe suffix in scrobble but not in album_tracks
    for pattern in SUFFIX_PATTERNS[:20]:
        if re.search(pattern, s_name, re.IGNORECASE) and not re.search(pattern, a_name, re.IGNORECASE):
            test = a_name + re.search(pattern, s_name, re.IGNORECASE).group(0)
            if test.lower() == s_lower:
                return f"scrobble has suffix, album_tracks cleaned"

    # Check for duplicate suffixes
    for pattern, _ in DUPLICATE_SUFFIX_PATTERNS:
        if re.search(pattern, a_name, re.IGNORECASE):
            return "duplicate suffix in album_tracks"
        if re.search(pattern, s_name, re.IGNORECASE):
            return "duplicate suffix in scrobble"

    # Check for remix/version suffix
    if re.search(r'\(.*?remix.*?\)|-\s*.*?remix', a_name, re.IGNORECASE):
        return "remix version in album_tracks"
    if re.search(r'\(.*?remix.*?\)|-\s*.*?remix', s_name, re.IGNORECASE):
        return "remix version in scrobble"

    # Check for live version
    if 'live' in a_lower and 'live' not in s_lower and s_lower in a_lower:
        return "live version in album_tracks"
    if 'live' in s_lower and 'live' not in a_lower and a_lower in s_lower:
        return "live version in scrobble"

    # Check for case difference only
    if s_lower == a_lower:
        return "case difference"

    return "other"


def find_mismatches(conn):
    """Find all mismatches between scrobble and album_tracks."""
    cursor = conn.cursor()

    # Get unique entries from both tables
    cursor.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
        ORDER BY artist, album, track
    """)
    scrobble_entries = [dict(row) for row in cursor.fetchall()]

    cursor.execute("""
        SELECT DISTINCT artist, album, track
        FROM album_tracks
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
        ORDER BY artist, album, track
    """)
    album_tracks_entries = [dict(row) for row in cursor.fetchall()]

    # Group by artist and album
    scrobble_by_album = defaultdict(set)
    for e in scrobble_entries:
        scrobble_by_album[(e['artist'], e['album'])].add(e['track'])

    album_tracks_by_album = defaultdict(set)
    for e in album_tracks_entries:
        album_tracks_by_album[(e['artist'], e['album'])].add(e['track'])

    # Find album mismatches
    scrobble_albums = defaultdict(set)
    for e in scrobble_entries:
        scrobble_albums[e['artist']].add(e['album'])

    album_tracks_albums = defaultdict(set)
    for e in album_tracks_entries:
        album_tracks_albums[e['artist']].add(e['album'])

    album_mismatches = []
    for artist in scrobble_albums:
        if artist not in album_tracks_albums:
            continue
        for s_album in scrobble_albums[artist]:
            s_album_norm = normalize_name(s_album)
            for a_album in album_tracks_albums[artist]:
                a_album_norm = normalize_name(a_album)
                if s_album != a_album and s_album_norm == a_album_norm:
                    mismatch_type = get_similarity_type(s_album, a_album)
                    album_mismatches.append({
                        'artist': artist,
                        'scrobble_album': s_album,
                        'album_tracks_album': a_album,
                        'normalized': s_album_norm,
                        'type': mismatch_type,
                    })

    # Find track mismatches (only for albums that exist in both tables)
    track_mismatches = []
    for key in scrobble_by_album:
        if key not in album_tracks_by_album:
            continue
        artist, album = key
        for s_track in scrobble_by_album[key]:
            s_track_norm = normalize_name(s_track)
            for a_track in album_tracks_by_album[key]:
                a_track_norm = normalize_name(a_track)
                if s_track != a_track and s_track_norm == a_track_norm:
                    mismatch_type = get_similarity_type(s_track, a_track)
                    track_mismatches.append({
                        'artist': artist,
                        'album': album,
                        'scrobble_track': s_track,
                        'album_tracks_track': a_track,
                        'normalized': s_track_norm,
                        'type': mismatch_type,
                    })

    return album_mismatches, track_mismatches


def display_mismatch(mismatch, index, total, category):
    """Display a single mismatch for user review."""
    print(f"\n{'='*70}")
    print(f"[{index + 1}/{total}] {category.upper()} MISMATCH - Type: {mismatch['type']}")
    print(f"{'='*70}")

    if category == 'album':
        print(f"Artist:       {mismatch['artist']}")
        print(f"Scrobble:     {mismatch['scrobble_album']}")
        print(f"Album Tracks: {mismatch['album_tracks_album']}")
        print(f"Normalized:   {mismatch['normalized']}")
    else:
        print(f"Artist:       {mismatch['artist']}")
        print(f"Album:        {mismatch['album']}")
        print(f"Scrobble:     {mismatch['scrobble_track']}")
        print(f"Album Tracks: {mismatch['album_tracks_track']}")
        print(f"Normalized:   {mismatch['normalized']}")


def prompt_action():
    """Prompt user for action on current mismatch."""
    print("\nOptions:")
    print("  [y] yes    - Apply change (normalize both to the clean version)")
    print("  [s] scrob  - Change album_tracks to match scrobble")
    print("  [a] alb    - Change scrobble to match album_tracks")
    print("  [n] no     - Skip this mismatch")
    print("  [q] quit   - Exit without saving")
    print("  [d] done   - Apply approved changes and exit")

    while True:
        choice = input("\nYour choice [y/s/a/n/q/d]? ").strip().lower()
        # Normalize to single character for consistency
        if choice in ['y', 'yes']:
            return 'y'
        elif choice in ['s', 'scrob']:
            return 's'
        elif choice in ['a', 'alb']:
            return 'a'
        elif choice in ['n', 'no']:
            return 'n'
        elif choice in ['q', 'quit']:
            return 'q'
        elif choice in ['d', 'done']:
            return 'd'
        else:
            print("Invalid choice. Please try again.")


def apply_changes(conn, album_changes, track_changes):
    """Apply approved changes to the database."""
    cursor = conn.cursor()
    total = len(album_changes) + len(track_changes)

    print(f"\n{'='*70}")
    print(f"APPLYING {total} CHANGES")
    print(f"{'='*70}")

    # Apply album changes to scrobble table
    for change in album_changes:
        if change['action'] in ['y', 's']:  # Normalize or use scrobble version
            # Update scrobble table to use the normalized version
            if change['action'] == 'y':
                new_album = change['normalized']
            else:  # 's' - keep scrobble as is, update album_tracks
                new_album = change['scrobble_album']

            cursor.execute("""
                UPDATE scrobble
                SET album = ?
                WHERE artist = ? AND album = ?
            """, (new_album, change['artist'], change['scrobble_album']))
            print(f"Updated scrobble: '{change['scrobble_album']}' -> '{new_album}'")

        if change['action'] in ['y', 'a']:  # Normalize or use album_tracks version
            # Update album_tracks table to use the normalized version
            if change['action'] == 'y':
                new_album = change['normalized']
            else:  # 'a' - keep album_tracks as is, update scrobble
                new_album = change['album_tracks_album']

            cursor.execute("""
                UPDATE album_tracks
                SET album = ?
                WHERE artist = ? AND album = ?
            """, (new_album, change['artist'], change['album_tracks_album']))
            print(f"Updated album_tracks: '{change['album_tracks_album']}' -> '{new_album}'")

    # Apply track changes
    for change in track_changes:
        if change['action'] in ['y', 's']:  # Normalize or use scrobble version
            if change['action'] == 'y':
                new_track = change['normalized']
            else:  # 's'
                new_track = change['scrobble_track']

            cursor.execute("""
                UPDATE scrobble
                SET track = ?
                WHERE artist = ? AND album = ? AND track = ?
            """, (new_track, change['artist'], change['album'], change['scrobble_track']))
            print(f"Updated scrobble track: '{change['scrobble_track']}' -> '{new_track}'")

        if change['action'] in ['y', 'a']:  # Normalize or use album_tracks version
            if change['action'] == 'y':
                new_track = change['normalized']
            else:  # 'a'
                new_track = change['album_tracks_track']

            cursor.execute("""
                UPDATE album_tracks
                SET track = ?
                WHERE artist = ? AND album = ? AND track = ?
            """, (new_track, change['artist'], change['album'], change['album_tracks_track']))
            print(f"Updated album_tracks track: '{change['album_tracks_track']}' -> '{new_track}'")

    conn.commit()
    print(f"\n✓ Successfully applied {total} changes!")


def batch_review_mismatches(mismatches, category):
    """Review mismatches with options for batch processing.

    Returns:
        - None: User pressed 'd' (done) - stop all processing and apply changes
        - []: User pressed 'q' (quit) - exit without saving
        - list: List of approved changes for this batch
    """
    if not mismatches:
        return []

    approved = []
    index = 0

    while index < len(mismatches):
        mismatch = mismatches[index]
        display_mismatch(mismatch, index, len(mismatches), category)

        choice = prompt_action()

        if choice == 'q':
            # Signal to stop all processing and exit without saving
            # Optionally save pending changes first
            if approved:
                save = input(f"\nYou have {len(approved)} pending changes. Save before quitting? [y/N]: ").strip().lower()
                if save == 'y':
                    # Return tuple to indicate "quit with save"
                    return ('QUIT', approved)
            # Return tuple to indicate "quit without saving"
            return ('QUIT', [])

        if choice == 'd':
            # Signal to stop all processing and apply approved changes
            # Return tuple to indicate "done with all processing"
            return ('DONE', approved)

        if choice == 'n':
            index += 1
            continue

        # Apply the change
        approved.append({**mismatch, 'action': choice})
        index += 1

    return approved


def main():
    """Main interactive cleaning function."""
    print("="*70)
    print("DATABASE MISMATCH CLEANING TOOL")
    print("="*70)
    print("\nThis tool will help you clean up mismatches between the scrobble")
    print("and album_tracks tables. Each mismatch will be presented for your")
    print("approval before any changes are made.\n")

    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Find mismatches
    print("Scanning database for mismatches...")
    album_mismatches, track_mismatches = find_mismatches(conn)

    print(f"\nFound {len(album_mismatches)} album mismatches")
    print(f"Found {len(track_mismatches)} track mismatches")

    if not album_mismatches and not track_mismatches:
        print("\n✓ No mismatches found! Database is clean.")
        conn.close()
        return

    # Group mismatches by type for easier navigation
    album_by_type = defaultdict(list)
    for m in album_mismatches:
        album_by_type[m['type']].append(m)

    track_by_type = defaultdict(list)
    for m in track_mismatches:
        track_by_type[m['type']].append(m)

    print("\nMismatch types found:")
    print("\nAlbum mismatches:")
    for mtype, mismatches in sorted(album_by_type.items(), key=lambda x: -len(x[1])):
        print(f"  - {mtype}: {len(mismatches)}")

    print("\nTrack mismatches:")
    for mtype, mismatches in sorted(track_by_type.items(), key=lambda x: -len(x[1])):
        print(f"  - {mtype}: {len(mismatches)}")

    # Ask which category to process
    print("\n" + "="*70)
    print("What would you like to clean?")
    print("  [1] Albums only")
    print("  [2] Tracks only")
    print("  [3] Both (albums first, then tracks)")
    print("  [q] Quit")

    while True:
        choice = input("\nYour choice [1/2/3/q]: ").strip().lower()
        if choice in ['1', '2', '3', 'q']:
            break
        print("Invalid choice.")

    if choice == 'q':
        conn.close()
        return

    all_approved = []
    done_processing = False
    quit_without_saving = False

    # Process albums
    if choice in ['1', '3']:
        # Process most common types first
        for mtype in ['album_tracks has suffix, scrobble cleaned', 'duplicate suffix in album_tracks', 'case difference']:
            if mtype in album_by_type:
                print(f"\n--- Processing album mismatches: {mtype} ({len(album_by_type[mtype])} items) ---")
                result = batch_review_mismatches(album_by_type[mtype], 'album')
                # Check if user pressed 'd' (done) or 'q' (quit)
                if isinstance(result, tuple):
                    if result[0] == 'QUIT':
                        if result[1]:  # User chose to save pending changes
                            all_approved.extend([('album', a) for a in result[1]])
                        quit_without_saving = not result[1]
                        done_processing = True
                        break
                    elif result[0] == 'DONE':
                        all_approved.extend([('album', a) for a in result[1]])
                        done_processing = True
                        break
                all_approved.extend([('album', a) for a in result])

        # Process remaining types
        if not done_processing:
            for mtype in sorted(album_by_type.keys()):
                if mtype not in ['album_tracks has suffix, scrobble cleaned', 'duplicate suffix in album_tracks', 'case difference']:
                    print(f"\n--- Processing album mismatches: {mtype} ({len(album_by_type[mtype])} items) ---")
                    result = batch_review_mismatches(album_by_type[mtype], 'album')
                    # Check if user pressed 'd' (done) or 'q' (quit)
                    if isinstance(result, tuple):
                        if result[0] == 'QUIT':
                            if result[1]:  # User chose to save pending changes
                                all_approved.extend([('album', a) for a in result[1]])
                            quit_without_saving = not result[1]
                            done_processing = True
                            break
                        elif result[0] == 'DONE':
                            all_approved.extend([('album', a) for a in result[1]])
                            done_processing = True
                            break
                    all_approved.extend([('album', a) for a in result])

    # Process tracks
    if choice in ['2', '3'] and not done_processing:
        # Process most common types first
        for mtype in ['album_tracks has suffix, scrobble cleaned', 'duplicate suffix in album_tracks', 'case difference']:
            if mtype in track_by_type:
                print(f"\n--- Processing track mismatches: {mtype} ({len(track_by_type[mtype])} items) ---")
                result = batch_review_mismatches(track_by_type[mtype], 'track')
                # Check if user pressed 'd' (done) or 'q' (quit)
                if isinstance(result, tuple):
                    if result[0] == 'QUIT':
                        if result[1]:  # User chose to save pending changes
                            all_approved.extend([('track', a) for a in result[1]])
                        quit_without_saving = not result[1]
                        done_processing = True
                        break
                    elif result[0] == 'DONE':
                        all_approved.extend([('track', a) for a in result[1]])
                        done_processing = True
                        break
                all_approved.extend([('track', a) for a in result])

        # Process remaining types
        if not done_processing:
            for mtype in sorted(track_by_type.keys()):
                if mtype not in ['album_tracks has suffix, scrobble cleaned', 'duplicate suffix in album_tracks', 'case difference']:
                    print(f"\n--- Processing track mismatches: {mtype} ({len(track_by_type[mtype])} items) ---")
                    result = batch_review_mismatches(track_by_type[mtype], 'track')
                    # Check if user pressed 'd' (done) or 'q' (quit)
                    if isinstance(result, tuple):
                        if result[0] == 'QUIT':
                            if result[1]:  # User chose to save pending changes
                                all_approved.extend([('track', a) for a in result[1]])
                            quit_without_saving = not result[1]
                            done_processing = True
                            break
                        elif result[0] == 'DONE':
                            all_approved.extend([('track', a) for a in result[1]])
                            done_processing = True
                            break
                    all_approved.extend([('track', a) for a in result])

    # Apply changes
    if quit_without_saving:
        print("\nQuit without saving changes.")
    elif all_approved:
        album_changes = [a for t, a in all_approved if t == 'album']
        track_changes = [a for t, a in all_approved if t == 'track']
        apply_changes(conn, album_changes, track_changes)
    else:
        print("\nNo changes approved.")

    conn.close()
    if not quit_without_saving:
        print("\nDone!")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Exiting without changes.")
        sys.exit(0)
