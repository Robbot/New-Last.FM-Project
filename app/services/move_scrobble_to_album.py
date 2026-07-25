#!/usr/bin/env python3
"""
Move scrobbles from one album to another with proper consistency checks.

This service ensures that when moving scrobbles to a different album:
1. The album_mbid is consistent across scrobble, album_art, and album_tracks tables
2. If the target album exists in album_art, its MBID is used
3. album_tracks.album_mbid is updated if needed
4. The canonical album_id (relational rework) is resolved for the target album
   and written to scrobble.album_id / album_tracks.album_id, so album_id-keyed
   reads (album library grouping, album play counts) reflect the move. The
   target album entity is created on demand if it isn't present yet.
5. album_artist is rewritten to the target album's prevailing value (falling
   back to the artist name) so a 'Various Artists' tag carried over from a
   compilation source doesn't split the track in views that GROUP BY
   album_artist (e.g. track-gaps, where it would pin a phantom row to the old
   play date).

Usage:
    python -m app.services.move_scrobble_to_album "Artist" "Track" "New Album"
    python -m app.services.move_scrobble_to_album "Artist" "Track" "New Album" --mbid "xxx-xxx"
"""

import argparse
import logging
import sqlite3
from pathlib import Path
from app.logging_config import get_logger
from app.db.entities import Resolver

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
        SELECT id, artist, album, track, album_mbid, artist_mbid, album_artist, album_id
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

    # Relational rework: resolve the canonical album_id for the target album so
    # reads that key on scrobble.album_id (album library grouping, album play
    # counts) reflect the move. The Resolver creates the album entity + alias
    # if the target album isn't present yet. In dry-run mode those creations are
    # uncommitted and rolled back when the connection closes.
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id(artist_name, scrobbles[0]["artist_mbid"])
    new_album_id = resolver.resolve_album_id(
        artist_id,
        new_album_name,
        final_mbid,
        album_artist_text=scrobbles[0]["album_artist"],
    )

    # Resolve the album_artist to set on the target album so the moved scrobble
    # groups consistently with the album's existing scrobbles. Views like
    # track-gaps GROUP BY album_artist, so a leftover 'Various Artists' carried
    # over from a compilation source would split the track into a phantom row
    # pinned to the old play date. Prefer the target album's prevailing
    # album_artist; fall back to the artist name when the album is new.
    aa_row = conn.execute(
        """
        SELECT album_artist
        FROM scrobble
        WHERE artist = ? AND album = ? AND album_artist IS NOT NULL AND album_artist != ''
        GROUP BY album_artist
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (artist_name, new_album_name)
    ).fetchone()
    final_album_artist = aa_row["album_artist"] if aa_row else artist_name

    results = []
    for scrobble in scrobbles:
        old_album = scrobble["album"]
        old_mbid = scrobble["album_mbid"]
        old_album_id = scrobble["album_id"]
        old_album_artist = scrobble["album_artist"]

        if dry_run:
            logger.info(f"[DRY RUN] Would move scrobble {scrobble['id']}: {artist_name} - {track_name}")
            logger.info(f"  Old album: {old_album} (MBID: {old_mbid}, album_id: {old_album_id}, album_artist: {old_album_artist})")
            logger.info(f"  New album: {new_album_name} (MBID: {final_mbid} from {mbid_source}, album_id: {new_album_id}, album_artist: {final_album_artist})")
            results.append({
                "scrobble_id": scrobble["id"],
                "old_album": old_album,
                "new_album": new_album_name,
                "mbid": final_mbid,
                "mbid_source": mbid_source,
                "old_album_id": old_album_id,
                "new_album_id": new_album_id,
                "old_album_artist": old_album_artist,
                "new_album_artist": final_album_artist
            })
        else:
            # Update the scrobble (album text, album_mbid, canonical album_id,
            # and album_artist — all four together, or the move is partly
            # invisible: a leftover album_artist splits the track in track-gaps)
            conn.execute(
                """
                UPDATE scrobble
                SET album = ?, album_mbid = ?, album_id = ?, album_artist = ?
                WHERE id = ?
                """,
                (new_album_name, final_mbid, new_album_id, final_album_artist, scrobble["id"])
            )

            # Update album_tracks album_mbid/album_id if the tracklist exists
            if final_mbid:
                conn.execute(
                    """
                    UPDATE album_tracks
                    SET album_mbid = ?, album_id = ?
                    WHERE artist = ? AND album = ? AND track = ?
                    """,
                    (final_mbid, new_album_id, artist_name, new_album_name, track_name)
                )

            logger.info(f"Moved scrobble {scrobble['id']}: {old_album} -> {new_album_name}")
            results.append({
                "scrobble_id": scrobble["id"],
                "old_album": old_album,
                "new_album": new_album_name,
                "mbid": final_mbid,
                "mbid_source": mbid_source,
                "old_album_id": old_album_id,
                "new_album_id": new_album_id,
                "old_album_artist": old_album_artist,
                "new_album_artist": final_album_artist
            })

    if not dry_run:
        conn.commit()
    conn.close()

    return {
        "status": "success",
        "moved": len(results),
        "scrobbles": results,
        "album_mbid": final_mbid,
        "mbid_source": mbid_source,
        "album_id": new_album_id
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
    if result.get("album_id"):
        print(f"Album ID: {result['album_id']}")

    for scrobble in result.get("scrobbles", []):
        print(f"  {scrobble['old_album']} -> {scrobble['new_album']}")

    return 0


if __name__ == "__main__":
    main()
