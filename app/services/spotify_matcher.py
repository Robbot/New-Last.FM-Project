"""
Spotify track matching service.

Matches Last.fm scrobble data to Spotify track URIs using fuzzy matching
and caching to minimize API calls.
"""

import logging
import time
import unicodedata
from difflib import SequenceMatcher
from typing import Optional, List, Dict

from .spotify_api import SpotifyAPI, get_spotify_client
from app.db.connections import get_db_connection

logger = logging.getLogger(__name__)


def normalize_for_matching(name: str) -> str:
    """
    Normalize a name for fuzzy matching.

    - Removes accents (é → e, ö → o)
    - Lowercases
    - Replaces special characters with spaces
    - Removes extra whitespace

    Args:
        name: Name to normalize

    Returns:
        str: Normalized name
    """
    if not name:
        return ""

    # Normalize Unicode quotes/apostrophes
    name = name.replace("'", "'")
    name = name.replace("'", "'")
    name = name.replace('"', '"')
    name = name.replace('"', '"')

    # Remove accents
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))

    # Lowercase
    name = name.lower()

    # Replace special characters with spaces
    for char in ['-', '_', '/', '\\', '(', ')', '[', ']', '{', '}', ':', ';', ',']:
        name = name.replace(char, ' ')

    # Remove extra whitespace
    name = ' '.join(name.split())

    return name


def similarity_score(str1: str, str2: str) -> int:
    """
    Calculate similarity score between two strings (0-100).

    Args:
        str1: First string
        str2: Second string

    Returns:
        int: Similarity score (0-100)
    """
    s1 = normalize_for_matching(str1)
    s2 = normalize_for_matching(str2)

    if s1 == s2:
        return 100

    # Check if one is substring of the other
    if s1 in s2 or s2 in s1:
        return 95

    # Use SequenceMatcher for fuzzy matching
    return int(SequenceMatcher(None, s1, s2).ratio() * 100)


