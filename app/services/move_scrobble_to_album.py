#!/usr/bin/env python3
"""
Move scrobbles from one album to another with proper consistency checks.

This service ensures that when moving scrobbles to a different album:
1. The album_mbid is consistent across scrobble, album_art, and album_tracks tables
2. If the target album exists in album_art, its MBID is used
3. album_tracks.album_mbid is updated if needed

Usage:
    python -m app.services.move_scrobble_to_album "Artist" "Track" "New Album"
    python -m app.services.move_scrobble_to_album "Artist" "Track" "New Album" --mbid "xxx-xxx"
"""

import argparse
import logging
import sqlite3
from pathlib import Path
from app.logging_config import get_logger

logger = get_logger(__name__)


def get_db_path() -> str:
    """Get the path to the SQLite database."""
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path.exists():
        return str(db_path)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_db_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def move_scrobble_to_album(
    artist_name: str,
    track_name: str,
    new_album_name: str,
    new_album_mbid: str = None,
    dry_run: bool = False
) -> dict:
    """
    Move a scrobble to a different album with consistency checks.

    Args:
        artist_name: Artist name
        track_name: Track name
        new_album_name: New album name to move to
        new_album_mbid: Optional MusicBrainz ID for the new album
        dry_run: If True, don't actually make changes

    Returns:
        dict with status and details about what was done
    """
    conn = get_db_connection()

    # Find the scrobble(s) to move
    scrobbles = conn.execute(
        """
        SELECT id, artist, album, track, album_mbid
        FROM scrobble
        WHERE artist = ? AND track = ?
        """,
        (artist_name, track_name)
    ).fetchall()

    if not scrobbles:
        conn.close()
        return {"status": "error", "message": f"No scrobble found for {artist_name} - {track_name}"}

    # Check if target album exists in album_art table
    art_row = conn.execute(
        """
        SELECT artist, album, album_mbid
        FROM album_art
        WHERE artist = ? AND album = ?
        LIMIT 1
        """,
        (artist_name, new_album_name)
    ).fetchone()

    # Determine the final MBID to use
    final_mbid = None
    mbid_source = None

    if art_row and art_row["album_mbid"]:
        # Use the MBID from album_art table (most reliable)
        final_mbid = art_row["album_mbid"]
        mbid_source = "album_art table"
    elif new_album_mbid:
        # Use the provided MBID
        final_mbid = new_album_mbid
        mbid_source = "provided parameter"
    else:
        # Try to find MBID from existing scrobbles of the target album
        existing_mbid = conn.execute(
            """
            SELECT album_mbid
            FROM scrobble
            WHERE artist = ? AND album = ? AND album_mbid IS NOT NULL AND album_mbid != ''
            LIMIT 1
            """,
            (artist_name, new_album_name)
        ).fetchone()

        if existing_mbid:
            final_mbid = existing_mbid["album_mbid"]
            mbid_source = "existing scrobbles"

    results = []
    for scrobble in scrobbles:
        old_album = scrobble["album"]
        old_mbid = scrobble["album_mbid"]

        if dry_run:
            logger.info(f"[DRY RUN] Would move scrobble {scrobble['id']}: {artist_name} - {track_name}")
            logger.info(f"  Old album: {old_album} (MBID: {old_mbid})")
            logger.info(f"  New album: {new_album_name} (MBID: {final_mbid} from {mbid_source})")
            results.append({
                "scrobble_id": scrobble["id"],
                "old_album": old_album,
                "new_album": new_album_name,
                "mbid": final_mbid,
                "mbid_source": mbid_source
            })
        else:
            # Update the scrobble
            conn.execute(
                """
                UPDATE scrobble
                SET album = ?, album_mbid = ?
                WHERE id = ?
                """,
                (new_album_name, final_mbid, scrobble["id"])
            )

            # Update album_tracks album_mbid if the tracklist exists
            if final_mbid:
                conn.execute(
                    """
                    UPDATE album_tracks
                    SET album_mbid = ?
                    WHERE artist = ? AND album = ? AND track = ?
                    """,
                    (final_mbid, artist_name, new_album_name, track_name)
                )

            logger.info(f"Moved scrobble {scrobble['id']}: {old_album} -> {new_album_name}")
            results.append({
                "scrobble_id": scrobble["id"],
                "old_album": old_album,
                "new_album": new_album_name,
                "mbid": final_mbid,
                "mbid_source": mbid_source
            })

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "status": "success",
        "moved": len(results),
        "scrobbles": results,
        "album_mbid": final_mbid,
        "mbid_source": mbid_source
    }


def main():
    parser = argparse.ArgumentParser(
        description="Move scrobbles to a different album with consistency checks"
    )
    parser.add_argument("artist", help="Artist name")
    parser.add_argument("track", help="Track name")
    parser.add_argument("album", help="New album name to move to")
    parser.add_argument("--mbid", help="MusicBrainz album ID (optional)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")

    args = parser.parse_args()

    result = move_scrobble_to_album(
        args.artist,
        args.track,
        args.album,
        args.mbid,
        args.dry_run
    )

    if result["status"] == "error":
        print(f"Error: {result['message']}")
        return 1

    if args.dry_run:
        print(f"[DRY RUN] Would move {result['moved']} scrobble(s)")
    else:
        print(f"Successfully moved {result['moved']} scrobble(s)")

    if result.get("album_mbid"):
        print(f"Album MBID: {result['album_mbid']} (from {result['mbid_source']})")

    for scrobble in result.get("scrobbles", []):
        print(f"  {scrobble['old_album']} -> {scrobble['new_album']}")

    return 0


if __name__ == "__main__":
    main()
