from flask import Flask, redirect, url_for
from .services.config import get_api_key
from datetime import datetime, timezone

def datetime_format_filter(timestamp):
    """Format Unix timestamp to readable datetime string."""
    if timestamp is None:
        return "—"
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")

def create_app():
    app = Flask(__name__)

    # Register custom Jinja filters
    app.jinja_env.filters['datetime_format'] = datetime_format_filter

    from .scrobbles import scrobbles_bp
    from .artists import artists_bp
    from .albums import albums_bp
    from .tracks import tracks_bp
    from .trackgaps import trackgaps_bp
    from .daterange import daterange_bp


    app.register_blueprint(scrobbles_bp)
    app.register_blueprint(artists_bp)
    app.register_blueprint(albums_bp)
    app.register_blueprint(tracks_bp)
    app.register_blueprint(trackgaps_bp)
    app.register_blueprint(daterange_bp)

    api_key, username = get_api_key()
    app.config["api_key"] = api_key
    app.config["lastfm_username"] = username

    @app.route("/")
    def index():
        return redirect(url_for("scrobbles.library_scrobbles"))
    
    return app

