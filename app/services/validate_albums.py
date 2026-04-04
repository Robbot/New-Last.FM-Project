"""
Album validation service for detecting and fixing album/track mismatches.

This service helps ensure data quality by:
1. Detecting when album names match track names (suspicious)
2. Looking up the correct album from existing data or MusicBrainz
3. Auto-correcting when confidence is high
4. Tracking issues for manual review
"""
import logging
import re
from typing import Optional, Tuple, List
from datetime import datetime

import requests

from .config import get_api_key
from .fetch_musicbrainz_releases import fetch_artist_releases_from_musicbrainz
from app.db.connections import _normalize_for_matching

logger = logging.getLogger(__name__)

# Last.fm API settings
LF_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
LF_TIMEOUT = 10


def is_album_name_suspicious(album: str, track: str, artist: str) -> bool:
    """
    Check if the album name is suspicious (likely a track name instead).

    Suspicious patterns:
    - Album name equals track name (exact match, case-insensitive)
    - Album name is just the track name with "- Single" or similar suffixes
    - Album is very short (< 4 chars)

    Args:
        album: The album name from scrobble
        track: The track name from scrobble
        artist: The artist name (for context)

    Returns:
        True if the album name is suspicious
    """
    if not album or not track:
        return False

    album_lower = album.lower().strip()
    track_lower = track.lower().strip()

    # Exact match (case-insensitive) - very suspicious
    if album_lower == track_lower:
        return True

    # Album equals track with common single suffixes
    single_suffixes = [
        " - single", " - single version",
        " (single)", " (single version)",
        " - promo", " - promotional",
        " (promo)", " (promotional)",
        " - radio edit", " (radio edit)",
        " - edit", " (edit)",
    ]

    for suffix in single_suffixes:
        if album_lower == track_lower + suffix:
            return True

    # Album is very short (likely not a real album name)
    # But exclude known short album names like "Led", "IV", etc.
    if len(album_lower) < 4 and album_lower not in ["iv", "iii", "ii", "led", "vs", "ep"]:
        return True

    # Album is just the track name in quotes
    if album_lower == f'"{track_lower}"' or album_lower == f"'{track_lower}'":
        return True

    return False


def find_correct_album_from_database(
    artist: str,
    track: str,
    exclude_album: str
) -> Optional[str]:
    """
    Find the correct album for a track from existing scrobbles in the database.

    Looks for other scrobbles of the same track by the same artist
    to find what album they're associated with.

    Args:
        artist: The artist name
        track: The track name
        exclude_album: The album to exclude (the suspicious one)

    Returns:
        The correct album name if found with high confidence, None otherwise
    """
    import sqlite3
    from pathlib import Path
    from app.db.connections import _normalize_for_matching

    DB_PATH = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        # Normalize for comparison
        exclude_norm = _normalize_for_matching(exclude_album)

        # Find other scrobbles of this track that have a different album
        rows = conn.execute(
            """
            SELECT album, COUNT(*) as plays
            FROM scrobble
            WHERE artist = ?
              AND track = ?
              AND album != ?
              AND album IS NOT NULL
              AND album != ''
            GROUP BY album
            ORDER BY plays DESC
            LIMIT 5
            """,
            (artist, track, exclude_album)
        ).fetchall()

        if not rows:
            return None

        # If we have results, check if one album dominates
        total_plays = sum(row["plays"] for row in rows)
        if total_plays == 0:
            return None

        # If the top album has > 80% of plays, we're confident
        top_album = rows[0]["album"]
        top_plays = rows[0]["plays"]

        # Normalize top album for comparison
        top_norm = _normalize_for_matching(top_album)

        # Skip if the "correct" album is the same as the suspicious one (after normalization)
        if top_norm == exclude_norm:
            logger.debug(f"Database lookup returned same album '{top_album}' for {artist} - {track}, no correction")
            return None

        if top_plays / total_plays > 0.8:
            logger.info(f"Found correct album from database: '{top_album}' for {artist} - {track} ({top_plays}/{total_plays} plays)")
            return top_album

        # If multiple albums, try to find the most common one (not single/suffix)
        for row in rows:
            album = row["album"]
            album_norm = _normalize_for_matching(album)

            # Skip if it normalizes to the same as the suspicious album
            if album_norm == exclude_norm:
                continue

            # Skip obviously single albums
            if any(s in album.lower() for s in [" - single", "(single)", " - promo", "(promo)"]):
                continue
            logger.info(f"Found correct album from database (filtering singles): '{album}' for {artist} - {track}")
            return album

        return None

    finally:
        conn.close()


