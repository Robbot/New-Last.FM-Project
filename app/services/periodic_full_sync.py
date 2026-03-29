#!/usr/bin/env python3
"""
Periodic full re-sync to catch gaps in scrobble data.

This script performs a comprehensive scan of the entire date range
from the first scrobble to now, checking for gaps and inconsistencies.
Runs daily at 5 AM to ensure data integrity.

Run manually: python -m app.services.periodic_full_sync
"""
import time
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
import requests

# Add parent directory to path for imports
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.config import get_api_key
from app.services.sync_lastfm import clean_title, ensure_schema
from app.db.notifications import create_notification
from app.logging_config import setup_logging
from app.logging_config import get_logger

# Setup logging
setup_logging()
logger = logging.getLogger(__name__)

# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

# Gap detection threshold (in seconds)
# Gaps larger than this are considered worth investigating
GAP_THRESHOLD_SECONDS = 2 * 60 * 60  # 2 hours

# Auto-insert missing scrobbles (set to False to only report)
AUTO_INSERT_MISSING = True


def get_conn():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_first_last_uts(conn):
    """Get the first and last scrobble timestamps from the database."""
    cur = conn.cursor()
    cur.execute("SELECT MIN(uts) as min_uts, MAX(uts) as max_uts FROM scrobble")
    result = cur.fetchone()
    return result["min_uts"], result["max_uts"]


def fetch_recent_tracks(api_key, username, from_ts, to_ts, page=1, limit=200):
    """Fetch recent tracks from Last.fm API for a time range."""
    params = {
        "method": "user.getRecentTracks",
        "user": username,
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "page": page,
    }
    if from_ts is not None:
        params["from"] = int(from_ts)
    if to_ts is not None:
        params["to"] = int(to_ts)

    response = requests.get(BASE_URL, params=params, timeout=15)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        logger.error(f"Last.fm API error {data['error']}: {data.get('message')}")
        raise RuntimeError(f"Last.fm API error {data['error']}: {data.get('message')}")

    return data


def detect_gaps_in_database(conn):
    """
    Scan database for gaps in scrobble timestamps.

    Returns a list of gaps detected, where each gap is a dict with:
    - start: timestamp of the scrobble before the gap
    - end: timestamp of the scrobble after the gap
    - gap_seconds: size of the gap in seconds
    """
    cur = conn.cursor()
    cur.execute("""
        SELECT uts, LAG(uts) OVER (ORDER BY uts) as prev_uts
        FROM scrobble
        ORDER BY uts DESC
        LIMIT 10000
    """)

    gaps = []
    for row in cur.fetchall():
        current_uts = row["uts"]
        prev_uts = row["prev_uts"]

        if prev_uts is None:
            continue

        gap = current_uts - prev_uts
        # Look for gaps larger than threshold (note: we're going backwards, so gap is negative)
        if abs(gap) > GAP_THRESHOLD_SECONDS:
            gaps.append({
                "start": min(current_uts, prev_uts),
                "end": max(current_uts, prev_uts),
                "gap_seconds": abs(gap)
            })

    return gaps


def check_time_range_against_lastfm(api_key, username, start_ts, end_ts):
    """
    Check a specific time range against Last.fm API to find missing scrobbles.

    Returns:
        - found_in_db: set of (uts, artist, album, track) tuples found in database
        - found_in_lastfm: set of (uts, artist, album, track) tuples from Last.fm
        - missing: list of scrobbles in Last.fm but not in database
    """
    conn = get_conn()
    cur = conn.cursor()

    # Get scrobbles from database in this range
    cur.execute("""
        SELECT uts, artist, album, track
        FROM scrobble
        WHERE uts >= ? AND uts <= ?
    """, (start_ts, end_ts))

    found_in_db = set()
    for row in cur.fetchall():
        found_in_db.add((row["uts"], row["artist"], row["album"], row["track"]))

    # Get scrobbles from Last.fm in this range
    page = 1
    found_in_lastfm = set()

    while True:
        data = fetch_recent_tracks(api_key, username, start_ts, end_ts, page)
        recent = data.get("recenttracks", {})
        tracks = recent.get("track", [])

        if not tracks:
            break

        for t in tracks:
            # Skip "now playing"
            if "@attr" in t and t["@attr"].get("nowplaying") == "true":
                continue

            date_info = t.get("date")
            if not date_info:
                continue

            uts = int(date_info["uts"])
            artist_name = t["artist"]["#text"]

            if isinstance(t.get("album"), dict):
                album_name = clean_title(t["album"]["#text"])
            else:
                album_name = clean_title(t.get("album", ""))

            track_name = clean_title(t["name"])

            found_in_lastfm.add((uts, artist_name, album_name, track_name))

        # Check pagination
        attr = recent.get("@attr", {})
        total_pages = int(attr.get("totalPages", page))

        if page >= total_pages:
            break

        page += 1
        time.sleep(0.25)

    conn.close()

    # Find missing scrobbles
    missing = found_in_lastfm - found_in_db

    return found_in_db, found_in_lastfm, missing


