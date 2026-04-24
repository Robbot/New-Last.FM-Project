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
    Fetch album tracklist from MusicBrainz API by searching artist/album.

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
        return _extract_tracks_from_release(release_data, artist_name, album_name)

    except requests.RequestException as e:
        logger.error(f"Failed to fetch from MusicBrainz: {e}")
        return None


def fetch_album_tracklist_by_mbid(album_mbid: str) -> list[dict] | None:
    """
    Fetch album tracklist from MusicBrainz API using release MBID directly.

    Args:
        album_mbid: MusicBrainz release ID (UUID)

    Returns list of dicts with keys: artist, track, track_number, track_mbid
    Returns None if not found or on error.
    """
    if not album_mbid:
        logger.warning("No MBID provided for MusicBrainz tracklist fetch")
        return None

    # Fetch the release with tracklist directly by MBID
    release_url = f"{MUSICBRAINZ_API_BASE}/release/{album_mbid}"
    params = {"inc": "recordings+artist-credits", "fmt": "json"}
    headers = {"User-Agent": USER_AGENT}

    try:
        response = requests.get(release_url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        release_data = response.json()

        # Extract artist name from release data
        artist_name = None
        artist_credits = release_data.get("artist-credit", [])
        if artist_credits:
            artist_name = artist_credits[0].get("name", "Unknown Artist")

        # For Various Artists compilations, track artists will be extracted individually
        album_name = release_data.get("title", "Unknown Album")

        # Extract tracklist
        tracks = _extract_tracks_from_release(release_data, artist_name, album_name)

        logger.info(f"Fetched {len(tracks)} tracks from MusicBrainz for MBID {album_mbid}")
        return tracks

    except requests.RequestException as e:
        logger.error(f"Failed to fetch from MusicBrainz for MBID {album_mbid}: {e}")
        return None


def _extract_tracks_from_release(release_data: dict, artist_name: str | None, album_name: str) -> list[dict]:
    """
    Extract and format tracks from MusicBrainz release data.

    Args:
        release_data: MusicBrainz release JSON data
        artist_name: Album artist name (used as fallback for tracks)
        album_name: Album name (for title cleaning)

    Returns list of dicts with keys: artist, track, track_number, track_mbid
    """
    from app.services.sync_lastfm import clean_title

    tracks = []
    for medium in release_data.get("media", []):
        for track in medium.get("tracks", []):
            # Get track artist from artist-credit (for compilations)
            track_artist = artist_name
            track_credits = track.get("artist-credit", [])
            if track_credits:
                track_artist = track_credits[0].get("name", artist_name or "Unknown Artist")

            # Apply title cleaning to ensure consistent capitalization
            track_name = clean_title(track["recording"]["title"], track_artist, album_name)

            # Extract track number (handle formats like "1", "A1", etc.)
            track_number = track.get("number", "")
            # Try to convert to integer if possible
            try:
                track_number = int(track_number)
            except (ValueError, TypeError):
                pass  # Keep as string if not a simple integer

            tracks.append({
                "artist": track_artist,
                "track": track_name,
                "track_number": track_number,
                "track_mbid": track["recording"]["id"]
            })

    return tracks


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
