from flask import render_template, abort, redirect, request, url_for
from app import db
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
    search_term = (request.args.get("search") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_track_stats()
    top_tracks = db.get_top_tracks(start=start, end=end, search_term=search_term)

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
        total_rows=total_rows,
        per_page=per_page,
        from_arg=from_arg,
        to_arg=to_arg,
        rangetype=rangetype,
        search_term=search_term,
    )

@tracks_bp.route("/library/track")
def track_detail():
    """Show track details using query parameters for unambiguous names.

    Artist and track names may contain slashes (for example ``AC/DC``).  Two
    adjacent ``path`` converters cannot distinguish a slash that belongs to
    the artist from the separator before the track, so these values must not
    be encoded as path segments.
    """
    artist_name = validate_artist_name(request.args.get("artist_name"))
    track_name = validate_track_name(request.args.get("track_name"))
    if not artist_name or not track_name:
        abort(404)

    stats = db.get_track_stats_detail(artist_name, track_name)
    if stats is None:
        abort(404)
    recent = db.get_recent_scrobbles_for_track(artist_name, track_name)

    # Get MusicBrainz ID for track
    track_mbid = db.get_track_mbid(artist_name, track_name)

    return render_template(
        "track_detail.html",
        active_tab="tracks",
        artist_name=artist_name,
        track_name=track_name,
        stats=stats,
        recent=recent,
        track_mbid=track_mbid,
    )


@tracks_bp.route("/library/track/<path:artist_name>/<path:track_name>")
def track_detail_legacy(artist_name, track_name):
    """Redirect old path-based track URLs to the unambiguous query URL.

    Werkzeug assigns the first segment to ``artist_name``.  If that split does
    not identify a scrobbled track, try every later slash as the boundary; this
    recovers old links such as ``/library/track/AC/DC/Thunderstruck``.
    """
    candidates = [(artist_name, track_name)]
    combined = f"{artist_name}/{track_name}"
    candidates.extend(
        (combined[:index], combined[index + 1:])
        for index, char in enumerate(combined)
        if char == "/"
    )

    for candidate_artist, candidate_track in candidates:
        stats = db.get_track_stats_detail(candidate_artist, candidate_track)
        if stats and stats["plays"] > 0:
            return redirect(url_for(
                "tracks.track_detail",
                artist_name=candidate_artist,
                track_name=candidate_track,
            ))

    abort(404)
