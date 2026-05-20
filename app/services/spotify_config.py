"""
Spotify API configuration management.

Follows the same pattern as Last.fm config with environment variables
as primary method and config.ini as fallback.
"""

import os
import configparser
from pathlib import Path


def get_spotify_credentials() -> tuple[str, str, str]:
    """
    Get Spotify API credentials.

    Priority order:
    1. Environment variables (SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, SPOTIFY_REDIRECT_URI)
    2. config.ini file (fallback for backwards compatibility)

    Returns:
        tuple[str, str, str]: (client_id, client_secret, redirect_uri)

    Raises:
        FileNotFoundError: If no credentials found in environment or config file
    """
    # Try environment variables first (recommended for production)
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8001/spotify/callback")

    if client_id and client_secret:
        return client_id, client_secret, redirect_uri

    # Fallback to config.ini for backwards compatibility
    config = configparser.ConfigParser()
    config_path = Path(__file__).resolve().parent / "config.ini"

    read_files = config.read(config_path)
    if not read_files:
        raise FileNotFoundError(
            "No Spotify credentials found. "
            "Either set SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET environment variables, "
            f"or create config.ini at: {config_path}"
        )

    if "spotify" not in config:
        raise KeyError(
            "Missing [spotify] section in config.ini. "
            "Please add it with your Spotify API credentials."
        )

    section = config["spotify"]
    client_id = section.get("client_id")
    client_secret = section.get("client_secret")
    redirect_uri = section.get("redirect_uri", "http://localhost:8001/spotify/callback")

    if not client_id or not client_secret:
        raise KeyError(
            "Spotify credentials incomplete in config.ini. "
            "Please provide both 'client_id' and 'client_secret' in [spotify] section."
        )

    return client_id, client_secret, redirect_uri


def get_playlist_settings() -> dict:
    """
    Get playlist generation settings from environment or defaults.

    Returns:
        dict: Settings for playlist generation
    """
    return {
        "auto_generate": os.getenv("SPOTIFY_PLAYLIST_AUTO_GENERATE", "false").lower() == "true",
        "schedule": os.getenv("SPOTIFY_PLAYLIST_SCHEDULE", "weekly"),
        "forgotten_days": int(os.getenv("SPOTIFY_PLAYLIST_FORGOTTEN_DAYS", "180")),
        "top_tracks_days": int(os.getenv("SPOTIFY_PLAYLIST_TOP_TRACKS_DAYS", "30")),
        "default_limit": int(os.getenv("SPOTIFY_PLAYLIST_DEFAULT_LIMIT", "50")),
    }
