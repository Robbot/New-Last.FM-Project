#!/usr/bin/env python3
"""
Populate Ummagumma album data from MusicBrainz.

MusicBrainz Release: https://musicbrainz.org/release/26afa7c0-c203-4edd-8947-bd54613d2603

This script:
1. Updates artist_mbid in album_art table
2. Populates album_tracks table with complete tracklist from MusicBrainz
"""

import sqlite3
import requests
import logging
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"

# MusicBrainz release ID
MB_RELEASE_ID = "26afa7c0-c203-4edd-8947-bd54613d2603"
MB_API_URL = f"https://musicbrainz.org/ws/2/release/{MB_RELEASE_ID}"

# Album info
ARTIST_NAME = "Pink Floyd"
ALBUM_NAME = "Ummagumma"


def fetch_musicbrainz_data():
    """Fetch release data from MusicBrainz API."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "PythonMusicBrainz/1.0 (https://github.com/robbot)"
    }

    params = {
        "inc": "artist-credits+recordings+release-groups"
    }

    logger.info(f"Fetching data from MusicBrainz: {MB_API_URL}")
    response = requests.get(MB_API_URL, headers=headers, params=params)
    response.raise_for_status()

    return response.json()


def update_album_art(conn, mb_data):
    """Update artist_mbid in album_art table."""
    cursor = conn.cursor()

    artist_mbid = mb_data["artist-credit"][0]["artist"]["id"]
    release_mbid = mb_data["id"]

    logger.info(f"Updating album_art: artist_mbid = {artist_mbid}")

    cursor.execute(
        """
        UPDATE album_art
        SET artist_mbid = ?
        WHERE artist = ? AND album = ? AND album_mbid = ?
        """,
        (artist_mbid, ARTIST_NAME, ALBUM_NAME, release_mbid)
    )

    if cursor.rowcount > 0:
        logger.info(f"  Updated {cursor.rowcount} row(s)")
    else:
        logger.warning("  No rows updated - entry not found")


def populate_album_tracks(conn, mb_data):
    """Populate album_tracks table with MusicBrainz tracklist."""
    cursor = conn.cursor()

    # First, clear existing tracks for this album
    cursor.execute(
        "DELETE FROM album_tracks WHERE artist = ? AND album = ?",
        (ARTIST_NAME, ALBUM_NAME)
    )
    logger.info(f"Cleared {cursor.rowcount} existing track entries")

    # Insert tracks from MusicBrainz
    tracks_inserted = 0
    for medium in mb_data.get("media", []):
        disc_number = medium["position"]
        medium_format = medium.get("format", "CD")

        for track in medium.get("tracks", []):
            track_number = track["number"]
            track_name = track["title"]
            recording_mbid = track.get("recording", {}).get("id", "")
            position = track.get("position", 0)

            # Calculate overall track number across discs
            # For a 2-disc album: disc 1 tracks 1-4, disc 2 tracks 5-16
            overall_track_number = position

            cursor.execute(
                """
                INSERT INTO album_tracks
                (artist, album, track, track_number)
                VALUES (?, ?, ?, ?)
                """,
                (ARTIST_NAME, ALBUM_NAME, track_name, overall_track_number)
            )
            tracks_inserted += 1

    logger.info(f"Inserted {tracks_inserted} tracks from MusicBrainz")

    # Show the inserted tracks
    cursor.execute(
        """
        SELECT track_number, track
        FROM album_tracks
        WHERE artist = ? AND album = ?
        ORDER BY track_number
        """,
        (ARTIST_NAME, ALBUM_NAME)
    )

    logger.info("\n=== Tracklist ===")
    for row in cursor.fetchall():
        track_num, track_name = row
        logger.info(f"  {track_num}. {track_name}")


def main():
    """Run the MusicBrainz data population."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return 1

    logger.info(f"Opening database: {DB_PATH}")

    # Fetch MusicBrainz data
    mb_data = fetch_musicbrainz_data()

    # Update database
    with sqlite3.connect(DB_PATH) as conn:
        update_album_art(conn, mb_data)
        populate_album_tracks(conn, mb_data)
        conn.commit()

    logger.info("\n=== Summary ===")
    logger.info(f"Release: {mb_data['title']} ({mb_data['date']})")
    logger.info(f"Release MBID: {mb_data['id']}")
    logger.info(f"Release Group MBID: {mb_data['release-group']['id']}")
    logger.info(f"Artist MBID: {mb_data['artist-credit'][0]['artist']['id']}")

    return 0


if __name__ == "__main__":
    exit(main())
