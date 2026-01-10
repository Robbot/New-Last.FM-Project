from flask import render_template, abort, request
import db
import math
from . import tracks_bp
from app.utils.range import compute_range

@tracks_bp.route("/library/tracks")
def library_tracks():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_track_stats()
    top_tracks = db.get_top_tracks(start=start, end=end)

    per_page = 50
    page = request.args.get("page", 1, type=int)
    total_rows = len(top_tracks)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    top_tracks = top_tracks[offset:limit]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)

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