class SpotifyTrackMatcher:
    """Match Last.fm scrobble data to Spotify track URIs."""

    def __init__(self, api_client: Optional[SpotifyAPI] = None):
        """
        Initialize track matcher.

        Args:
            api_client: Optional SpotifyAPI client. If not provided, will
                       create a new one using get_spotify_client().
        """
        self.api = api_client
        self._cache = {}

    def _get_from_cache(self, artist: str, album: Optional[str], track: str) -> Optional[str]:
        """
        Get Spotify URI from cache.

        Args:
            artist: Artist name
            album: Optional album name
            track: Track name

        Returns:
            str: Spotify URI or None if not in cache
        """
        try:
            conn = get_db_connection()

            if album:
                row = conn.execute(
                    """
                    SELECT spotify_uri FROM spotify_track_cache
                    WHERE artist = ? AND album = ? AND track = ?
                    AND datetime(last_updated, 'unixepoch', '+30 days') > datetime('now')
                    LIMIT 1
                """,
                    (artist, album, track),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT spotify_uri FROM spotify_track_cache
                    WHERE artist = ? AND track = ?
                    AND (album IS NULL OR album = '')
                    AND datetime(last_updated, 'unixepoch', '+30 days') > datetime('now')
                    LIMIT 1
                """,
                    (artist, track),
                ).fetchone()

            conn.close()

            if row:
                logger.debug(f"Cache hit for {artist} - {track}")
                return row["spotify_uri"]

        except Exception as e:
            logger.debug(f"Cache lookup failed: {e}")

        return None

    def _save_to_cache(self, artist: str, album: Optional[str], track: str, uri: str):
        """
        Save Spotify URI to cache.

        Args:
            artist: Artist name
            album: Optional album name
            track: Track name
            uri: Spotify URI to cache
        """
        try:
            conn = get_db_connection()

            conn.execute(
                """
                INSERT INTO spotify_track_cache (artist, album, track, spotify_uri)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(artist, album, track) DO UPDATE SET
                    spotify_uri = excluded.spotify_uri,
                    last_updated = strftime('%s', 'now')
                """,
                (artist, album, track, uri),
            )

            conn.commit()
            conn.close()

            logger.debug(f"Cached URI for {artist} - {track}")

        except Exception as e:
            logger.debug(f"Failed to cache URI: {e}")

    def find_track_uri(
        self,
        artist: str,
        track: str,
        album: Optional[str] = None,
        min_confidence: int = 70,
        use_cache: bool = True,
    ) -> Optional[str]:
        """
        Find Spotify URI for a track using fuzzy matching.

        Strategy:
        1. Check cache first (if enabled)
        2. Try exact artist + track match
        3. Try with album name if available
        4. Use fuzzy matching on results
        5. Return best match above confidence threshold

        Args:
            artist: Artist name
            track: Track name
            album: Optional album name for more precise matching
            min_confidence: Minimum confidence score (0-100) to accept a match
            use_cache: Whether to check cache before API call

        Returns:
            str: Spotify URI (e.g., "spotify:track:...") or None if not found
        """
        # Check cache first
        if use_cache:
            cached = self._get_from_cache(artist, album, track)
            if cached:
                return cached

        # Get API client if not provided
        if not self.api:
            try:
                self.api = get_spotify_client()
            except Exception as e:
                logger.error(f"Could not get Spotify client: {e}")
                return None

        # Try exact artist + track match first
        query = f"artist:{artist} track:{track}"

        if album:
            query += f" album:{album}"

        results = self.api.search_track(query, limit=10)

        if not results:
            logger.debug(f"No results for: {artist} - {track}")
            return None

        # Find best match using fuzzy matching
        best_match = None
        best_score = 0

        for result in results:
            result_artist = result.get("artists", [{}])[0].get("name", "")
            result_track = result.get("name", "")
            result_album = result.get("album", {}).get("name", "")
            result_uri = result.get("uri")

            # Calculate similarity score
            artist_score = similarity_score(artist, result_artist)

            if artist_score < 50:
                # Artist doesn't match well, skip
                continue

            track_score = similarity_score(track, result_track)

            # Bonus for album match if provided
            album_bonus = 0
            if album and result_album:
                album_score = similarity_score(album, result_album)
                if album_score >= 80:
                    album_bonus = 10

            # Weighted score: artist match is most important
            total_score = int((artist_score * 0.4 + track_score * 0.6) + album_bonus)

            # Bonus for exact match
            if normalize_for_matching(track) == normalize_for_matching(result_track):
                total_score = min(total_score + 5, 100)

            if total_score > best_score:
                best_score = total_score
                best_match = result_uri

        # Check if best match meets confidence threshold
        if best_match and best_score >= min_confidence:
            logger.info(f"Matched {artist} - {track} with confidence {best_score}%")

            # Cache the result
            if use_cache:
                self._save_to_cache(artist, album, track, best_match)

            return best_match
        elif best_match:
            logger.debug(
                f"Best match for {artist} - {track} only {best_score}% confidence (threshold: {min_confidence}%)"
            )

        return None

    def batch_find_tracks(
        self,
        tracks: List[Dict[str, str]],
        min_confidence: int = 70,
        use_cache: bool = True,
        delay: float = 0.1,
    ) -> Dict[str, str]:
        """
        Find Spotify URIs for multiple tracks efficiently.

        Args:
            tracks: List of dicts with 'artist', 'track', and optionally 'album'
            min_confidence: Minimum confidence score (0-100) to accept a match
            use_cache: Whether to use cache
            delay: Delay between API calls in seconds (rate limiting)

        Returns:
            dict: Map of track key ("artist - album - track") to Spotify URI
        """
        results = {}

        for i, track_info in enumerate(tracks):
            artist = track_info.get("artist", "")
            track = track_info.get("track", "")
            album = track_info.get("album")

            if not artist or not track:
                continue

            # Create key for results dict
            key = f"{artist} - {album if album else ''} - {track}"

            # Find URI
            uri = self.find_track_uri(
                artist=artist,
                track=track,
                album=album,
                min_confidence=min_confidence,
                use_cache=use_cache,
            )

            if uri:
                results[key] = uri

            # Rate limiting
            if i < len(tracks) - 1:
                time.sleep(delay)

            logger.info(f"Processed {i + 1}/{len(tracks)} tracks")

        return results

    def clear_cache(self, older_than_days: int = 30):
        """
        Clear cached entries older than specified days.

        Args:
            older_than_days: Only clear cache entries older than this
        """
        try:
            conn = get_db_connection()

            conn.execute(
                """
                DELETE FROM spotify_track_cache
                WHERE datetime(last_updated, 'unixepoch', '+' || ? || ' days') < datetime('now')
            """,
                (older_than_days,),
            )

            deleted = conn.total_changes
            conn.commit()
            conn.close()

            logger.info(f"Cleared {deleted} old cache entries")

        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")


def get_matcher() -> SpotifyTrackMatcher:
    """
    Get a track matcher instance.

    Returns:
        SpotifyTrackMatcher: Matcher instance
    """
    return SpotifyTrackMatcher()
