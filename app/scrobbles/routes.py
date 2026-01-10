import math
from flask import Blueprint, render_template, request
import db
from . import scrobbles_bp
from app.utils.range import compute_range

@scrobbles_bp.route("/library/scrobbles")
def library_scrobbles():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range(from_arg or None, to_arg or None, rangetype or None)

    # query: total scrobbles, avg per day, latest tracks
    all_rows = db.get_latest_scrobbles(start=start, end=end)
    per_day = db.average_scrobbles_per_day()

    per_page = 50
    page = request.args.get("page", 1, type=int)

    total_rows = len(all_rows)
    total_pages = max(1, math.ceil(total_rows / per_page))
    
    # clamp page within range
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    page_rows = all_rows[offset:limit]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)

    return render_template("library_scrobbles.html",
                            active_tab="scrobbles",
                            rows=page_rows,
                            page=page,
                            total_pages=total_pages,
                            total_rows=total_rows,
                            per_day=per_day 
                        )