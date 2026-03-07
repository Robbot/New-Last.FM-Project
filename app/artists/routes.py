import math
from flask import render_template, abort, request
import db
from . import artists_bp
from app.utils.range import compute_range_validated
from app.utils.validators import validate_int, validate_enum, validate_artist_name
from app.utils.constants import (
    PAGE_MIN,
    ALLOWED_SORT_BY,
    ALLOWED_SORT_ORDER,
    DEFAULT_SORT_BY,
    DEFAULT_SORT_ORDER,
)


@artists_bp.route("/library/artists/<path:artist_name>")
def artist_detail(artist_name: str):
    # Validate path parameter
    artist_name = validate_artist_name(artist_name)

    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_artist_stats(artist_name, start=start, end=end)

    if stats is None:
        abort(404, description="Artist not found")
    albums_rows = db.get_artist_albums(artist_name, start=start, end=end)          # NEW or existing query
    tracks_rows = db.get_top_tracks_for_artist(artist_name, start=start, end=end) # your new function
    artist_position = db.get_artist_position(artist_name, start=start, end=end)

    return render_template(
        "artist_detail.html",
        active_tab="artists",
        artist_name=artist_name,
        start=start, end=end,
        stats=stats,
        albums_rows=albums_rows,
        tracks_rows=tracks_rows,
        artist_position=artist_position,
    )


@artists_bp.route("/library/artists")
def library_artists():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    search_term = (request.args.get("search") or "").strip()
    sort_by = validate_enum(
        request.args.get("sort_by"),
        ALLOWED_SORT_BY,
        DEFAULT_SORT_BY,
        case_sensitive=False,
    )
    sort_order = validate_enum(
        request.args.get("sort_order"),
        ALLOWED_SORT_ORDER,
        DEFAULT_SORT_ORDER,
        case_sensitive=False,
    )

    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_library_stats()
    rows = db.get_artists_details(start=start, end=end, sort_by=sort_by, sort_order=sort_order, search_term=search_term)

    per_page = 50
    page = validate_int(request.args.get("page"), min_val=PAGE_MIN, default=1)
    total_rows = len(rows)
    total_pages = max(1, math.ceil(total_rows / per_page))

    # clamp page within range
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    rows = rows[offset:limit]

    # Determine current sort state for each column
    current_sort = {"by": sort_by, "order": sort_order}


    return render_template(
        "library_artists.html",
        active_tab="artists",
        stats=stats,
        rows=rows,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
        current_sort=current_sort,
        from_arg=from_arg,
        to_arg=to_arg,
        rangetype=rangetype,
        search_term=search_term,
    )
