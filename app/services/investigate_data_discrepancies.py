#!/usr/bin/env python3
"""
Data quality investigation script.

Identifies discrepancies in scrobble data:
- Empty or different album_mbid for the same track on the same album
- Empty or incorrect album_artist fields
- Multiple MBIDs per album
- Albums with mixed album_artist values
"""
import argparse
import logging
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connections import get_db_connection

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def investigate_album_mbid_variations(artist: str | None = None):
    """Find tracks on the same album with different album_mbid values."""
    conn = get_db_connection()

    sql = """
        SELECT
            artist,
            album,
            track,
            album_mbid,
            COUNT(*) as play_count
        FROM scrobble
    """
    params = []

    if artist:
        sql += " WHERE artist = ?"
        params.append(artist)

    sql += """
        GROUP BY artist, album, track, album_mbid
        ORDER BY artist, album, track, play_count DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Group by (artist, album, track) to find variations
    track_groups = {}
    for row in rows:
        key = (row["artist"], row["album"], row["track"])
        if key not in track_groups:
            track_groups[key] = []
        track_groups[key].append({
            "album_mbid": row["album_mbid"],
            "play_count": row["play_count"]
        })

    # Find tracks with multiple MBIDs or empty MBIDs
    issues = []
    for key, variations in track_groups.items():
        artist, album, track = key
        mbids = [v["album_mbid"] for v in variations]

        if len(variations) > 1 or any(mbid is None or mbid == "" for mbid in mbids):
            total_plays = sum(v["play_count"] for v in variations)
            issues.append({
                "artist": artist,
                "album": album,
                "track": track,
                "variations": variations,
                "total_plays": total_plays
            })

    return issues


def investigate_album_mbid_variations_by_album(artist: str | None = None):
    """Find albums with multiple different album_mbid values."""
    conn = get_db_connection()

    sql = """
        SELECT
            artist,
            album,
            album_mbid,
            COUNT(*) as play_count
        FROM scrobble
    """
    params = []

    if artist:
        sql += " WHERE artist = ?"
        params.append(artist)

    sql += """
        GROUP BY artist, album, album_mbid
        ORDER BY artist, album, play_count DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Group by (artist, album) to find MBID variations
    album_groups = {}
    for row in rows:
        key = (row["artist"], row["album"])
        if key not in album_groups:
            album_groups[key] = []
        album_groups[key].append({
            "album_mbid": row["album_mbid"],
            "play_count": row["play_count"]
        })

    # Find albums with multiple MBIDs
    issues = []
    for key, variations in album_groups.items():
        if len(variations) > 1:
            artist, album = key
            total_plays = sum(v["play_count"] for v in variations)
            issues.append({
                "artist": artist,
                "album": album,
                "variations": variations,
                "total_plays": total_plays
            })

    return issues


