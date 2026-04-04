#!/usr/bin/env python3
"""
Import scrobbles from CSV file into SQLite database.

CSV format: Artist,Album,Title,date (YYYY-MM-DD HH:MM:SS)

Features:
- Converts datetime to Unix timestamp (UTC)
- Checks timestamp first - skips if ANY scrobble exists at that time
- Saves skipped entries to CSV file for future reference
- Applies same data cleaning as sync_lastfm.py
- Sets source='csv_import' for traceability
- Progress logging every 1000 records

Note: Skips entire rows if timestamp exists in database, regardless of
artist/album/track differences. This prevents duplicates from data variations
like "The Artist" vs "Artist".
"""

import csv
import sqlite3
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Import cleaning functions from sync_lastfm
from .sync_lastfm import (
    clean_title,
    clean_remastered_suffix,
    _fix_small_words_case,
    get_conn,
    DB_PATH
)

from app.logging_config import setup_logging
from app.db.notifications import create_notification

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)


def parse_datetime_to_uts(date_str: str) -> Optional[int]:
    """
    Parse datetime string to Unix timestamp in seconds.

    Args:
        date_str: Date string in format "YYYY-MM-DD HH:MM:SS"

    Returns:
        Unix timestamp as integer, or None if parsing fails

    Note:
        The CSV timestamps are assumed to be in UTC (as exported from Last.fm).
        We explicitly set timezone to UTC to avoid system timezone interference.
    """
    try:
        # Parse the datetime string and explicitly set timezone to UTC
        # This avoids issues where the system timezone might be different
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        # Make it timezone-aware as UTC
        dt = dt.replace(tzinfo=timezone.utc)
        # Convert to Unix timestamp
        return int(dt.timestamp())
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse datetime '{date_str}': {e}")
        return None


def import_scrobbles_from_csv(csv_path: Path, batch_size: int = 1000) -> dict:
    """
    Import scrobbles from CSV file into database.

    Args:
        csv_path: Path to CSV file
        batch_size: Number of records to insert per batch

    Returns:
        Dictionary with import statistics
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    logger.info(f"Starting import from: {csv_path}")
    logger.info(f"Batch size: {batch_size}")

    # Create skipped entries file for future reference
    skipped_file = csv_path.parent / f"{csv_path.stem}_skipped.csv"
    skipped_rows = []

    conn = get_conn()
    cur = conn.cursor()

    # Statistics
    stats = {
        "total_rows": 0,
        "inserted": 0,
        "skipped": 0,
        "errors": 0,
        "parse_errors": 0
    }

    # Batch for inserts
    scrobble_batch: list[tuple] = []

    try:
        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            # Use csv module with proper quote handling
            reader = csv.DictReader(f, quotechar='"', delimiter=',', quoting=csv.QUOTE_MINIMAL)

            for row_num, row in enumerate(reader, start=1):  # start=1 because header is row 0
                stats["total_rows"] += 1

                # Extract fields from CSV
                artist = row.get("Artist", "").strip()
                album = row.get("Album", "").strip()
                track = row.get("Title", "").strip()
                date_str = row.get("date", "").strip()

                # Validate required fields
                if not artist or not track or not date_str:
                    logger.warning(f"Row {row_num}: Missing required fields (artist={artist}, track={track}, date={date_str})")
                    stats["errors"] += 1
                    continue

                # Parse datetime to Unix timestamp
                uts = parse_datetime_to_uts(date_str)
                if uts is None:
                    stats["parse_errors"] += 1
                    stats["errors"] += 1
                    continue

                # CRITICAL: Check if ANY scrobble exists at this timestamp
                # If yes, skip entirely regardless of artist/album/track differences
                cur.execute("SELECT COUNT(*) FROM scrobble WHERE uts = ?", (uts,))
                existing_count = cur.fetchone()[0]

                if existing_count > 0:
                    stats["skipped"] += 1
                    # Save skipped row for future reference
                    skipped_rows.append({
                        "Artist": artist,
                        "Album": album,
                        "Title": track,
                        "date": date_str,
                        "reason": f"timestamp_exists ({existing_count} existing scrobble(s) at uts={uts})"
                    })
                    logger.debug(f"Row {row_num}: Skipped due to existing scrobble at uts={uts} ({date_str})")
                    continue

                # Apply data cleaning (same as sync_lastfm.py)
                artist_clean = clean_title(artist)
                album_clean = clean_title(album) if album else None
                track_clean = clean_title(track)

                # Prepare insert tuple
                # Format: (artist, artist_mbid, album, album_mbid, track, track_mbid, uts, album_artist, source)
                scrobble_batch.append((
                    artist_clean,           # artist
                    None,                   # artist_mbid (not available in CSV)
                    album_clean,            # album
                    None,                   # album_mbid (not available in CSV)
                    track_clean,            # track
                    None,                   # track_mbid (not available in CSV)
                    uts,                    # uts (Unix timestamp)
                    artist_clean,           # album_artist (same as artist for CSV import)
                    'csv_import'            # source (identifies these as imported from CSV)
                ))

                # Insert batch when it reaches batch_size
                if len(scrobble_batch) >= batch_size:
                    inserted, skipped = _insert_batch(conn, cur, scrobble_batch, stats["total_rows"])
                    stats["inserted"] += inserted
                    stats["skipped"] += skipped
                    scrobble_batch.clear()

            # Insert any remaining records in the final batch
            if scrobble_batch:
                inserted, skipped = _insert_batch(conn, cur, scrobble_batch, stats["total_rows"])
                stats["inserted"] += inserted
                stats["skipped"] += skipped

        # Write skipped entries to file
        if skipped_rows:
            with open(skipped_file, 'w', encoding='utf-8', newline='') as f:
                fieldnames = ["Artist", "Album", "Title", "date", "reason"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(skipped_rows)
            logger.info(f"Saved {len(skipped_rows)} skipped entries to: {skipped_file}")

    except Exception as e:
        logger.error(f"Error during import: {e}", exc_info=True)
        create_notification(
            notification_type='csv_import_error',
            title='CSV import failed',
            message=f'Error importing scrobbles from CSV: {str(e)}',
            details={'error': str(e), 'stats': stats},
            severity='error'
        )
        raise

    finally:
        conn.close()

    # Log summary
    logger.info("=" * 60)
    logger.info("Import Summary:")
    logger.info(f"  Total rows processed: {stats['total_rows']}")
    logger.info(f"  Successfully inserted: {stats['inserted']}")
    logger.info(f"  Skipped (existing timestamps): {stats['skipped']}")
    logger.info(f"  Errors: {stats['errors']} (parse errors: {stats['parse_errors']})")
    if skipped_rows:
        logger.info(f"  Skipped entries saved to: {skipped_file}")
    logger.info("=" * 60)

    # Create success notification
    create_notification(
        notification_type='csv_import_complete',
        title=f'CSV import complete: {stats["inserted"]} scrobbles added',
        message=f'Imported {stats["inserted"]} scrobbles from CSV. {stats["skipped"]} skipped due to existing timestamps.',
        details=stats,
        severity='info'
    )

    return stats


def _insert_batch(conn: sqlite3.Connection, cur: sqlite3.Cursor, batch: list[tuple], row_num: int) -> tuple[int, int]:
    """
    Insert a batch of scrobbles into the database.

    Args:
        conn: Database connection
        cur: Database cursor
        batch: List of scrobble tuples to insert
        row_num: Current row number (for logging)

    Returns:
        Tuple of (inserted_count, skipped_count)
    """
    try:
        # Sort by timestamp to maintain chronological order
        batch.sort(key=lambda x: x[6])  # x[6] = uts

        # Get the count before insert
        cur.execute("SELECT COUNT(*) FROM scrobble WHERE source = 'csv_import';")
        count_before = cur.fetchone()[0]

        # Use INSERT OR IGNORE to handle duplicates based on unique index
        cur.executemany(
            """
            INSERT OR IGNORE INTO scrobble
                (artist, artist_mbid, album, album_mbid,
                 track, track_mbid, uts, album_artist, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            batch
        )
        conn.commit()

        # Get the count after insert
        cur.execute("SELECT COUNT(*) FROM scrobble WHERE source = 'csv_import';")
        count_after = cur.fetchone()[0]

        inserted = count_after - count_before
        skipped = len(batch) - inserted

        logger.debug(f"Batch inserted at row {row_num}: {inserted} new, {skipped} skipped (batch size {len(batch)})")

        return inserted, skipped

    except sqlite3.Error as e:
        logger.error(f"Database error inserting batch at row {row_num}: {e}")
        conn.rollback()
        raise


