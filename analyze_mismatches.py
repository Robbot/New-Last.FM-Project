#!/usr/bin/env python3
"""Analyze mismatches between scrobble and album_tracks tables."""

import sqlite3
import re
from collections import defaultdict

# Common suffix patterns that cause mismatches
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
    r'\s*-\s*Remix',
    r'\s*\(Remix\)',
    r'\s*-\s*Original.*?\)',
    r'\s*\(Original.*?\)',
    r'\s*\(feat\..*?\)',
    r'\s*\(with.*?\)',
    r'\s*\(from.*?\)',
    r'\s*\(z\s+filmu.*?\)',  # Polish: "from the movie"
    r'\s*\(demo.*?\)',
    r'\s*-\s*demo.*?',
]

def normalize_name(name):
    """Normalize a name by removing common suffixes and normalizing case."""
    original = name
    for pattern in SUFFIX_PATTERNS:
        name = re.sub(pattern, '', name, flags=re.IGNORECASE)
    return name.strip()

def similarity_score(str1, str2):
    """Calculate a simple similarity score."""
    s1 = str1.lower().strip()
    s2 = str2.lower().strip()
    if s1 == s2:
        return 100
    if s1 in s2 or s2 in s1:
        return 80
    return 0

def analyze_database(db_path):
    """Analyze mismatches between scrobble and album_tracks tables."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get unique artist/album/track combinations from scrobble
    cursor.execute("""
        SELECT DISTINCT artist, album, track
        FROM scrobble
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
    """)
    scrobble_entries = {f"{row['artist']}|{row['album']}|{row['track']}": dict(row) for row in cursor.fetchall()}

    # Get unique artist/album/track combinations from album_tracks
    cursor.execute("""
        SELECT DISTINCT artist, album, track
        FROM album_tracks
        WHERE album IS NOT NULL AND album != '' AND track IS NOT NULL AND track != ''
    """)
    album_tracks_entries = {f"{row['artist']}|{row['album']}|{row['track']}": dict(row) for row in cursor.fetchall()}

    # Find mismatches
    album_mismatches = []
    track_mismatches = []

    # Analyze album mismatches
    scrobble_albums = defaultdict(set)
    for key, entry in scrobble_entries.items():
        scrobble_albums[entry['artist']].add(entry['album'])

    album_tracks_albums = defaultdict(set)
    for key, entry in album_tracks_entries.items():
        album_tracks_albums[entry['artist']].add(entry['album'])

    for artist in scrobble_albums:
        if artist not in album_tracks_albums:
            continue
        for s_album in scrobble_albums[artist]:
            s_album_norm = normalize_name(s_album)
            for a_album in album_tracks_albums[artist]:
                a_album_norm = normalize_name(a_album)
                if s_album != a_album and (s_album_norm == a_album_norm or similarity_score(s_album_norm, a_album_norm) >= 80):
                    album_mismatches.append({
                        'artist': artist,
                        'scrobble_album': s_album,
                        'album_tracks_album': a_album,
                        'normalized': s_album_norm
                    })

    # Analyze track mismatches (only where album matches exactly)
    scrobble_tracks_key = defaultdict(set)
    for key, entry in scrobble_entries.items():
        scrobble_tracks_key[(entry['artist'], entry['album'])].add(entry['track'])

    album_tracks_tracks_key = defaultdict(set)
    for key, entry in album_tracks_entries.items():
        album_tracks_tracks_key[(entry['artist'], entry['album'])].add(entry['track'])

    for key in scrobble_tracks_key:
        if key not in album_tracks_tracks_key:
            continue
        artist, album = key
        for s_track in scrobble_tracks_key[key]:
            s_track_norm = normalize_name(s_track)
            for a_track in album_tracks_tracks_key[key]:
                a_track_norm = normalize_name(a_track)
                if s_track != a_track and (s_track_norm == a_track_norm or similarity_score(s_track_norm, a_track_norm) >= 80):
                    track_mismatches.append({
                        'artist': artist,
                        'album': album,
                        'scrobble_track': s_track,
                        'album_tracks_track': a_track,
                        'normalized': s_track_norm
                    })

    conn.close()

    return album_mismatches, track_mismatches

def main():
    db_path = '/home/roju/New-Last.FM-Project/files/lastfmstats.sqlite'

    print("Analyzing database for mismatches...")
    album_mismatches, track_mismatches = analyze_database(db_path)

    print(f"\n{'='*60}")
    print(f"ALBUM MISMATCHES (found: {len(album_mismatches)})")
    print(f"{'='*60}")

    # Group by artist
    by_artist = defaultdict(list)
    for m in album_mismatches:
        by_artist[m['artist']].append(m)

    for artist in sorted(by_artist.keys()):
        print(f"\n{artist}:")
        seen = set()
        for m in by_artist[artist]:
            key = f"{m['scrobble_album']} <-> {m['album_tracks_album']}"
            if key not in seen:
                print(f"  Scrobble:     {m['scrobble_album']}")
                print(f"  Album Tracks: {m['album_tracks_album']}")
                seen.add(key)

    print(f"\n{'='*60}")
    print(f"TRACK MISMATCHES (found: {len(track_mismatches)})")
    print(f"{'='*60}")

    # Group by artist/album
    by_album = defaultdict(list)
    for m in track_mismatches:
        key = f"{m['artist']} - {m['album']}"
        by_album[key].append(m)

    for album_key in sorted(by_album.keys())[:30]:  # Show first 30 albums
        print(f"\n{album_key}:")
        seen = set()
        for m in by_album[album_key]:
            key = f"{m['scrobble_track']} <-> {m['album_tracks_track']}"
            if key not in seen:
                print(f"  Scrobble:     {m['scrobble_track']}")
                print(f"  Album Tracks: {m['album_tracks_track']}")
                seen.add(key)

    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Total album variations: {len(album_mismatches)}")
    print(f"Total track variations: {len(track_mismatches)}")
    print(f"Unique artists with album mismatches: {len(set(m['artist'] for m in album_mismatches))}")
    print(f"Unique albums with track mismatches: {len(by_album)}")

if __name__ == '__main__':
    main()