def find_correct_album_from_lastfm(
    artist: str,
    track: str,
    api_key: str,
    suspicious_album: str
) -> Optional[str]:
    """
    Find the correct album for a track using Last.fm track.getInfo API.

    Args:
        artist: The artist name
        track: The track name
        api_key: Last.fm API key
        suspicious_album: The suspicious album name to check against

    Returns:
        The correct album name if found, None otherwise
    """
    params = {
        "method": "track.getInfo",
        "api_key": api_key,
        "artist": artist,
        "track": track,
        "format": "json",
        "autocorrect": 0,
    }

    try:
        response = requests.get(LF_BASE_URL, params=params, timeout=LF_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        if "error" in data:
            logger.debug(f"Last.fm API error for {artist} - {track}: {data.get('message')}")
            return None

        track_info = data.get("track", {})
        if not track_info:
            return None

        album_info = track_info.get("album", {})
        if not album_info:
            return None

        album = album_info.get("title", "")
        if album:
            # Normalize both for comparison
            album_norm = album.lower().strip()
            suspicious_norm = suspicious_album.lower().strip()

            # Skip if it's the same as the suspicious album (no real correction)
            if album_norm == suspicious_norm:
                logger.debug(f"Last.fm returned same album '{album}' for {artist} - {track}, no correction")
                return None

            # Skip if the album is clearly a single/live recording
            skip_patterns = [
                " - single", "(single)", " - single version",
                " - promo", "(promo)", " - promotional",
                " - ep", "(ep)", " - live", "(live)",
                " - bbc", " - radio edit", " - session",
                " - at", " live at", " - from"
            ]

            for pattern in skip_patterns:
                if pattern in album_norm:
                    logger.debug(f"Skipping live/single album '{album}' for {artist} - {track}")
                    return None

            # Skip if it's a venue/location recording (e.g., "2019-11-11: Scotiabank Arena")
            if re.match(r'^\d{4}-\d{2}-\d{2}:', album):
                logger.debug(f"Skipping venue recording '{album}' for {artist} - {track}")
                return None

            logger.info(f"Found correct album from Last.fm: '{album}' for {artist} - {track}")
            return album

        return None

    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning(f"Error fetching track info from Last.fm for {artist} - {track}: {e}")
        return None


def find_correct_album_from_musicbrainz(
    artist: str,
    track: str,
    artist_mbid: str
) -> Optional[str]:
    """
    Find the correct album for a track using MusicBrainz data.

    Args:
        artist: The artist name
        track: The track name
        artist_mbid: The artist's MusicBrainz ID

    Returns:
        The correct album name if found, None otherwise
    """
    if not artist_mbid:
        return None

    try:
        releases = fetch_artist_releases_from_musicbrainz(artist_mbid)

        if not releases:
            return None

        # Try to find a matching track in album titles
        # This is a heuristic - we look for albums whose title might contain the track
        track_normalized = _normalize_for_matching(track)

        for release in releases:
            if not release.get("is_pure_album", False):
                continue  # Skip compilations, live, remix

            album_title = release.get("title", "")
            album_normalized = _normalize_for_matching(album_title)

            # Skip if the album title is too short or too similar to track
            if len(album_normalized) < 3:
                continue

            # Skip if album equals track (already suspicious)
            if album_normalized == track_normalized:
                continue

            # Look for partial matches (album might contain track name)
            # This is a loose heuristic
            if track_normalized in album_normalized and len(track_normalized) > 3:
                # Make sure it's not just the track name with suffixes
                if album_normalized.replace(track_normalized, "").strip() != "":
                    logger.info(f"Found potential album from MusicBrainz: '{album_title}' for {artist} - {track}")
                    return album_title

        return None

    except Exception as e:
        logger.warning(f"Error fetching from MusicBrainz for {artist}: {e}")
        return None


def validate_and_correct_album(
    artist: str,
    album: str,
    track: str,
    artist_mbid: Optional[str] = None,
    auto_correct: bool = False
) -> Tuple[bool, Optional[str], int]:
    """
    Validate and potentially correct the album association for a scrobble.

    Args:
        artist: The artist name
        album: The album name from scrobble (potentially incorrect)
        track: The track name
        artist_mbid: The artist's MusicBrainz ID (optional)
        auto_correct: If True, auto-correct when confident; if False, only log the issue

    Returns:
        A tuple of (is_valid, correct_album, confidence)
        - is_valid: True if album is valid, False if suspicious
        - correct_album: The correct album name if found, None otherwise
        - confidence: 1-100 (how confident we are in the correction)
    """
    # Check if album name is suspicious
    if not is_album_name_suspicious(album, track, artist):
        return True, None, 100

    # Album is suspicious - try to find the correct one
    logger.info(f"Suspicious album detected: {artist} - {track} (album: '{album}')")

    confidence = 0
    correct_album = None

    # 1. Check our own database first (most reliable)
    correct_album = find_correct_album_from_database(artist, track, album)
    if correct_album:
        confidence = 95  # High confidence - from our own data
        if auto_correct:
            return False, correct_album, confidence

    # 2. Try Last.fm API
    if not correct_album:
        api_key, _ = get_api_key()
        correct_album = find_correct_album_from_lastfm(artist, track, api_key, album)
        if correct_album:
            confidence = 80  # Medium-high confidence - from Last.fm
            if auto_correct:
                return False, correct_album, confidence

    # 3. Try MusicBrainz (least reliable for track-to-album lookup)
    if not correct_album and artist_mbid:
        correct_album = find_correct_album_from_musicbrainz(artist, track, artist_mbid)
        if correct_album:
            confidence = 60  # Medium confidence - from MusicBrainz heuristic
            if auto_correct:
                return False, correct_album, confidence

    # If we found a correction, return it; otherwise mark as invalid
    if correct_album:
        logger.info(f"Correction found for '{album}' -> '{correct_album}' (confidence: {confidence})")
        return False, correct_album, confidence
    else:
        logger.warning(f"No correction found for suspicious album '{album}' for {artist} - {track}")
        return False, None, 0


def log_data_quality_issue(
    artist: str,
    bad_album: str,
    track: str,
    correct_album: Optional[str],
    confidence: int,
    auto_corrected: bool = False
):
    """
    Log a data quality issue to the database for tracking.

    Args:
        artist: The artist name
        bad_album: The suspicious/incorrect album name
        track: The track name
        correct_album: The correct album name (if found)
        confidence: Confidence level of the correction (1-100)
        auto_corrected: Whether this was auto-corrected
    """
    import sqlite3
    from pathlib import Path

    DB_PATH = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
    conn = sqlite3.connect(DB_PATH)

    try:
        conn.execute(
            """
            INSERT INTO data_quality_issues
            (issue_type, artist_name, album_name, track_name, correct_album_name,
             confidence, status, auto_corrected, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "album_track_mismatch",
                artist,
                bad_album,
                track,
                correct_album,
                confidence,
                "resolved" if correct_album and auto_corrected else "open",
                auto_corrected,
                f"Auto-corrected with confidence {confidence}%" if auto_corrected else "Requires review"
            )
        )
        conn.commit()

    except sqlite3.Error as e:
        logger.error(f"Error logging data quality issue: {e}")
    finally:
        conn.close()
