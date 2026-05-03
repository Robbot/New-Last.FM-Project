#!/usr/bin/env python3
"""
Fix compilation albums that don't have MBIDs.

This script identifies and fixes scrobbles on compilation albums
that should have album_artist = "Various Artists" but don't,
due to missing album_mbid values.

Uses the same logic as sync_lastfm.py:
1. Pattern matching for known compilation types (soundtracks, OSTs, etc.)
2. Artist count threshold (6+ artists) when no MBID is available
"""
import argparse
import logging
import sqlite3
import re
from pathlib import Path

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.connections import get_db_connection

# Compilation detection patterns (same as sync_lastfm.py)
_COMPILATION_PATTERNS = [
    # Soundtrack patterns (high confidence)
    r'.*Soundtrack.*',
    r'.*OST.*',  # Original Soundtrack
    r'.*Original Motion Picture Soundtrack.*',
    r'.*Motion Picture Soundtrack.*',
    r'.*Music From and Inspired.*',
    r'.*Music from the Motion Picture.*',
    r'.*Score.*',  # Film scores
    # Compilation series
    r'Kuschel Rock\s*\d*',
    r'Kuschelrock\s*\d*',
    r'Bravo Hits\s*\d*',
    r'Now That\'?s What I Call Music',
    r'Now \d+',
    r'Totally \w+',
    # Various Artists indicators
    r'Various Artists',
    r'VA\s*-',
    r'\[VA\]',
    r'^VA\b',
    # Explicit compilation keywords
    r'\bCompilations?\b',
    r'\bAnthology\b',
    r'\bCollection\b',
    r'\bGreatest Hits\b.*Various',  # Various artists greatest hits
    r'\bThe Best\b.*Various',
]


def _matches_compilation_pattern(album: str) -> bool:
    """Check if album name matches known compilation patterns."""
    if not album:
        return False

    for pattern in _COMPILATION_PATTERNS:
        if re.search(pattern, album, re.IGNORECASE):
            return True
    return False


def fix_compilation_albums_dry_run(conn: sqlite3.Connection):
    """Show what would be fixed without making changes."""
    print("\n" + "=" * 80)
    print("  DRY RUN - Compilation Albums Without MBID")
    print("=" * 80 + "\n")

    # 1. Albums matching compilation patterns
    print("1. ALBUMS MATCHING COMPILATION PATTERNS:\n")
    cursor = conn.execute(
        """
        SELECT album, COUNT(DISTINCT artist) as artist_count, COUNT(*) as total_plays
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        GROUP BY album
        ORDER BY total_plays DESC
        """
    )

    pattern_albums = []
    for row in cursor.fetchall():
        album = row["album"]
        if _matches_compilation_pattern(album):
            pattern_albums.append(album)
            print(f"  - {album}")
            print(f"    Artists: {row['artist_count']}, Plays: {row['total_plays']}")

    print(f"\nTotal: {len(pattern_albums)} albums matching patterns\n")

    # 2. Albums with 6+ distinct artists
    print("2. ALBUMS WITH 6+ DISTINCT ARTISTS:\n")
    cursor = conn.execute(
        """
        SELECT album, COUNT(DISTINCT artist) as artist_count, COUNT(*) as total_plays
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        GROUP BY album
        HAVING COUNT(DISTINCT artist) >= 6
        ORDER BY artist_count DESC, total_plays DESC
        LIMIT 20
        """
    )

    high_artist_albums = []
    for row in cursor.fetchall():
        high_artist_albums.append(row["album"])
        print(f"  - {row['album']}")
        print(f"    Artists: {row['artist_count']}, Plays: {row['total_plays']}")

    print(f"\nTotal: {len(high_artist_albums)} albums with 6+ artists (showing top 20)\n")

    # Calculate total scrobbles that would be updated
    cursor = conn.execute(
        """
        SELECT COUNT(*) as total
        FROM scrobble
        WHERE album_mbid IS NULL
          AND album_artist != 'Various Artists'
        """
    )
    total_eligible = cursor.fetchone()["total"]

    print("=" * 80)
    print(f"  SUMMARY")
    print("=" * 80)
    print(f"Total scrobbles eligible for update: {total_eligible}")
    print(f"Albums matching patterns: {len(pattern_albums)}")
    print(f"Albums with 6+ artists: {len(high_artist_albums)} (top 20 shown)")
    print()


