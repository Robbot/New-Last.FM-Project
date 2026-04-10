#!/usr/bin/env python3
"""
Find scrobbles with track names that don't match album_tracks due to
misspellings, truncation, or minor discrepancies.

Uses fuzzy string matching to identify potential corrections.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.db.connections import get_db_connection


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate the Levenshtein distance between two strings.
    Returns the minimum number of single-character edits (insertions, deletions, or substitutions)
    required to change one string into the other.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)

    # len(s1) >= len(s2)
    if len(s2) == 0:
        return len(s1)

    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row

    return previous_row[-1]


def similarity_score(s1: str, s2: str) -> float:
    """
    Calculate a similarity score between two strings.
    Returns a value between 0.0 and 1.0, where 1.0 is identical.
    Uses a combination of Levenshtein distance and length ratio.
    """
    if not s1 or not s2:
        return 0.0

    # Normalize for comparison (lowercase, strip whitespace)
    s1_norm = s1.lower().strip()
    s2_norm = s2.lower().strip()

    # Levenshtein distance
    max_len = max(len(s1_norm), len(s2_norm))
    if max_len == 0:
        return 1.0

    distance = levenshtein_distance(s1_norm, s2_norm)

    # Calculate similarity score
    # Use 1 - (distance / max_len) as base score
    base_score = 1.0 - (distance / max_len)

    # Apply penalty for very different lengths
    length_ratio = min(len(s1_norm), len(s2_norm)) / max_len
    final_score = base_score * (0.7 + 0.3 * length_ratio)

    return final_score


def find_potential_matches(scrobble_track: str, album_tracks: list[dict], threshold: float = 0.7) -> list[tuple]:
    """
    Find potential matching tracks in album_tracks for a given scrobble track.

    Args:
        scrobble_track: The track name from scrobbles
        album_tracks: List of dicts with 'track' and 'track_number' from album_tracks
        threshold: Minimum similarity score (0.0 to 1.0) to consider a match

    Returns:
        List of tuples: (album_track_name, track_number, similarity_score)
    """
    matches = []

    for track_info in album_tracks:
        album_track = track_info['track']
        score = similarity_score(scrobble_track, album_track)

        if score >= threshold:
            matches.append((album_track, track_info['track_number'], score))

    # Sort by similarity score (highest first)
    matches.sort(key=lambda x: x[2], reverse=True)
    return matches


def find_unmatched_scrobbles(artist: str = None, album: str = None) -> list[dict]:
    """
    Find scrobbles that don't have exact matches in album_tracks.

    Args:
        artist: Filter by specific artist (optional)
        album: Filter by specific album (optional)

    Returns:
        List of dicts with scrobble info and potential matches
    """
    conn = get_db_connection()

    # Build query
    sql = """
        SELECT DISTINCT
            s.artist,
            s.album,
            s.track as scrobble_track,
            COUNT(*) as scrobble_count,
            MAX(s.uts) as last_played
        FROM scrobble s
        LEFT JOIN album_tracks at
            ON s.artist = at.artist
            AND s.album = at.album
            AND s.track = at.track
        WHERE at.track IS NULL
    """

    params = []
    if artist:
        sql += " AND s.artist = ?"
        params.append(artist)
    if album:
        sql += " AND s.album = ?"
        params.append(album)

    sql += """
        GROUP BY s.artist, s.album, s.track
        ORDER BY s.artist, s.album, scrobble_count DESC
    """

    cursor = conn.execute(sql, params)
    scrobbles = cursor.fetchall()
    conn.close()

    return [dict(row) for row in scrobbles]


def find_all_mismatches(threshold: float = 0.7) -> list[dict]:
    """
    Find all scrobbles that don't match album_tracks and find potential matches.

    Args:
        threshold: Minimum similarity score to consider a match (default 0.7)

    Returns:
        List of dicts with scrobble info and potential matches
    """
    conn = get_db_connection()

    # Get all unique (artist, album) combinations that have album_tracks
    cursor = conn.execute("""
        SELECT DISTINCT artist, album
        FROM album_tracks
        ORDER BY artist, album
    """)
    albums = cursor.fetchall()

    results = []

    for album_row in albums:
        artist = album_row['artist']
        album = album_row['album']

        # Get all tracks for this album from album_tracks
        cursor = conn.execute("""
            SELECT track, track_number
            FROM album_tracks
            WHERE artist = ? AND album = ?
            ORDER BY track_number
        """, (artist, album))
        album_tracks = [dict(row) for row in cursor.fetchall()]

        if not album_tracks:
            continue

        # Get scrobbles for this album that don't match
        cursor = conn.execute("""
            SELECT
                s.track as scrobble_track,
                COUNT(*) as scrobble_count,
                MAX(s.uts) as last_played
            FROM scrobble s
            LEFT JOIN album_tracks at
                ON s.artist = at.artist
                AND s.album = at.album
                AND s.track = at.track
            WHERE s.artist = ? AND s.album = ? AND at.track IS NULL
            GROUP BY s.track
            ORDER BY s.track
        """, (artist, album))
        unmatched = cursor.fetchall()

        for scrobble_row in unmatched:
            scrobble_track = scrobble_row['scrobble_track']
            scrobble_count = scrobble_row['scrobble_count']
            last_played = scrobble_row['last_played']

            # Find potential matches
            matches = find_potential_matches(scrobble_track, album_tracks, threshold)

            if matches:
                results.append({
                    'artist': artist,
                    'album': album,
                    'scrobble_track': scrobble_track,
                    'scrobble_count': scrobble_count,
                    'last_played': last_played,
                    'matches': matches
                })

    conn.close()
    return results


def print_results(results: list[dict], show_all: bool = False):
    """
    Print the mismatch results in a readable format.

    Args:
        results: List of dicts from find_all_mismatches
        show_all: If True, show all results; if False, only show high-confidence matches
    """
    if not results:
        print("No mismatches found.")
        return

    print(f"\nFound {len(results)} scrobbles with potential mismatches:\n")
    print("=" * 100)

    current_artist = None
    current_album = None

    for result in results:
        artist = result['artist']
        album = result['album']

        # Print album header
        if artist != current_artist or album != current_album:
            print(f"\n{artist} — {album}")
            print("-" * 100)
            current_artist = artist
            current_album = album

        scrobble_track = result['scrobble_track']
        scrobble_count = result['scrobble_count']

        print(f"\n  Scrobble: \"{scrobble_track}\" ({scrobble_count} plays)")

        for match_track, track_num, score in result['matches']:
            # Only show high-confidence matches unless show_all is True
            if show_all or score >= 0.8:
                confidence = "HIGH" if score >= 0.9 else "MED" if score >= 0.8 else "LOW"
                print(f"    → Track #{track_num}: \"{match_track}\" (similarity: {score:.2%}) [{confidence}]")

    print("\n" + "=" * 100)


def generate_update_sql(results: list[dict], min_score: float = 0.85) -> str:
    """
    Generate SQL UPDATE statements for high-confidence matches.

    Args:
        results: List of dicts from find_all_mismatches
        min_score: Minimum similarity score to generate an UPDATE statement

    Returns:
        String containing SQL UPDATE statements
    """
    statements = []

    for result in results:
        artist = result['artist'].replace("'", "''")
        album = result['album'].replace("'", "''")
        scrobble_track = result['scrobble_track'].replace("'", "''")

        for match_track, track_num, score in result['matches']:
            if score >= min_score:
                match_track_escaped = match_track.replace("'", "''")
                stmt = f"""UPDATE scrobble SET track = '{match_track_escaped}' WHERE track = '{scrobble_track}' AND artist = '{artist}' AND album = '{album}';"""
                statements.append(stmt)

    if not statements:
        return "-- No high-confidence matches found for auto-update\n"

    return "\n".join([
        "-- Auto-generated UPDATE statements for high-confidence matches",
        f"-- Minimum similarity score: {min_score:.0%}",
        f"-- Total statements: {len(statements)}",
        "-- Review carefully before executing!\n",
        *statements
    ])


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Find scrobbles with track names that may need correction'
    )
    parser.add_argument(
        '--artist',
        help='Filter by specific artist'
    )
    parser.add_argument(
        '--album',
        help='Filter by specific album'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=0.7,
        help='Minimum similarity score (0.0 to 1.0, default: 0.7)'
    )
    parser.add_argument(
        '--show-all',
        action='store_true',
        help='Show all results including low-confidence matches'
    )
    parser.add_argument(
        '--generate-sql',
        action='store_true',
        help='Generate SQL UPDATE statements for high-confidence matches'
    )
    parser.add_argument(
        '--min-score',
        type=float,
        default=0.85,
        help='Minimum score for SQL generation (default: 0.85)'
    )

    args = parser.parse_args()

    if args.artist or args.album:
        # Filtered mode
        results = find_unmatched_scrobbles(args.artist, args.album)
        print(f"\nFound {len(results)} unmatched scrobbles")
        if args.artist:
            print(f"Artist: {args.artist}")
        if args.album:
            print(f"Album: {args.album}")

        for scrobble in results:
            print(f"  - {scrobble['scrobble_track']} ({scrobble['scrobble_count']} plays)")
    else:
        # Full analysis mode
        results = find_all_mismatches(args.threshold)
        print_results(results, args.show_all)

        if args.generate_sql:
            sql = generate_update_sql(results, args.min_score)
            print("\n" + sql)


if __name__ == "__main__":
    main()
