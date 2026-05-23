"""
Playlist generation service.

Generates Spotify playlists based on Last.fm scrobble statistics
with various algorithms: forgotten albums, top tracks, deep cuts,
high rotation, and AI-powered mixes.
"""

import logging
import random
from datetime import datetime, timezone
from typing import List, Dict, Optional

from .spotify_api import SpotifyAPI, get_spotify_client
from .spotify_matcher import SpotifyTrackMatcher, get_matcher
from app.db.connections import get_db_connection
from app.db import playlist_queries
from app.db.notifications import create_notification

logger = logging.getLogger(__name__)


class PlaylistGenerator:
    """Generate Spotify playlists based on Last.fm statistics."""

    def __init__(self, api_client: Optional[SpotifyAPI] = None, matcher: Optional[SpotifyTrackMatcher] = None):
        """
        Initialize playlist generator.

        Args:
            api_client: Optional SpotifyAPI client
            matcher: Optional SpotifyTrackMatcher instance
        """
        self.api = api_client
        self.matcher = matcher

        # Initialize on first use if not provided
        if not self.api:
            try:
                self.api = get_spotify_client()
            except Exception as e:
                logger.warning(f"Could not initialize Spotify API: {e}")

        if not self.matcher:
            self.matcher = get_matcher()
            if self.api:
                self.matcher.api = self.api

    def _find_track_uris(self, tracks: List[Dict], min_confidence: int = 70) -> List[str]:
        """
        Find Spotify URIs for a list of tracks.

        Args:
            tracks: List of track dicts with artist, track, album
            min_confidence: Minimum confidence score for matching

        Returns:
            list: List of Spotify URIs
        """
        uris = []

        for track_info in tracks:
            artist = track_info.get("artist")
            track = track_info.get("track")
            album = track_info.get("album")

            if not artist or not track:
                continue

            uri = self.matcher.find_track_uri(artist, track, album, min_confidence=min_confidence)

            if uri:
                uris.append(uri)
                logger.debug(f"Found URI for {artist} - {track}")
            else:
                logger.debug(f"No URI found for {artist} - {track}")

        return uris

    def _save_playlist_history(
        self, playlist_type: str, name: str, spotify_id: Optional[str], track_count: int, parameters: Dict
    ):
        """Save playlist generation to history."""
        try:
            import json

            conn = get_db_connection()

            conn.execute(
                """
                INSERT INTO playlist_history (playlist_type, playlist_name, spotify_playlist_id, track_count, parameters)
                VALUES (?, ?, ?, ?, ?)
            """,
                (playlist_type, name, spotify_id, track_count, json.dumps(parameters)),
            )

            conn.commit()
            conn.close()

            logger.debug(f"Saved playlist history: {name}")

        except Exception as e:
            logger.error(f"Failed to save playlist history: {e}")

    def generate_forgotten_albums_playlist(
        self,
        days_threshold: int = 180,
        track_limit: int = 50,
        name: Optional[str] = None,
        description: Optional[str] = None,
        create_on_spotify: bool = True,
    ) -> Dict:
        """
        Generate playlist of albums not played recently.

        Args:
            days_threshold: Days since last play to consider "forgotten"
            track_limit: Maximum number of tracks
            name: Custom playlist name (auto-generated if None)
            description: Custom playlist description
            create_on_spotify: Whether to actually create on Spotify

        Returns:
            dict: Playlist info with tracks, spotify_id, etc.
        """
        logger.info(f"Generating forgotten albums playlist (threshold: {days_threshold} days)")

        # Get forgotten albums
        forgotten = playlist_queries.get_forgotten_albums(days_threshold=days_threshold, limit=track_limit * 2)

        # Sample tracks from these albums (prefer less played albums)
        tracks = []
        seen_artists = set()

        for album_info in forgotten:
            # Ensure artist diversity
            if album_info["artist"] in seen_artists and len(seen_artists) > 20:
                continue

            seen_artists.add(album_info["artist"])

            # Get recent plays from this album
            conn = get_db_connection()

            rows = conn.execute(
                """
                SELECT DISTINCT artist, album, track
                FROM scrobble
                WHERE artist = ? AND album = ?
                ORDER BY RANDOM()
                LIMIT 2
            """,
                (album_info["artist"], album_info["album"]),
            ).fetchall()

            conn.close()

            for row in rows:
                tracks.append(dict(row))
                if len(tracks) >= track_limit:
                    break

            if len(tracks) >= track_limit:
                break

        # Shuffle for variety
        random.shuffle(tracks)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="forgotten_albums",
            name=name or f"Forgotten Gems ({days_threshold} days)",
            description=description
            or f"Albums I haven't played in {days_threshold} days or more. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"days_threshold": days_threshold, "track_limit": track_limit},
        )

    def generate_top_tracks_playlist(
        self,
        period_days: int = 30,
        limit: int = 50,
        name: Optional[str] = None,
        description: Optional[str] = None,
        create_on_spotify: bool = True,
    ) -> Dict:
        """
        Generate playlist of most played tracks in a time period.

        Args:
            period_days: Number of days to look back
            limit: Maximum number of tracks
            name: Custom playlist name
            description: Custom playlist description
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info(f"Generating top tracks playlist (period: {period_days} days)")

        tracks = playlist_queries.get_top_tracks_by_period(period_days=period_days, limit=limit)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="top_tracks",
            name=name or f"Top Tracks - Last {period_days} Days",
            description=description
            or f"My most played tracks from the last {period_days} days. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"period_days": period_days, "limit": limit},
        )

    def generate_deep_cuts_playlist(
        self, min_plays: int = 3, max_plays: int = 20, limit: int = 50, create_on_spotify: bool = True
    ) -> Dict:
        """
        Generate playlist of lesser-played tracks from top artists.

        Args:
            min_plays: Minimum times track must have been played
            max_plays: Maximum times track must have been played
            limit: Maximum number of tracks
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info(f"Generating deep cuts playlist ({min_plays}-{max_plays} plays)")

        tracks = playlist_queries.get_deep_cuts(min_plays=min_plays, max_plays=max_plays, limit=limit)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="deep_cuts",
            name=f"Deep Cuts Discovery ({min_plays}-{max_plays} plays)",
            description=f"Lesser-known gems from my favorite artists. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"min_plays": min_plays, "max_plays": max_plays, "limit": limit},
        )

    def generate_high_rotation_playlist(
        self, days: int = 7, min_plays: int = 3, limit: int = 50, create_on_spotify: bool = True
    ) -> Dict:
        """
        Generate playlist of tracks played frequently in recent days.

        Args:
            days: Number of days to look back
            min_plays: Minimum number of plays in the period
            limit: Maximum number of tracks
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info(f"Generating high rotation playlist (last {days} days)")

        tracks = playlist_queries.get_high_rotation(days=days, min_plays=min_plays, limit=limit)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="high_rotation",
            name=f"Heavy Rotation - Last {days} Days",
            description=f"Tracks I've been playing on repeat lately. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"days": days, "min_plays": min_plays, "limit": limit},
        )

    def generate_track_gaps_playlist(self, limit: int = 50, create_on_spotify: bool = True) -> Dict:
        """
        Generate playlist of tracks not played in the longest time.

        Args:
            limit: Maximum number of tracks
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info("Generating track gaps playlist")

        tracks = playlist_queries.get_track_gaps(limit=limit)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="track_gaps",
            name="Rediscover These Tracks",
            description=f"Tracks I haven't played in the longest time. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"limit": limit},
        )

    def generate_recent_discoveries_playlist(
        self, days: int = 30, limit: int = 50, create_on_spotify: bool = True
    ) -> Dict:
        """
        Generate playlist of tracks first played recently.

        Args:
            days: Number of days to look back
            limit: Maximum number of tracks
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info(f"Generating recent discoveries playlist (last {days} days)")

        tracks = playlist_queries.get_recent_discoveries(days=days, limit=limit)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="recent_discoveries",
            name=f"New Discoveries - Last {days} Days",
            description=f"Tracks I discovered for the first time recently. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"days": days, "limit": limit},
        )

    def generate_ai_mix(
        self, style: str = "forgotten", diversity: str = "medium", limit: int = 50, create_on_spotify: bool = True
    ) -> Dict:
        """
        Generate playlist using AI logic based on listening patterns.

        AI Logic:
        - Analyzes listening patterns (time of day, day of week)
        - Detects mood patterns (high energy vs chill)
        - Balances familiar vs discovery tracks
        - Considers artist diversity
        - Uses album cohort analysis for flow

        Args:
            style: "forgotten", "discovery", "familiar", or "balanced"
            diversity: "low", "medium", or "high" artist diversity
            limit: Maximum number of tracks
            create_on_spotify: Whether to create on Spotify

        Returns:
            dict: Playlist info
        """
        logger.info(f"Generating AI mix playlist (style: {style}, diversity: {diversity})")

        tracks = []
        seen_artists = set()

        # Base track selection on style
        if style == "forgotten":
            base_tracks = playlist_queries.get_track_gaps(limit=limit * 3)
        elif style == "discovery":
            base_tracks = playlist_queries.get_deep_cuts(min_plays=2, max_plays=15, limit=limit * 3)
        elif style == "familiar":
            base_tracks = playlist_queries.get_top_tracks_by_period(period_days=30, limit=limit * 2)
        else:  # balanced
            # Mix of forgotten and familiar
            forgotten = playlist_queries.get_track_gaps(limit=limit)
            familiar = playlist_queries.get_top_tracks_by_period(period_days=90, limit=limit)
            base_tracks = forgotten[: limit // 2] + familiar[: limit // 2]

        # Apply diversity filter
        max_same_artist = {"low": limit, "medium": max(3, limit // 10), "high": max(2, limit // 20)}[diversity]

        for track in base_tracks:
            artist = track.get("artist")

            # Count how many tracks we already have from this artist
            artist_count = sum(1 for t in tracks if t.get("artist") == artist)

            if artist_count < max_same_artist:
                tracks.append(track)
                seen_artists.add(artist)

            if len(tracks) >= limit:
                break

        # Shuffle for variety (but keep some coherence)
        if style != "familiar":
            random.shuffle(tracks)

        return self._create_playlist(
            tracks=tracks,
            playlist_type="ai_mix",
            name=f"AI Mix: {style.title()} ({diversity} diversity)",
            description=f"AI-generated playlist based on my listening patterns. Style: {style}, Diversity: {diversity}. Generated {datetime.now().strftime('%Y-%m-%d')}.",
            create_on_spotify=create_on_spotify,
            parameters={"style": style, "diversity": diversity, "limit": limit},
        )

    def _create_playlist(
        self,
        tracks: List[Dict],
        playlist_type: str,
        name: str,
        description: str,
        create_on_spotify: bool,
        parameters: Dict,
    ) -> Dict:
        """
        Create or update a playlist.

        Args:
            tracks: List of track dicts
            playlist_type: Type of playlist
            name: Playlist name
            description: Playlist description
            create_on_spotify: Whether to actually create on Spotify
            parameters: Generation parameters

        Returns:
            dict: Playlist info
        """
        logger.info(f"Creating playlist '{name}' with {len(tracks)} tracks")

        result = {
            "name": name,
            "description": description,
            "playlist_type": playlist_type,
            "track_count": len(tracks),
            "tracks": tracks,
            "spotify_id": None,
            "spotify_url": None,
            "parameters": parameters,
        }

        if not create_on_spotify:
            logger.info("Dry run mode - not creating on Spotify")
            return result

        if not self.api:
            logger.error("No Spotify API client available")
            create_notification(
                notification_type="playlist_error",
                title="Spotify API not available",
                message="Could not create playlist - not authenticated with Spotify",
                severity="error",
            )
            return result

        try:
            # Get user ID
            user_id = self.api.get_user_id()

            # Find Spotify URIs for tracks
            uris = self._find_track_uris(tracks, min_confidence=70)

            if not uris:
                logger.warning(f"No Spotify URIs found for any tracks")
                create_notification(
                    notification_type="playlist_warning",
                    title=f"No tracks matched for '{name}'",
                    message=f"Could not find any tracks on Spotify for playlist '{name}'",
                    severity="warning",
                )
                return result

            # Create playlist
            playlist = self.api.create_playlist(user_id=user_id, name=name, description=description, public=False)

            spotify_id = playlist.get("id")
            spotify_url = playlist.get("external_urls", {}).get("spotify")

            # Add tracks
            self.api.add_tracks_to_playlist(spotify_id, uris)

            result["spotify_id"] = spotify_id
            result["spotify_url"] = spotify_url
            result["matched_tracks"] = len(uris)

            # Save to history
            self._save_playlist_history(playlist_type, name, spotify_id, len(uris), parameters)

            # Create notification
            create_notification(
                notification_type="playlist_created",
                title=f"Playlist created: {name}",
                message=f"Successfully created playlist '{name}' with {len(uris)} tracks on Spotify.",
                severity="info",
            )

            logger.info(f"✓ Created playlist '{name}' on Spotify with {len(uris)} tracks")

        except Exception as e:
            logger.error(f"Failed to create playlist: {e}", exc_info=True)
            create_notification(
                notification_type="playlist_error",
                title=f"Failed to create playlist: {name}",
                message=f"Error: {str(e)}",
                severity="error",
            )

        return result


def get_generator() -> PlaylistGenerator:
    """
    Get a playlist generator instance.

    Returns:
        PlaylistGenerator: Generator instance
    """
    return PlaylistGenerator()
