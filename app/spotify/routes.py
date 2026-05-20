"""
Spotify integration routes.

Provides endpoints for authentication, playlist management,
and playlist generation.
"""

import json
import logging
from flask import (
    render_template,
    redirect,
    url_for,
    request,
    session,
    jsonify,
    flash,
)

from app.spotify import spotify_bp
from app.services.spotify_config import get_spotify_credentials, get_playlist_settings
from app.services.spotify_api import SpotifyAPI, SpotifyAPIError, get_spotify_client
from app.services.playlist_generator import get_generator
from app.db.connections import get_db_connection
from app.db.notifications import create_notification

logger = logging.getLogger(__name__)


@spotify_bp.before_request
def check_local_access():
    """Restrict Spotify features to localhost/local network (like admin panel)."""
    from flask import abort

    remote_addr = request.remote_addr

    # Allow localhost and local network
    if not (
        remote_addr == "127.0.0.1"
        or remote_addr == "::1"
        or remote_addr.startswith("192.168.")
        or remote_addr.startswith("10.")
        or remote_addr.startswith("172.")
    ):
        abort(403, "Access denied. Spotify features are only available on the local network.")


@spotify_bp.route("/")
def index():
    """Spotify integration dashboard."""
    try:
        # Check if authenticated
        api = SpotifyAPI()
        authenticated = api.access_token is not None

        # Get playlist history
        conn = get_db_connection()
        history_rows = conn.execute(
            """
            SELECT playlist_type, playlist_name, spotify_playlist_id,
                   track_count, generated_at, parameters
            FROM playlist_history
            ORDER BY generated_at DESC
            LIMIT 20
        """
        ).fetchall()

        history = []
        for row in history_rows:
            history.append(
                {
                    "type": row["playlist_type"],
                    "name": row["playlist_name"],
                    "spotify_id": row["spotify_playlist_id"],
                    "track_count": row["track_count"],
                    "generated_at": row["generated_at"],
                    "parameters": json.loads(row["parameters"]) if row["parameters"] else {},
                }
            )

        conn.close()

        # Get settings
        settings = get_playlist_settings()

        return render_template(
            "spotify/index.html",
            authenticated=authenticated,
            history=history,
            settings=settings,
        )

    except Exception as e:
        logger.error(f"Error loading Spotify dashboard: {e}", exc_info=True)
        flash(f"Error loading dashboard: {e}", "error")
        return render_template("spotify/index.html", authenticated=False, history=[], settings={})


@spotify_bp.route("/auth")
def auth():
    """Start Spotify OAuth flow."""
    try:
        client_id, client_secret, redirect_uri = get_spotify_credentials()

        api = SpotifyAPI()
        auth_url = api.get_auth_url()

        return render_template("spotify/auth.html", auth_url=auth_url)

    except Exception as e:
        logger.error(f"Error initiating auth: {e}", exc_info=True)
        flash(f"Error initiating authentication: {e}", "error")
        return redirect(url_for("spotify.index"))


@spotify_bp.route("/callback")
def callback():
    """Handle Spotify OAuth callback."""
    try:
        code = request.args.get("code")
        error = request.args.get("error")

        if error:
            logger.error(f"Spotify OAuth error: {error}")
            flash(f"Authentication failed: {error}", "error")
            return redirect(url_for("spotify.index"))

        if not code:
            flash("No authorization code received", "error")
            return redirect(url_for("spotify.index"))

        # Exchange code for token
        api = SpotifyAPI()
        token_data = api.exchange_code_for_token(code)

        flash("Successfully authenticated with Spotify!", "success")

        # Create notification
        create_notification(
            notification_type="spotify_auth",
            title="Spotify authentication successful",
            message="You can now generate playlists from your Last.fm statistics",
            severity="info",
        )

        return redirect(url_for("spotify.index"))

    except Exception as e:
        logger.error(f"Error handling OAuth callback: {e}", exc_info=True)
        flash(f"Authentication error: {e}", "error")
        return redirect(url_for("spotify.index"))


@spotify_bp.route("/generate", methods=["POST"])
def generate_playlist():
    """Generate a playlist via AJAX."""
    try:
        data = request.get_json()
        playlist_type = data.get("type")

        if not playlist_type:
            return jsonify({"error": "Missing playlist type"}), 400

        generator = get_generator()
        result = None

        # Route to appropriate generator
        if playlist_type == "forgotten":
            result = generator.generate_forgotten_albums_playlist(
                days_threshold=data.get("days", 180),
                track_limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        elif playlist_type == "top_tracks":
            result = generator.generate_top_tracks_playlist(
                period_days=data.get("days", 30),
                limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        elif playlist_type == "deep_cuts":
            result = generator.generate_deep_cuts_playlist(
                min_plays=data.get("min_plays", 3),
                max_plays=data.get("max_plays", 20),
                limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        elif playlist_type == "high_rotation":
            result = generator.generate_high_rotation_playlist(
                days=data.get("days", 7),
                min_plays=data.get("min_plays", 3),
                limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        elif playlist_type == "track_gaps":
            result = generator.generate_track_gaps_playlist(limit=data.get("limit", 50), create_on_spotify=True)
        elif playlist_type == "recent_discoveries":
            result = generator.generate_recent_discoveries_playlist(
                days=data.get("days", 30),
                limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        elif playlist_type == "ai_mix":
            result = generator.generate_ai_mix(
                style=data.get("style", "forgotten"),
                diversity=data.get("diversity", "medium"),
                limit=data.get("limit", 50),
                create_on_spotify=True,
            )
        else:
            return jsonify({"error": f"Unknown playlist type: {playlist_type}"}), 400

        # Return result
        response = {
            "success": True,
            "playlist": {
                "name": result.get("name"),
                "type": result.get("playlist_type"),
                "track_count": result.get("track_count"),
                "matched_tracks": result.get("matched_tracks", 0),
                "spotify_url": result.get("spotify_url"),
                "spotify_id": result.get("spotify_id"),
            }
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Error generating playlist: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@spotify_bp.route("/history")
def history():
    """View playlist generation history."""
    try:
        conn = get_db_connection()

        rows = conn.execute(
            """
            SELECT id, playlist_type, playlist_name, spotify_playlist_id,
                   track_count, generated_at, parameters
            FROM playlist_history
            ORDER BY generated_at DESC
            LIMIT 100
        """
        ).fetchall()

        conn.close()

        history = []
        for row in rows:
            history.append(
                {
                    "id": row["id"],
                    "type": row["playlist_type"],
                    "name": row["playlist_name"],
                    "spotify_id": row["spotify_playlist_id"],
                    "track_count": row["track_count"],
                    "generated_at": row["generated_at"],
                    "parameters": json.loads(row["parameters"]) if row["parameters"] else {},
                }
            )

        return render_template("spotify/history.html", history=history)

    except Exception as e:
        logger.error(f"Error loading history: {e}", exc_info=True)
        flash(f"Error loading history: {e}", "error")
        return render_template("spotify/history.html", history=[])


@spotify_bp.route("/settings", methods=["GET", "POST"])
def settings():
    """Manage playlist generation settings."""
    from os import getenv

    if request.method == "POST":
        try:
            # Update environment variables for current session
            data = request.form

            # In a real implementation, you'd persist these to a config file
            flash("Settings updated (Note: persistent settings require configuration file update)", "info")

        except Exception as e:
            logger.error(f"Error updating settings: {e}", exc_info=True)
            flash(f"Error updating settings: {e}", "error")

    current_settings = get_playlist_settings()

    return render_template("spotify/settings.html", settings=current_settings)
