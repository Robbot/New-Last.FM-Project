import configparser
import os
from pathlib import Path


def get_api_key() -> tuple[str, str]:
    """
    Get Last.fm API key and username.

    Priority order:
    1. Environment variables (LASTFM_API_KEY, LASTFM_USERNAME)
    2. config.ini file (fallback for backwards compatibility)

    Returns:
        tuple[str, str]: (api_key, username)
    """
    # Try environment variables first (recommended for production)
    api_key = os.getenv("LASTFM_API_KEY")
    username = os.getenv("LASTFM_USERNAME")

    if api_key and username:
        return api_key, username

    # Fallback to config.ini for backwards compatibility
    config = configparser.ConfigParser()
    config_path = Path(__file__).resolve().parent / "config.ini"

    read_files = config.read(config_path)
    if not read_files:
        raise FileNotFoundError(
            "No Last.fm credentials found. "
            "Either set LASTFM_API_KEY and LASTFM_USERNAME environment variables, "
            f"or create config.ini at: {config_path}"
        )

    section = config["last.fm"]
    api_key = section["api_key"]
    username = section["username"]

    return api_key, username