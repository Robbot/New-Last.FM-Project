"""
Spotify integration blueprint.

Provides web UI for:
- Spotify authentication (OAuth flow)
- Playlist management
- Manual playlist generation
- Playlist history
"""

from flask import Blueprint

spotify_bp = Blueprint("spotify", __name__, url_prefix="/spotify")

from app.spotify import routes