def investigate_empty_album_artist(artist: str | None = None):
    """Find scrobbles with empty album_artist."""
    conn = get_db_connection()

    sql = """
        SELECT
            artist,
            album,
            album_artist,
            COUNT(*) as play_count
        FROM scrobble
        WHERE (album_artist IS NULL OR album_artist = '')
    """
    params = []

    if artist:
        sql += " AND artist = ?"
        params.append(artist)

    sql += """
        GROUP BY artist, album, album_artist
        ORDER BY play_count DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    return list(rows)


def investigate_inconsistent_album_artist(artist: str | None = None):
    """Find albums with multiple different album_artist values."""
    conn = get_db_connection()

    sql = """
        SELECT
            artist,
            album,
            COALESCE(album_artist, '') as album_artist,
            COUNT(*) as play_count
        FROM scrobble
    """
    params = []

    if artist:
        sql += " WHERE artist = ?"
        params.append(artist)

    sql += """
        GROUP BY artist, album, album_artist
        ORDER BY artist, album, play_count DESC
    """

    rows = conn.execute(sql, params).fetchall()
    conn.close()

    # Group by (artist, album) to find album_artist variations
    album_groups = {}
    for row in rows:
        key = (row["artist"], row["album"])
        if key not in album_groups:
            album_groups[key] = []
        album_groups[key].append({
            "album_artist": row["album_artist"],
            "play_count": row["play_count"]
        })

    # Find albums with multiple album_artist values
    issues = []
    for key, variations in album_groups.items():
        if len(variations) > 1:
            artist, album = key
            total_plays = sum(v["play_count"] for v in variations)
            issues.append({
                "artist": artist,
                "album": album,
                "variations": variations,
                "total_plays": total_plays
            })

    return issues


def get_correct_album_mbid(artist: str, album: str) -> str | None:
    """Get the correct album_mbid from album_art table."""
    conn = get_db_connection()
    row = conn.execute(
        "SELECT album_mbid FROM album_art WHERE artist = ? AND album = ?",
        (artist, album)
    ).fetchone()
    conn.close()

    return row["album_mbid"] if row and row["album_mbid"] else None


def print_section(title: str):
    """Print a section header."""
    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}\n")


def print_track_mbid_issues(issues: list):
    """Print track-level MBID variations."""
    if not issues:
        print("✓ No track-level MBID variations found.")
        return

    print(f"⚠ Found {len(issues)} tracks with MBID variations:\n")

    for i, issue in enumerate(issues, 1):
        print(f"{i}. {issue['artist']} - {issue['album']} - {issue['track']}")
        print(f"   Total plays: {issue['total_plays']}")
        print(f"   Variations:")
        for var in issue['variations']:
            mbid = var['album_mbid'] if var['album_mbid'] else "(empty)"
            print(f"     - MBID: {mbid} ({var['play_count']} plays)")

        # Suggest correct MBID
        correct_mbid = get_correct_album_mbid(issue['artist'], issue['album'])
        if correct_mbid:
            print(f"   → Correct MBID from album_art: {correct_mbid}")
            print(f"   → Fix: UPDATE scrobble SET album_mbid = '{correct_mbid}'")
            print(f"      WHERE artist = '{issue['artist']}' AND album = '{issue['album']}'")
            print(f"      AND track = '{issue['track']}' AND album_mbid IS NULL;")
        print()


def print_album_mbid_issues(issues: list):
    """Print album-level MBID variations."""
    if not issues:
        print("✓ No album-level MBID variations found.")
        return

    print(f"⚠ Found {len(issues)} albums with MBID variations:\n")

    for i, issue in enumerate(issues, 1):
        print(f"{i}. {issue['artist']} - {issue['album']}")
        print(f"   Total plays: {issue['total_plays']}")
        print(f"   Variations:")
        for var in issue['variations']:
            mbid = var['album_mbid'] if var['album_mbid'] else "(empty)"
            print(f"     - MBID: {mbid} ({var['play_count']} plays)")

        # Suggest correct MBID
        correct_mbid = get_correct_album_mbid(issue['artist'], issue['album'])
        if correct_mbid:
            print(f"   → Correct MBID from album_art: {correct_mbid}")
            print(f"   → Fix: UPDATE scrobble SET album_mbid = '{correct_mbid}'")
            print(f"      WHERE artist = '{issue['artist']}' AND album = '{issue['album']}'")
            print(f"      AND album_mbid IS NULL;")
        print()


def print_empty_album_artist(rows: list):
    """Print tracks with empty album_artist."""
    if not rows:
        print("✓ No tracks with empty album_artist found.")
        return

    print(f"⚠ Found {len(rows)} (album, track) combinations with empty album_artist:\n")

    for i, row in enumerate(rows[:20], 1):  # Limit to 20
        print(f"{i}. {row['artist']} - {row['album']} - {row['album_artist'] or '(empty)'} ({row['play_count']} plays)")

    if len(rows) > 20:
        print(f"\n... and {len(rows) - 20} more")


def print_album_artist_variations(issues: list):
    """Print albums with album_artist variations."""
    if not issues:
        print("✓ No album_artist variations found.")
        return

    print(f"⚠ Found {len(issues)} albums with album_artist variations:\n")

    for i, issue in enumerate(issues, 1):
        print(f"{i}. {issue['artist']} - {issue['album']}")
        print(f"   Total plays: {issue['total_plays']}")
        print(f"   Variations:")
        for var in issue['variations']:
            artist = var['album_artist'] if var['album_artist'] else "(empty)"
            print(f"     - album_artist: {artist} ({var['play_count']} plays)")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Investigate data quality issues in scrobbles"
    )
    parser.add_argument(
        "--artist",
        help="Filter by specific artist name"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check all artists (without --artist, defaults to all)"
    )

    args = parser.parse_args()

    # Default to all if no artist specified
    check_artist = args.artist if args.artist else None

    print(f"\nInvestigating data quality issues")
    if check_artist:
        print(f"Filtering by artist: {check_artist}")
    print()

    # Track-level MBID variations
    print_section("TRACK-LEVEL ALBUM_MBD VARIATIONS")
    track_issues = investigate_album_mbid_variations(check_artist)
    print_track_mbid_issues(track_issues)

    # Album-level MBID variations
    print_section("ALBUM-LEVEL ALBUM_MBD VARIATIONS")
    album_issues = investigate_album_mbid_variations_by_album(check_artist)
    print_album_mbid_issues(album_issues)

    # Empty album_artist
    print_section("EMPTY ALBUM_ARTIST")
    empty_artist = investigate_empty_album_artist(check_artist)
    print_empty_album_artist(empty_artist)

    # Album artist variations
    print_section("ALBUM_ARTIST VARIATIONS")
    artist_variations = investigate_inconsistent_album_artist(check_artist)
    print_album_artist_variations(artist_variations)

    # Summary
    print_section("SUMMARY")
    total_issues = (
        len(track_issues) +
        len(album_issues) +
        len(empty_artist) +
        len(artist_variations)
    )
    print(f"Total issues found: {total_issues}")
    if total_issues == 0:
        print("✓ No data quality issues detected!")


if __name__ == "__main__":
    main()
