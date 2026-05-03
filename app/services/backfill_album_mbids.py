#!/usr/bin/env python3
"""
Backfill MusicBrainz release MBIDs for albums that don't have them.

This script fetches MBIDs from MusicBrainz API for albums in the database
that are missing MBID data. It respects MusicBrainz's rate limiting (1 req/sec).

Usage:
    python -m app.services.backfill_album_mbids
    python -m app.services.backfill_album_mbids --limit 50
    python -m app.services.backfill_album_mbids --artist "Artist Name"
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import requests

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.logging_config import get_logger
from app.db.connections import get_db_connection

logger = get_logger(__name__)
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "LastFMStats/1.0 (https://github.com/robbot/lastfmstats)"


def fetch_album_mbid_from_musicbrainz(artist_name: str, album_name: str) -> str | None:
    """
    Search MusicBrainz for an album's MBID.

    Args:
        artist_name: Artist name
        album_name: Album name

    Returns:
        MBID string if found, None otherwise
    """
    search_url = f"{MUSICBRAINZ_API_BASE}/release/"
    params = {
        "query": f'artist:"{artist_name}" AND release:"{album_name}"',
        "fmt": "json",
        "limit": 5
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("releases"):
            return None

        # Return the first (best match) release's MBID
        return data["releases"][0]["id"]

    except requests.RequestException as e:
        logger.error(f"Failed to fetch MBID for {artist_name} - {album_name}: {e}")
        return None


def backfill_album_mbids(limit: int = None, artist_filter: str = None, dry_run: bool = False):
    """
    Backfill MBIDs for albums missing them.

    Args:
        limit: Maximum number of albums to process (None = all)
        artist_filter: Only process albums by this artist
        dry_run: If True, don't actually update the database
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get albums that need MBID
    if artist_filter:
        cursor.execute("""
            SELECT DISTINCT at.album, at.artist
            FROM album_tracks at
            WHERE (at.album_mbid IS NULL OR at.album_mbid = '')
              AND at.artist = ?
            ORDER BY at.album
        """, [artist_filter])
    else:
        cursor.execute("""
            SELECT DISTINCT at.album, at.artist
            FROM album_tracks at
            WHERE at.album_mbid IS NULL OR at.album_mbid = ''
            ORDER BY at.album
        """)

    albums = cursor.fetchall()
    total = len(albums)

    if limit:
        albums = albums[:limit]

    print(f"Found {total} albums missing MBID" + (f" (processing {limit})" if limit else ""))
    print(f"Artist filter: {artist_filter or 'None'}")
    print(f"Dry run: {dry_run}")
    logger.info(f"Found {total} albums missing MBID" + (f" (processing {limit})" if limit else ""))
    logger.info(f"Artist filter: {artist_filter or 'None'}")
    logger.info(f"Dry run: {dry_run}")

    if not albums:
        logger.info("No albums to process")
        conn.close()
        return

    # For non-interactive environments, auto-confirm
    import sys
    is_interactive = sys.stdin.isatty()

    if not dry_run and is_interactive:
        response = input(f"Process {len(albums)} albums? (y/n): ")
        if response.lower() != 'y':
            logger.info("Aborted")
            conn.close()
            return
    elif not dry_run:
        print(f"Processing {len(albums)} albums...")

    processed = 0
    found = 0
    failed = 0

    for i, row in enumerate(albums, 1):
        album_name = row['album']
        artist_name = row['artist']

        print(f"[{i}/{len(albums)}] Searching: {artist_name} - {album_name}")
        logger.info(f"[{i}/{len(albums)}] Searching: {artist_name} - {album_name}")

        mbid = fetch_album_mbid_from_musicbrainz(artist_name, album_name)

        if mbid:
            print(f"  ✓ Found MBID: {mbid}")
            logger.info(f"  Found MBID: {mbid}")
            found += 1

            if not dry_run:
                cursor.execute("""
                    UPDATE album_tracks
                    SET album_mbid = ?
                    WHERE album = ?
                      AND (album_mbid IS NULL OR album_mbid = '')
                """, [mbid, album_name])
        else:
            print(f"  ✗ No MBID found")
            logger.warning(f"  No MBID found")
            failed += 1

        processed += 1

        # Commit every 50 albums
        if not dry_run and processed % 50 == 0:
            conn.commit()
            print(f"  → Committed {processed} updates")
            logger.info(f"Committed {processed} updates")

        # Rate limiting: MusicBrainz requires 1 second between requests
        time.sleep(1)

    if not dry_run:
        conn.commit()
        logger.info(f"Final commit completed")

    conn.close()

    print(f"\nSummary:")
    print(f"  Processed: {processed}")
    print(f"  Found: {found}")
    print(f"  Failed: {failed}")
    logger.info(f"Summary:")
    logger.info(f"  Processed: {processed}")
    logger.info(f"  Found: {found}")
    logger.info(f"  Failed: {failed}")


def main():
    parser = argparse.ArgumentParser(
        description='Backfill MusicBrainz MBIDs for albums',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all albums (this will take a long time!)
  python -m app.services.backfill_album_mbids

  # Process first 50 albums
  python -m app.services.backfill_album_mbids --limit 50

  # Process only albums by a specific artist
  python -m app.services.backfill_album_mbids --artist "Radiohead"

  # Dry run (show what would be done without making changes)
  python -m app.services.backfill_album_mbids --dry-run
        """
    )

    parser.add_argument(
        '--limit', '-l',
        type=int,
        help='Maximum number of albums to process (default: all)'
    )
    parser.add_argument(
        '--artist', '-a',
        type=str,
        help='Only process albums by this artist'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be done without making changes'
    )

    args = parser.parse_args()

    backfill_album_mbids(
        limit=args.limit,
        artist_filter=args.artist,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
