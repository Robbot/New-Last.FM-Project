from flask import render_template, abort
import db
from . import tracks_bp

@tracks_bp.route("/library/tracks")
def library_tracks():
    stats = db.get_track_stats()
    top_tracks = db.get_top_tracks()
    return render_template("library_tracks.html", active_tab="tracks", stats=stats, top_tracks=top_tracks)

@tracks_bp.route("/library/track/<path:artist_name>/<path:track_name>")
def track_detail(artist_name, track_name):
    stats = db.get_track_stats_detail(artist_name, track_name)
    if stats is None:
        abort(404)
    recent = db.get_recent_scrobbles_for_track(artist_name, track_name)
    return render_template(
        "track_detail.html",
        active_tab="tracks",
        artist_name=artist_name,
        track_name=track_name,
        stats=stats,
        recent=recent,
    )