def run_full_gap_check():
    """
    Perform a full gap check across the entire date range.

    This is designed to run periodically (e.g., daily at 5 AM) to catch
    any data gaps that may have occurred due to sync failures, database issues,
    or other problems.
    """
    api_key, username = get_api_key()
    logger.info(f"Starting periodic full gap check for user: {username}")

    conn = get_conn()

    # Get the date range
    first_uts, last_uts = get_first_last_uts(conn)

    if first_uts is None or first_uts == 0:
        logger.info("No scrobbles in database yet, skipping gap check")
        conn.close()
        return

    logger.info(f"Date range: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(first_uts))} to "
                f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(last_uts))} UTC")

    # Detect gaps in the database
    logger.info("Scanning for gaps in database...")
    gaps = detect_gaps_in_database(conn)
    conn.close()

    if not gaps:
        logger.info("No significant gaps detected in database")
        create_notification(
            notification_type='sync_check',
            title='Periodic gap check completed',
            message='Full gap check completed successfully. No significant gaps detected.',
            severity='info'
        )
        return

    logger.info(f"Found {len(gaps)} potential gaps")

    # Check gaps against Last.fm API
    total_missing_found = 0
    all_missing_scrobbles = []  # Track all missing scrobbles for notification
    checked_gaps = 0
    max_gaps_to_check = 10  # Limit API calls to avoid rate limiting

    for gap in gaps[:max_gaps_to_check]:
        checked_gaps += 1
        gap_start = gap["start"]
        gap_end = gap["end"]

        logger.info(f"Checking gap from {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(gap_start))} to "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(gap_end))} "
                   f"({gap['gap_seconds'] / 3600:.1f} hours)")

        try:
            _, _, missing = check_time_range_against_lastfm(
                api_key, username, gap_start, gap_end
            )

            if missing:
                total_missing_found += len(missing)
                logger.warning(f"Found {len(missing)} missing scrobble(s) in this gap")

                # Log detailed information for each missing scrobble
                for uts, artist, album, track in sorted(missing):
                    timestamp_str = time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime(uts))
                    logger.info(f"  MISSING: [{timestamp_str}] {artist} - {track} (album: {album})")
                    # Add to list for notification
                    all_missing_scrobbles.append({
                        'uts': uts,
                        'timestamp': timestamp_str,
                        'artist': artist,
                        'album': album,
                        'track': track
                    })

                # Insert missing scrobbles if auto-insert is enabled
                if AUTO_INSERT_MISSING:
                    conn = get_conn()
                    inserted = 0

                    for uts, artist, album, track in missing:
                        try:
                            cur = conn.cursor()
                            cur.execute(
                                """
                                INSERT OR IGNORE INTO scrobble
                                (artist, album, track, uts, album_artist)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (artist, album, track, uts, artist)
                            )
                            if cur.rowcount > 0:
                                inserted += 1
                        except sqlite3.Error as e:
                            logger.error(f"Error inserting scrobble: {e}")

                    conn.commit()
                    conn.close()

                    if inserted > 0:
                        logger.info(f"Inserted {inserted} missing scrobble(s) into database")
                else:
                    logger.info(f"Auto-insert disabled. {len(missing)} scrobble(s) reported but not inserted.")

        except Exception as e:
            logger.error(f"Error checking gap: {e}", exc_info=True)

    # Create notification with results
    if total_missing_found > 0:
        if AUTO_INSERT_MISSING:
            title = f'Found and filled {total_missing_found} missing scrobble(s)'
            message = f'Periodic full gap check found {total_missing_found} scrobbles that were missing. ' \
                     f'These have been automatically inserted. Checked {checked_gaps} of {len(gaps)} gaps detected.'
        else:
            title = f'Found {total_missing_found} missing scrobble(s) - Review Required'
            message = f'Periodic full gap check found {total_missing_found} scrobbles that are missing from the database. ' \
                     f'Please review and manually insert if needed. Checked {checked_gaps} of {len(gaps)} gaps detected.'

        create_notification(
            notification_type='data_gap',
            title=title,
            message=message,
            details={
                'gaps_detected': len(gaps),
                'gaps_checked': checked_gaps,
                'missing_found': total_missing_found,
                'auto_insert_enabled': AUTO_INSERT_MISSING,
                'missing_scrobbles': all_missing_scrobbles
            },
            severity='warning'
        )
        logger.info(f"Gap check complete: found {total_missing_found} missing scrobble(s)")
    else:
        create_notification(
            notification_type='sync_check',
            title=f'Gap check completed: {len(gaps)} gaps checked',
            message=f'Checked {checked_gaps} gap(s) from {len(gaps)} detected. No missing scrobbles found.',
            details={
                'gaps_detected': len(gaps),
                'gaps_checked': checked_gaps
            },
            severity='info'
        )
        logger.info(f"Gap check complete: {checked_gaps} gaps checked, no missing scrobbles found")


def main():
    """Main entry point."""
    try:
        run_full_gap_check()
        logger.info("Periodic full gap check finished successfully.")
    except Exception as exc:
        logger.error(f"Periodic full gap check failed: {exc}", exc_info=True)
        create_notification(
            notification_type='sync_error',
            title='Periodic gap check failed',
            message=f'The periodic full gap check encountered an error: {str(exc)}',
            severity='error'
        )
        raise


if __name__ == "__main__":
    main()
