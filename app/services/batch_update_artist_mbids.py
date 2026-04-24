"""
Batch update artist and album MBIDs for all entries in the database.

Fetches MBIDs from MusicBrainz API for artists and albums that don't have them
and updates the database in batches.

When an artist MBID is found, also attempts to find and add album MBIDs
for all albums by that artist.
"""
import logging
import sys
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.fetch_artist_mbid import fetch_artist_mbid, fetch_album_mbid, MB_SLEEP_SECONDS
import time

logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).resolve().parent.parent.parent / "files" / "lastfmstats.sqlite"


def get_artists_without_mbid() -> List[str]:
    """
    Get all distinct artists from the database that don't have an MBID.

    Returns:
        List of artist names without MBIDs, sorted by play count (descending)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get artists without MBID, sorted by play count
        query = """
            SELECT artist, COUNT(*) as play_count
            FROM scrobble
            WHERE artist_mbid IS NULL OR artist_mbid = ''
            GROUP BY artist
            ORDER BY play_count DESC
        """

        cursor.execute(query)
        rows = cursor.fetchall()

        artists = [row["artist"] for row in rows]
        conn.close()

        logger.info(f"Found {len(artists)} artists without MBID")
        return artists

    except sqlite3.Error as e:
        logger.error(f"Database error getting artists without MBID: {e}")
        return []


def update_artist_mbid(artist_name: str, mbid: str) -> bool:
    """
    Update all scrobbles for an artist with their MBID.

    Args:
        artist_name: Name of the artist
        mbid: MusicBrainz ID to set

    Returns:
        True if update was successful, False otherwise
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE scrobble SET artist_mbid = ? WHERE artist = ?",
            (mbid, artist_name)
        )

        conn.commit()
        rows_updated = cursor.rowcount
        conn.close()

        logger.info(f"Updated {rows_updated} scrobbles for '{artist_name}' with MBID {mbid}")
        return True

    except sqlite3.Error as e:
        logger.error(f"Database error updating MBID for '{artist_name}': {e}")
        return False


def get_albums_without_mbid(artist_name: Optional[str] = None) -> List[tuple]:
    """
    Get all distinct albums from the database that don't have an album MBID.

    Args:
        artist_name: If provided, only return albums for this artist

    Returns:
        List of (artist, album) tuples without MBIDs, sorted by play count (descending)
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get albums without MBID, sorted by play count
        if artist_name:
            query = """
                SELECT artist, album, COUNT(*) as play_count
                FROM scrobble
                WHERE artist = ? AND (album_mbid IS NULL OR album_mbid = '')
                GROUP BY artist, album
                ORDER BY play_count DESC
            """
            cursor.execute(query, (artist_name,))
        else:
            query = """
                SELECT artist, album, COUNT(*) as play_count
                FROM scrobble
                WHERE album_mbid IS NULL OR album_mbid = ''
                GROUP BY artist, album
                ORDER BY play_count DESC
            """
            cursor.execute(query)

        rows = cursor.fetchall()
        albums = [(row["artist"], row["album"]) for row in rows]
        conn.close()

        logger.info(f"Found {len(albums)} albums without MBID" + (f" for artist '{artist_name}'" if artist_name else ""))
        return albums

    except sqlite3.Error as e:
        logger.error(f"Database error getting albums without MBID: {e}")
        return []


def update_album_mbid(artist_name: str, album_name: str, mbid: str) -> bool:
    """
    Update all scrobbles for an album with their MBID.

    Args:
        artist_name: Name of the artist
        album_name: Name of the album
        mbid: MusicBrainz ID to set

    Returns:
        True if update was successful, False otherwise
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute(
            "UPDATE scrobble SET album_mbid = ? WHERE artist = ? AND album = ?",
            (mbid, artist_name, album_name)
        )

        conn.commit()
        rows_updated = cursor.rowcount
        conn.close()

        logger.info(f"Updated {rows_updated} scrobbles for '{artist_name} - {album_name}' with album MBID {mbid}")
        return True

    except sqlite3.Error as e:
        logger.error(f"Database error updating album MBID for '{artist_name} - {album_name}': {e}")
        return False


def update_albums_for_artist(artist_name: str, artist_mbid: str, dry_run: bool = False) -> dict:
    """
    Update MBIDs for all albums by an artist.

    Args:
        artist_name: Name of the artist
        artist_mbid: MusicBrainz artist ID (improves album lookup accuracy)
        dry_run: If True, don't actually update the database

    Returns:
        Dict with results: found, updated, not_found, errors
    """
    albums = get_albums_without_mbid(artist_name)

    results = {
        "found": 0,
        "updated": 0,
        "not_found": 0,
        "errors": 0,
    }

    for album_name in albums:
        album_title = album_name[1]
        try:
            album_mbid = fetch_album_mbid(artist_name, album_title, artist_mbid)
            if album_mbid:
                if not dry_run:
                    success = update_album_mbid(artist_name, album_title, album_mbid)
                    if success:
                        results["updated"] += 1
                        results["found"] += 1
                    else:
                        results["errors"] += 1
                else:
                    results["found"] += 1
            else:
                results["not_found"] += 1

        except Exception as e:
            logger.error(f"Error processing album '{artist_name} - {album_title}': {e}")
            results["errors"] += 1

    return results


