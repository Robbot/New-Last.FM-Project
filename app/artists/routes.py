import math
from flask import render_template, abort, request
import db
from . import artists_bp
from app.utils.range import compute_range


@artists_bp.route("/library/artists/<path:artist_name>")
def artist_detail(artist_name: str):

    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range(from_arg or None, to_arg or None, rangetype or None)
 
    stats = db.get_artist_stats(artist_name, start=start, end=end)
    
    if stats is None:
        abort(404, description="Artist not found")
    albums_rows = db.get_artist_albums(artist_name, start=start, end=end)          # NEW or existing query
    tracks_rows = db.get_top_tracks_for_artist(artist_name, start=start, end=end) # your new function

    return render_template(
        "artist_detail.html",
        active_tab="artists",
        artist_name=artist_name,
        start=start, end=end,
        stats=stats,
        albums_rows=albums_rows,
        tracks_rows=tracks_rows,
    )


@artists_bp.route("/library/artists")
def library_artists():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    sort_by = (request.args.get("sort_by") or "plays").strip()
    sort_order = (request.args.get("sort_order") or "desc").strip()

    print("=" * 60)
    print(f"Artists - URL params: from={from_arg}, to={to_arg}, rangetype={rangetype}, sort_by={sort_by}, sort_order={sort_order}")

    start, end = compute_range(from_arg or None, to_arg or None, rangetype or None)

    print(f"Artists - Computed range: start={start}, end={end}")

    stats = db.get_library_stats()
    rows = db.get_artists_details(start=start, end=end, sort_by=sort_by, sort_order=sort_order)

    print(f"Artists - Total rows returned: {len(rows)}")
    print("=" * 60)

    per_page = 50
    page = request.args.get("page", 1, type=int)
    total_rows = len(rows)
    total_pages = max(1, math.ceil(total_rows / per_page))


    # clamp page within range
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    rows = rows[offset:limit]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)

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
    )
