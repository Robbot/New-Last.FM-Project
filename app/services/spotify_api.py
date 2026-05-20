"""
Spotify API client wrapper.

Implements OAuth 2.0 authorization code flow and core Spotify API endpoints
for playlist creation and track search.
"""

import time
import json
import logging
import requests
from typing import Optional, List, Dict
from urllib.parse import urlencode

from .spotify_config import get_spotify_credentials
from .connections import get_db_connection

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"

# Scopes required for playlist management
PLAYLIST_SCOPES = [
    "playlist-read-private",
    "playlist-modify-public",
    "playlist-modify-private",
    "user-library-read",
]


class SpotifyAPIError(Exception):
    """Custom exception for Spotify API errors."""
    pass


class SpotifyAPI:
    """Spotify API client with OAuth 2.0 authorization code flow."""

    def __init__(self, access_token: Optional[str] = None):
        """
        Initialize Spotify API client.

        Args:
            access_token: Optional pre-existing access token. If not provided,
                         will attempt to load from database.
        """
        self.client_id, self.client_secret, self.redirect_uri = get_spotify_credentials()
        self.access_token = access_token or self._load_token_from_db()
        self.refresh_token = None
        self.token_expires_at = 0

        if self.access_token:
            # Load token info from database
            self._load_token_info()

    def _load_token_from_db(self) -> Optional[str]:
        """Load access token from database."""
        try:
            conn = get_db_connection()
            row = conn.execute(
                "SELECT access_token, refresh_token, expires_at FROM spotify_tokens WHERE user_id = 'default' LIMIT 1"
            ).fetchone()
            conn.close()

            if row:
                return row["access_token"]
        except Exception as e:
            logger.debug(f"No token found in database: {e}")

        return None

    def _load_token_info(self):
        """Load token info from database."""
        try:
            conn = get_db_connection()
            row = conn.execute(
                "SELECT refresh_token, expires_at FROM spotify_tokens WHERE user_id = 'default' LIMIT 1"
            ).fetchone()
            conn.close()

            if row:
                self.refresh_token = row["refresh_token"]
                self.token_expires_at = row["expires_at"]
        except Exception as e:
            logger.debug(f"Could not load token info: {e}")

    def _save_token(self, access_token: str, refresh_token: str, expires_in: int):
        """Save token to database."""
        expires_at = int(time.time()) + expires_in

        try:
            conn = get_db_connection()
            conn.execute(
                """
                INSERT INTO spotify_tokens (user_id, access_token, refresh_token, expires_at)
                VALUES ('default', ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    access_token = excluded.access_token,
                    refresh_token = excluded.refresh_token,
                    expires_at = excluded.expires_at,
                    updated_at = strftime('%s', 'now')
                """,
                (access_token, refresh_token, expires_at),
            )
            conn.commit()
            conn.close()

            self.access_token = access_token
            self.refresh_token = refresh_token
            self.token_expires_at = expires_at

            logger.info("Spotify token saved to database")
        except Exception as e:
            logger.error(f"Failed to save token: {e}", exc_info=True)

    def get_auth_url(self) -> str:
        """
        Generate Spotify authorization URL.

        Returns:
            str: Authorization URL for user to visit
        """
        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(PLAYLIST_SCOPES),
            "show_dialog": "true",
        }

        return f"{SPOTIFY_AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_token(self, code: str) -> dict:
        """
        Exchange authorization code for access token.

        Args:
            code: Authorization code from Spotify callback

        Returns:
            dict: Token response with access_token, refresh_token, expires_in

        Raises:
            SpotifyAPIError: If token exchange fails
        """
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(SPOTIFY_TOKEN_URL, data=data, headers=headers, timeout=10)
            response.raise_for_status()

            token_data = response.json()

            # Save token to database
            self._save_token(
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_in=token_data["expires_in"],
            )

            logger.info("Successfully exchanged authorization code for token")
            return token_data

        except requests.RequestException as e:
            logger.error(f"Token exchange failed: {e}", exc_info=True)
            raise SpotifyAPIError(f"Failed to exchange code for token: {e}")

    def _refresh_access_token(self):
        """Refresh access token using refresh token."""
        if not self.refresh_token:
            raise SpotifyAPIError("No refresh token available")

        data = {
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = requests.post(SPOTIFY_TOKEN_URL, data=data, headers=headers, timeout=10)
            response.raise_for_status()

            token_data = response.json()

            # Spotify may return a new refresh token
            new_refresh_token = token_data.get("refresh_token", self.refresh_token)

            self._save_token(
                access_token=token_data["access_token"],
                refresh_token=new_refresh_token,
                expires_in=token_data["expires_in"],
            )

            logger.info("Successfully refreshed access token")

        except requests.RequestException as e:
            logger.error(f"Token refresh failed: {e}", exc_info=True)
            raise SpotifyAPIError(f"Failed to refresh token: {e}")

    def _ensure_valid_token(self):
        """Ensure access token is valid, refresh if needed."""
        if not self.access_token:
            raise SpotifyAPIError("No access token available. Please authenticate first.")

        # Check if token expires in less than 60 seconds
        if self.token_expires_at - time.time() < 60:
            logger.info("Access token expiring soon, refreshing...")
            self._refresh_access_token()

    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make authenticated request to Spotify API.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE)
            endpoint: API endpoint (without base URL)
            **kwargs: Additional arguments for requests

        Returns:
            dict: JSON response from API

        Raises:
            SpotifyAPIError: If request fails
        """
        self._ensure_valid_token()

        url = f"{SPOTIFY_API_BASE}/{endpoint}"
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self.access_token}"

        try:
            response = requests.request(method, url, headers=headers, timeout=10, **kwargs)
            response.raise_for_status()
            return response.json()

        except requests.RequestException as e:
            # Check if token expired (401)
            if response.status_code == 401:
                logger.info("Access token expired, attempting refresh...")
                try:
                    self._refresh_access_token()
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    response = requests.request(method, url, headers=headers, timeout=10, **kwargs)
                    response.raise_for_status()
                    return response.json()
                except Exception:
                    pass

            logger.error(f"Spotify API request failed: {e}", exc_info=True)
            raise SpotifyAPIError(f"API request failed: {e}")

    def get_current_user(self) -> dict:
        """
        Get current user profile.

        Returns:
            dict: User profile data including id, display_name, etc.
        """
        return self._make_request("GET", "me")

    def get_user_id(self) -> str:
        """
        Get authenticated user's Spotify ID.

        Returns:
            str: Spotify user ID
        """
        user = self.get_current_user()
        return user["id"]

    def search_track(
        self, query: str, limit: int = 10, market: Optional[str] = None
    ) -> List[dict]:
        """
        Search for a track on Spotify.

        Args:
            query: Search query (e.g., "artist:Radiohead track:High and Dry")
            limit: Maximum number of results (1-50)
            market: ISO 3166-1 alpha-2 country code for track availability

        Returns:
            list: List of track objects with name, artists, album, uri
        """
        params = {"q": query, "type": "track", "limit": min(limit, 50)}

        if market:
            params["market"] = market

        result = self._make_request("GET", "search", params=params)
        return result.get("tracks", {}).get("items", [])

    def find_track_uri(
        self, artist: str, track: str, album: Optional[str] = None
    ) -> Optional[str]:
        """
        Find Spotify URI for a specific track.

        Args:
            artist: Artist name
            track: Track name
            album: Optional album name for more precise matching

        Returns:
            str: Spotify URI (e.g., "spotify:track:...") or None if not found
        """
        # Build search query
        query = f"artist:{artist} track:{track}"
        if album:
            query += f" album:{album}"

        results = self.search_track(query, limit=5)

        if not results:
            return None

        # Return first result's URI
        return results[0].get("uri")

    def create_playlist(self, user_id: str, name: str, description: str, public: bool = False) -> dict:
        """
        Create a new playlist.

        Args:
            user_id: Spotify user ID
            name: Playlist name
            description: Playlist description
            public: Whether playlist should be public

        Returns:
            dict: Playlist object with id, name, url, etc.
        """
        data = {"name": name, "description": description, "public": public}

        result = self._make_request("POST", f"users/{user_id}/playlists", json=data)
        logger.info(f"Created playlist: {name}")
        return result

    def get_playlist(self, playlist_id: str) -> dict:
        """
        Get playlist details.

        Args:
            playlist_id: Spotify playlist ID

        Returns:
            dict: Playlist object
        """
        return self._make_request("GET", f"playlists/{playlist_id}")

    def add_tracks_to_playlist(
        self, playlist_id: str, track_uris: List[str], position: Optional[int] = None
    ) -> dict:
        """
        Add tracks to a playlist.

        Args:
            playlist_id: Spotify playlist ID
            track_uris: List of Spotify track URIs
            position: Position to insert tracks (default: append to end)

        Returns:
            dict: Response with snapshot_id
        """
        data = {"uris": track_uris}

        if position is not None:
            data["position"] = position

        result = self._make_request("POST", f"playlists/{playlist_id}/tracks", json=data)
        logger.info(f"Added {len(track_uris)} tracks to playlist {playlist_id}")
        return result

    def replace_playlist_tracks(self, playlist_id: str, track_uris: List[str]) -> dict:
        """
        Replace all tracks in a playlist.

        Args:
            playlist_id: Spotify playlist ID
            track_uris: List of Spotify track URIs

        Returns:
            dict: Response with snapshot_id
        """
        data = {"uris": track_uris}

        result = self._make_request("PUT", f"playlists/{playlist_id}/tracks", json=data)
        logger.info(f"Replaced tracks in playlist {playlist_id} with {len(track_uris)} tracks")
        return result

    def update_playlist_details(
        self, playlist_id: str, name: Optional[str] = None, description: Optional[str] = None
    ) -> dict:
        """
        Update playlist details.

        Args:
            playlist_id: Spotify playlist ID
            name: New playlist name (optional)
            description: New description (optional)

        Returns:
            dict: Updated playlist object
        """
        data = {}

        if name is not None:
            data["name"] = name

        if description is not None:
            data["description"] = description

        result = self._make_request("PUT", f"playlists/{playlist_id}", json=data)
        logger.info(f"Updated playlist {playlist_id}")
        return result


def get_spotify_client() -> SpotifyAPI:
    """
    Get authenticated Spotify API client.

    Returns:
        SpotifyAPI: Authenticated client instance

    Raises:
        SpotifyAPIError: If no valid token exists
    """
    client = SpotifyAPI()

    if not client.access_token:
        raise SpotifyAPIError(
            "No Spotify access token found. Please authenticate first using the CLI or web interface."
        )

    return client