def batch_update_all_artist_mbids(limit: Optional[int] = None, dry_run: bool = False, include_albums: bool = True):
    """
    Batch update MBIDs for all artists that don't have them.

    Args:
        limit: Maximum number of artists to update (None for all)
        dry_run: If True, don't actually update the database
        include_albums: If True, also fetch and update album MBIDs for each artist
    """
    artists = get_artists_without_mbid()

    if limit:
        artists = artists[:limit]

    if not artists:
        print("No artists found without MBIDs!")
        return

    total = len(artists)
    print(f"\n{'='*60}")
    print(f"Batch updating MBIDs for {total} artists")
    if dry_run:
        print("DRY RUN MODE - No changes will be made")
    if include_albums:
        print("Will also update album MBIDs for each artist")
    print(f"{'='*60}\n")

    results = {
        "artists_found": 0,
        "artists_updated": 0,
        "artists_not_found": 0,
        "artists_errors": 0,
        "albums_found": 0,
        "albums_updated": 0,
        "albums_not_found": 0,
        "albums_errors": 0,
    }

    for i, artist in enumerate(artists, 1):
        print(f"[{i}/{total}] Looking up '{artist}'...", end=" ")

        if dry_run:
            mbid = fetch_artist_mbid(artist)
            if mbid:
                print(f"✓ Found: {mbid} (would update)")
                results["artists_found"] += 1

                # Also check for albums
                if include_albums:
                    albums = get_albums_without_mbid(artist)
                    if albums:
                        print(f"\n  → Checking {len(albums)} albums...")
                        album_results = update_albums_for_artist(artist, mbid, dry_run=True)
                        results["albums_found"] += album_results["found"]
                        results["albums_not_found"] += album_results["not_found"]
                        print(f"  → Albums: {album_results['found']} found, {album_results['not_found']} not found")
            else:
                print("✗ Not found")
                results["artists_not_found"] += 1
        else:
            try:
                mbid = fetch_artist_mbid(artist)
                if mbid:
                    success = update_artist_mbid(artist, mbid)
                    if success:
                        print(f"✓ Updated: {mbid}")
                        results["artists_updated"] += 1
                        results["artists_found"] += 1
                    else:
                        print(f"✗ Error updating database")
                        results["artists_errors"] += 1

                    # Also update albums
                    if include_albums:
                        albums = get_albums_without_mbid(artist)
                        if albums:
                            print(f"  → Updating {len(albums)} albums...")
                            album_results = update_albums_for_artist(artist, mbid, dry_run=False)
                            results["albums_updated"] += album_results["updated"]
                            results["albums_found"] += album_results["found"]
                            results["albums_not_found"] += album_results["not_found"]
                            results["albums_errors"] += album_results["errors"]
                            print(f"  → Albums: {album_results['updated']} updated, {album_results['not_found']} not found")
                else:
                    print("✗ Not found on MusicBrainz")
                    results["artists_not_found"] += 1

            except Exception as e:
                print(f"✗ Error: {e}")
                results["artists_errors"] += 1

        # Sleep to respect MusicBrainz rate limiting
        if i < total:
            time.sleep(MB_SLEEP_SECONDS)

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Artists:")
    print(f"  Total processed: {total}")
    print(f"  MBIDs found: {results['artists_found']}")
    if dry_run:
        print(f"  Would update: {results['artists_found']}")
    else:
        print(f"  Successfully updated: {results['artists_updated']}")
    print(f"  Not found: {results['artists_not_found']}")
    print(f"  Errors: {results['artists_errors']}")

    if include_albums:
        print(f"\nAlbums:")
        print(f"  MBIDs found: {results['albums_found']}")
        if dry_run:
            print(f"  Would update: {results['albums_found']}")
        else:
            print(f"  Successfully updated: {results['albums_updated']}")
        print(f"  Not found: {results['albums_not_found']}")
        print(f"  Errors: {results['albums_errors']}")
    print(f"{'='*60}\n")


def update_single_artist(artist_name: str, dry_run: bool = False, include_albums: bool = True):
    """
    Update MBID for a single artist and optionally their albums.

    Args:
        artist_name: Name of the artist to update
        dry_run: If True, don't actually update the database
        include_albums: If True, also update album MBIDs for this artist
    """
    print(f"Looking up MBID for '{artist_name}'...")

    mbid = fetch_artist_mbid(artist_name)

    if mbid:
        print(f"✓ Found MBID: {mbid}")

        if not dry_run:
            success = update_artist_mbid(artist_name, mbid)
            if success:
                # Verify the update
                conn = sqlite3.connect(DB_PATH)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM scrobble WHERE artist = ? AND artist_mbid = ?",
                    (artist_name, mbid)
                )
                count = cursor.fetchone()[0]
                conn.close()
                print(f"✓ Successfully updated {count} scrobbles")
            else:
                print("✗ Failed to update database")
        else:
            print(f"(would update artist scrobbles)")

        # Also update albums
        if include_albums:
            albums = get_albums_without_mbid(artist_name)
            if albums:
                print(f"\nChecking {len(albums)} albums without MBID...")
                album_results = update_albums_for_artist(artist_name, mbid, dry_run=dry_run)
                print(f"\nAlbum results:")
                print(f"  Found: {album_results['found']}")
                if not dry_run:
                    print(f"  Updated: {album_results['updated']}")
                print(f"  Not found: {album_results['not_found']}")
                if album_results['errors'] > 0:
                    print(f"  Errors: {album_results['errors']}")
            else:
                print("\nNo albums found without MBID for this artist")
    else:
        print("✗ MBID not found on MusicBrainz")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Batch update artist and album MBIDs from MusicBrainz")
    parser.add_argument("--artist", "-a", help="Update a single artist by name")
    parser.add_argument("--limit", "-l", type=int, help="Limit number of artists to update")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Don't actually update database")
    parser.add_argument("--no-albums", action="store_true", help="Don't update album MBIDs (only artist MBIDs)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    include_albums = not args.no_albums

    if args.artist:
        update_single_artist(args.artist, dry_run=args.dry_run, include_albums=include_albums)
    else:
        batch_update_all_artist_mbids(limit=args.limit, dry_run=args.dry_run, include_albums=include_albums)
