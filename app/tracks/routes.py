from flask import render_template, abort, request
import db
import math
from . import tracks_bp
from app.utils.range import compute_range_validated
from app.utils.validators import validate_int, validate_artist_name, validate_track_name
from app.utils.constants import PAGE_MIN

@tracks_bp.route("/library/tracks")
def library_tracks():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_track_stats()
    top_tracks = db.get_top_tracks(start=start, end=end)

    per_page = 50
    page = validate_int(request.args.get("page"), min_val=PAGE_MIN, default=1)
    total_rows = len(top_tracks)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    top_tracks = top_tracks[offset:limit]

    return render_template(
        "library_tracks.html",
        active_tab="tracks", 
        stats=stats, 
        top_tracks=top_tracks,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )

@tracks_bp.route("/library/track/<path:artist_name>/<path:track_name>")
def track_detail(artist_name, track_name):
    # Validate path parameters
    artist_name = validate_artist_name(artist_name)
    track_name = validate_track_name(track_name)

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