def fix_compilation_albums_apply(conn: sqlite3.Connection):
    """Apply fixes for compilation albums without MBIDs."""
    print("\n" + "=" * 80)
    print("  APPLYING FIXES - Compilation Albums Without MBID")
    print("=" * 80 + "\n")

    updated_total = 0

    # 1. Find albums matching compilation patterns
    cursor = conn.execute(
        """
        SELECT DISTINCT album
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        """
    )
    albums_to_check = [row["album"] for row in cursor.fetchall()]

    pattern_albums = []
    for album in albums_to_check:
        if _matches_compilation_pattern(album):
            pattern_albums.append(album)

    # Update albums matching compilation patterns
    if pattern_albums:
        placeholders = ",".join(["?" for _ in pattern_albums])
        cursor = conn.execute(
            f"""
            UPDATE scrobble
            SET album_artist = 'Various Artists'
            WHERE album IN ({placeholders})
              AND album_mbid IS NULL
              AND album_artist != 'Various Artists'
            """,
            pattern_albums,
        )
        updated = cursor.rowcount
        updated_total += updated
        conn.commit()
        print(f"✓ Pattern-based: Updated {updated} scrobbles across {len(pattern_albums)} albums")
        for album in pattern_albums[:10]:  # Show first 10
            cursor = conn.execute(
                "SELECT COUNT(*) FROM scrobble WHERE album = ? AND album_artist = 'Various Artists'", (album,)
            )
            count = cursor.fetchone()[0]
            print(f"  - {album} ({count} plays)")
        if len(pattern_albums) > 10:
            print(f"  ... and {len(pattern_albums) - 10} more")
        print()

    # 2. Find albums with 6+ distinct artists
    cursor = conn.execute(
        """
        SELECT album
        FROM scrobble
        WHERE album IS NOT NULL
          AND album != ''
          AND album_mbid IS NULL
          AND album_artist != 'Various Artists'
        GROUP BY album
        HAVING COUNT(DISTINCT artist) >= 6
        """
    )
    high_artist_albums = [row["album"] for row in cursor.fetchall()]

    # Update albums with high artist count
    if high_artist_albums:
        placeholders = ",".join(["?" for _ in high_artist_albums])
        cursor = conn.execute(
            f"""
            UPDATE scrobble
            SET album_artist = 'Various Artists'
            WHERE album IN ({placeholders})
              AND album_mbid IS NULL
              AND album_artist != 'Various Artists'
            """,
            high_artist_albums,
        )
        updated = cursor.rowcount
        updated_total += updated
        conn.commit()
        print(f"✓ Artist-count-based: Updated {updated} scrobbles across {len(high_artist_albums)} albums")
        for album in high_artist_albums[:10]:  # Show first 10
            cursor = conn.execute(
                "SELECT COUNT(DISTINCT artist) as ac, COUNT(*) as pc FROM scrobble WHERE album = ?", (album,)
            )
            row = cursor.fetchone()
            print(f"  - {album} ({row['ac']} artists, {row['pc']} plays)")
        if len(high_artist_albums) > 10:
            print(f"  ... and {len(high_artist_albums) - 10} more")
        print()

    print("=" * 80)
    print(f"  TOTAL SCROBBLES UPDATED: {updated_total}")
    print("=" * 80)
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Fix compilation albums that don't have MBIDs"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply fixes (default: dry-run mode)"
    )
    parser.add_argument(
        "--artist",
        help="Filter by specific artist name"
    )

    args = parser.parse_args()

    conn = get_db_connection()

    if args.apply:
        print("⚠ WARNING: This will modify your database!")
        confirm = input("Type 'yes' to continue: ")
        if confirm.lower() == 'yes':
            fix_compilation_albums_apply(conn)
        else:
            print("Cancelled.")
    else:
        fix_compilation_albums_dry_run(conn)
        print("\nTo apply these fixes, run with --apply flag:")
        print("  python -m app.services.fix_compilation_albums_no_mbid --apply")

    conn.close()


if __name__ == "__main__":
    main()