def import_scrobbles_from_csv_safe(csv_path: str) -> dict:
    """
    Safe wrapper for import_scrobbles_from_csv with error handling.

    Args:
        csv_path: Path to CSV file (as string)

    Returns:
        Dictionary with import statistics
    """
    csv_path = Path(csv_path)

    if not csv_path.exists():
        logger.error(f"CSV file not found: {csv_path}")
        return {"error": "File not found", "total_rows": 0, "inserted": 0, "skipped": 0}

    try:
        return import_scrobbles_from_csv(csv_path)
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        return {"error": str(e), "total_rows": 0, "inserted": 0, "skipped": 0}


# ---------- CLI entry point ----------

if __name__ == "__main__":
    import sys

    # Parse arguments
    args = [arg for arg in sys.argv[1:] if arg not in ("--dry-run", "-n")]
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    # Default CSV path
    csv_file = args[0] if args else "scrobbles_gaps.csv"

    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made to the database")
        logger.info(f"Would import from: {csv_file}")

        # Just analyze the CSV
        csv_path = Path(csv_file)
        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            sys.exit(1)

        with open(csv_path, 'r', encoding='utf-8', errors='replace') as f:
            reader = csv.DictReader(f)
            row_count = sum(1 for _ in reader)

        logger.info(f"Total records in CSV: {row_count}")
        logger.info("Run without --dry-run to actually import the data.")
        sys.exit(0)

    logger.info(f"Starting CSV import from: {csv_file}")
    logger.info("Press Ctrl+C to abort...")

    try:
        stats = import_scrobbles_from_csv_safe(csv_file)
        logger.info("Import finished successfully.")

        # Print summary
        print("\n" + "=" * 60)
        print("IMPORT SUMMARY")
        print("=" * 60)
        print(f"Total rows processed: {stats.get('total_rows', 0)}")
        print(f"Successfully inserted: {stats.get('inserted', 0)}")
        print(f"Skipped (duplicates): {stats.get('skipped', 0)}")
        print(f"Errors: {stats.get('errors', 0)}")
        print("=" * 60)

    except KeyboardInterrupt:
        logger.info("Import aborted by user.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        sys.exit(1)
