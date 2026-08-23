import logging
import os
import secrets
from pathlib import Path
from flask import Flask, redirect, url_for, jsonify
from werkzeug.middleware.proxy_fix import ProxyFix
from .services.config import get_api_key
from .logging_config import setup_logging, setup_request_logging, cleanup_old_logs
from datetime import datetime, timezone
from .utils.validators import ValidationError

def datetime_format_filter(timestamp):
    """Format Unix timestamp to readable datetime string."""
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

def create_app():
    app = Flask(__name__)

    # Sessions are required for admin CSRF protection. In production, set a
    # stable SECRET_KEY so tokens survive process restarts and multiple workers.
    secret_key = os.environ.get("SECRET_KEY")
    if not secret_key:
        secret_key = secrets.token_hex(32)
        app.logger.warning(
            "SECRET_KEY is not configured; using an ephemeral key for this process"
        )
    app.config["SECRET_KEY"] = secret_key
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Strict"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get(
        "SESSION_COOKIE_SECURE", "0"
    ).lower() in {"1", "true", "yes", "on"}

    # Production is served through one local reverse proxy. ProxyFix trusts
    # only the configured number of right-most forwarding entries instead of
    # allowing route code to consume an arbitrary client-supplied header.
    trusted_proxy_hops = int(os.environ.get("TRUSTED_PROXY_HOPS", "1"))
    if trusted_proxy_hops > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=trusted_proxy_hops)

    # Disable template caching and auto-reload for development
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.jinja_env.auto_reload = True
    app.jinja_env.cache = {}

    # Set database path in config
    BASE_DIR = Path(__file__).resolve().parent.parent
    app.config["DATABASE_PATH"] = str(BASE_DIR / "files" / "lastfmstats.sqlite")

    # Setup logging
    setup_logging(app)
    setup_request_logging(app)
    app.logger.info("Initializing Flask application")

    # Clean up old log files on startup (keeps last 30 days by default)
    deleted_logs = cleanup_old_logs()
    if deleted_logs > 0:
        app.logger.info(f"Cleaned up {deleted_logs} old log file(s) on startup")

    # Register custom Jinja filters
    app.jinja_env.filters['datetime_format'] = datetime_format_filter

    # Add min function to Jinja globals for templates
    app.jinja_env.globals['min'] = min

    from .scrobbles import scrobbles_bp
    from .artists import artists_bp
    from .albums import albums_bp
    from .compilations import compilations_bp
    from .tracks import tracks_bp
    from .trackgaps import trackgaps_bp
    from .daterange import daterange_bp
    from .admin import admin_bp
    from .spotify import spotify_bp
    from .db import notifications as db_notifications  # Ensures notifications module is loaded


    app.register_blueprint(scrobbles_bp)
    app.register_blueprint(artists_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(compilations_bp)
    app.register_blueprint(tracks_bp)
    app.register_blueprint(trackgaps_bp)
    app.register_blueprint(daterange_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(spotify_bp)

    api_key, username = get_api_key()
    app.config["api_key"] = api_key
    app.config["lastfm_username"] = username
    app.logger.info(f"Loaded Last.fm config for user: {username}")

    @app.route("/")
    def index():
        return redirect(url_for("scrobbles.library_scrobbles"))

    @app.errorhandler(404)
    def not_found(e):
        app.logger.warning(f"404 Not Found: {e}")
        return redirect(url_for("scrobbles.library_scrobbles"))

    @app.errorhandler(500)
    def server_error(e):
        app.logger.error(f"500 Server Error: {e}", exc_info=True)
        return "Internal Server Error", 500

    @app.errorhandler(ValidationError)
    def validation_error(e):
        """Handle validation errors with a 400 Bad Request response."""
        app.logger.warning(f"Validation error: {e}")
        # Check if request expects JSON (API routes)
        accept_header = getattr(e, 'request_accept', None)
        # For simplicity, return JSON for all validation errors
        # This works for both API and HTML routes
        return jsonify({"error": str(e)}), 400

    app.logger.info("Application initialization complete")
    return app
