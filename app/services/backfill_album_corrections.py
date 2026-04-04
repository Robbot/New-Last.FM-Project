#!/usr/bin/env python3
"""
Backfill script to fix existing album/track mismatches in the database.

Scans for scrobbles where the album name equals the track name (suspicious)
and attempts to find the correct album using various data sources.

Usage:
    python -m app.services.backfill_album_corrections
"""
import sys
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE_DIR))

import sqlite3

from app.services.validate_albums import (
    is_album_name_suspicious,
    validate_and_correct_album,
    log_data_quality_issue,
)
from app.db.artists import get_artist_mbid
from app.logging_config import setup_logging

# Database path
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def get_suspicious_albums(limit: int = None) -> list:
    """
    Find all scrobbles with suspicious album names (album equals track).

    Args:
        limit: Maximum number of suspicious entries to return

    Returns:
        List of tuples (artist, album, track, count, artist_mbid)
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Find scrobbles where album name equals track name (case-insensitive)
        # Group by artist, album, track to count plays
        query = """
            SELECT
                artist,
                album,
                track,
                COUNT(*) as plays,
                (
                    SELECT artist_mbid
                    FROM scrobble s2
                    WHERE s2.artist = s1.artist
                      AND s2.artist_mbid IS NOT NULL
                      AND s2.artist_mbid != ''
                    LIMIT 1
                ) as artist_mbid
            FROM scrobble s1
            GROUP BY artist, album, track
            HAVING LOWER(album) = LOWER(track)
              AND album IS NOT NULL
              AND album != ''
              AND LENGTH(album) > 2
            ORDER BY plays DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

    finally:
        conn.close()


def fix_album_in_database(
    artist: str,
    old_album: str,
    track: str,
    new_album: str
) -> int:
    """
    Update all scrobbles for a given artist/track combination to use the correct album.

    Args:
        artist: The artist name
        old_album: The old (incorrect) album name
        track: The track name
        new_album: The new (correct) album name

    Returns:
        Number of scrobbles updated
    """
    conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE scrobble
            SET album = ?
            WHERE artist = ?
              AND album = ?
              AND track = ?
            """,
            (new_album, artist, old_album, track)
        )
        updated = cursor.rowcount
        conn.commit()
        return updated

    finally:
        conn.close()


def main(limit: int = None, dry_run: bool = False):
    """
    Main backfill function.

    Args:
        limit: Maximum number of suspicious albums to process
        dry_run: If True, only show what would be changed without making changes
    """
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")

    logger.info("Scanning for suspicious albums (album equals track name)...")
    suspicious = get_suspicious_albums(limit)

    if not suspicious:
        logger.info("No suspicious albums found!")
        return

    logger.info(f"Found {len(suspicious)} suspicious album/track combinations")

    stats = {
        "total": len(suspicious),
        "corrected": 0,
        "not_found": 0,
        "skipped": 0,
    }

    for i, item in enumerate(suspicious, 1):
        artist = item["artist"]
        album = item["album"]
        track = item["track"]
        plays = item["plays"]
        artist_mbid = item.get("artist_mbid")

        logger.info(f"[{i}/{len(suspicious)}] Processing: {artist} - {track}")
        artist = item["artist"]
        album = item["album"]
        track = item["track"]
        plays = item["plays"]
        artist_mbid = item.get("artist_mbid")

        # Try to find the correct album
        is_valid, correct_album, confidence = validate_and_correct_album(
            artist, album, track, artist_mbid, auto_correct=False
        )

        if is_valid:
            stats["skipped"] += 1
            continue

        if not correct_album:
            logger.debug(f"No correction found for {artist} - {track} (album: '{album}')")
            stats["not_found"] += 1

            # Still log the issue for manual review
            log_data_quality_issue(
                artist, album, track, None, 0, auto_corrected=False
            )
            continue

        # Found a correction
        if dry_run:
            logger.info(f"[DRY RUN] Would correct: {artist} - {track}")
            logger.info(f"  Old album: '{album}' -> New album: '{correct_album}' ({confidence}% confidence)")
            logger.info(f"  Scrobbles affected: {plays}")
            stats["corrected"] += 1
        else:
            # Actually fix it
            updated = fix_album_in_database(artist, album, track, correct_album)
            logger.info(f"Corrected {updated} scrobbles: {artist} - {track}")
            logger.info(f"  '{album}' -> '{correct_album}' ({confidence}% confidence)")

            # Log the correction
            log_data_quality_issue(
                artist, album, track, correct_album, confidence, auto_corrected=True
            )

            # Clean up album_art if the old album no longer has any scrobbles
            conn = sqlite3.connect(DB_PATH)
            try:
                count = conn.execute(
                    "SELECT COUNT(*) FROM scrobble WHERE artist = ? AND album = ?",
                    (artist, album)
                ).fetchone()[0]

                if count == 0:
                    # Delete from album_art
                    conn.execute(
                        "DELETE FROM album_art WHERE artist = ? AND album = ?",
                        (artist, album)
                    )
                    conn.commit()
                    logger.info(f"  Removed '{album}' from album_art (no remaining scrobbles)")
            finally:
                conn.close()

            stats["corrected"] += 1

    # Summary
    logger.info("\n" + "="*60)
    logger.info("Backfill Summary:")
    logger.info(f"  Total suspicious entries found: {stats['total']}")
    logger.info(f"  Successfully corrected: {stats['corrected']}")
    logger.info(f"  No correction found: {stats['not_found']}")
    logger.info(f"  Skipped (already valid): {stats['skipped']}")
    logger.info("="*60)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Backfill and fix album/track mismatches in the database"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of suspicious albums to process (default: all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without making changes"
    )

    args = parser.parse_args()

    main(limit=args.limit, dry_run=args.dry_run)
