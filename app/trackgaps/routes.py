from flask import render_template, request
import db
import math
from . import trackgaps_bp
from app.utils.range import compute_range_validated
from app.utils.validators import validate_int
from app.utils.constants import PAGE_MIN

@trackgaps_bp.route("/library/trackgaps")
def library_trackgaps():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    track_gaps = db.get_track_gaps(start=start, end=end)

    per_page = 50
    page = validate_int(request.args.get("page"), min_val=PAGE_MIN, default=1)
    total_rows = len(track_gaps)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    track_gaps = track_gaps[offset:limit]

    return render_template(
        "library_trackgaps.html",
        active_tab="trackgaps",
        track_gaps=track_gaps,
        page=page,
        total_pages=total_pages,
        per_page=per_page,
    )
