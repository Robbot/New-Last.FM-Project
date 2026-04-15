#!/usr/bin/env python3
"""
Fetch album tracklists from MusicBrainz API with reliable MBIDs.

MusicBrainz is the authoritative source for MBIDs and provides
more consistent track metadata than Last.fm.

Usage:
    python -m app.services.fetch_tracklist_musicbrainz "Artist" "Album"
"""

import logging
import requests
import time
from app.logging_config import get_logger
from app.db.connections import get_db_connection
from app.db.albums import upsert_album_tracks

logger = get_logger(__name__)
MUSICBRAINZ_API_BASE = "https://musicbrainz.org/ws/2"
USER_AGENT = "LastFMStats/1.0 (https://github.com/yourusername/lastfmstats)"


def fetch_album_tracklist_musicbrainz(artist_name: str, album_name: str) -> list[dict] | None:
    """
    Fetch album tracklist from MusicBrainz API.

    Returns list of dicts with keys: artist, track, track_number, track_mbid
    Returns None if not found or on error.
    """
    # First, search for the release
    search_url = f"{MUSICBRAINZ_API_BASE}/release/"
    params = {
        "query": f'artist:"{artist_name}" AND release:"{album_name}"',
        "fmt": "json",
        "limit": 10
    }
    headers = {"User-Agent": USER_AGENT}

    try:
        response = requests.get(search_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if not data.get("releases"):
            logger.warning(f"No MusicBrainz release found for {artist_name} - {album_name}")
            return None

        # Get the first release's MBID
        release_mbid = data["releases"][0]["id"]

        # Fetch the release with tracklist
        release_url = f"{MUSICBRAINZ_API_BASE}/release/{release_mbid}"
        params = {"inc": "recordings", "fmt": "json"}

        time.sleep(1)  # MusicBrainz requires 1 second between requests
        response = requests.get(release_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        release_data = response.json()

        # Extract tracklist
        from app.services.sync_lastfm import clean_title

        tracks = []
        for medium in release_data.get("media", []):
            for track in medium.get("tracks", []):
                # Apply title cleaning to ensure consistent capitalization
                track_name = clean_title(track["recording"]["title"], artist_name, album_name)
                tracks.append({
                    "artist": artist_name,
                    "track": track_name,
                    "track_number": track["number"],
                    "track_mbid": track["recording"]["id"]
                })

        logger.info(f"Fetched {len(tracks)} tracks from MusicBrainz for {artist_name} - {album_name}")
        return tracks

    except requests.RequestException as e:
        logger.error(f"Failed to fetch from MusicBrainz: {e}")
        return None


def fetch_and_store_tracklist(artist_name: str, album_name: str) -> bool:
    """
    Fetch tracklist from MusicBrainz and store in database.

    Returns True if successful, False otherwise.
    """
    tracks = fetch_album_tracklist_musicbrainz(artist_name, album_name)
    if tracks:
        upsert_album_tracks(artist_name, album_name, tracks)
        return True
    return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fetch album tracklist from MusicBrainz')
    parser.add_argument('artist', help='Artist name')
    parser.add_argument('album', help='Album name')

    args = parser.parse_args()

    if fetch_and_store_tracklist(args.artist, args.album):
        print(f"Successfully fetched and stored tracklist for {args.artist} - {args.album}")
    else:
        print(f"Failed to fetch tracklist for {args.artist} - {args.album}")


if __name__ == "__main__":
    main()
