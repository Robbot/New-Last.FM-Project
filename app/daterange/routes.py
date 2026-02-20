# app/blueprints/daterange.py
from __future__ import annotations

from flask import request, jsonify
import db
from . import daterange_bp


def _coerce_int(s: str | None, default: int | None = None) -> int | None:
    if s is None or s == "":
        return default
    try:
        return int(s)
    except ValueError:
        return default


def _played_at_expr() -> str:
    """Returns SQLite expression to convert uts to datetime string."""
    return "datetime(uts, 'unixepoch', 'localtime')"


@daterange_bp.route("", methods=["GET"])
@daterange_bp.route("/", methods=["GET"])
def daterange_index():
    # example: parse query params safely
    year = _coerce_int(request.args.get("year"))
    month = _coerce_int(request.args.get("month"))
    day = _coerce_int(request.args.get("day"))

    return jsonify({"year": year, "month": month, "day": day})


def _build_filters(args) -> tuple[str, list]:
    """
    Optional scoping so the same component can be reused across tabs.

    Supported query params:
      artist=...
      album=...
      track=...
    """
    where = []
    params: list = []

    artist = args.get("artist")
    album = args.get("album")
    track = args.get("track")

    if artist:
        where.append("artist = ?")
        params.append(artist)
    if album:
        where.append("album = ?")
        params.append(album)
    if track:
        where.append("track = ?")
        params.append(track)

    clause = ""
    if where:
        clause = " AND " + " AND ".join(where)

    return clause, params


@daterange_bp.get("/years")
def years():
    """
    Returns: [{year: 2011, count: 123}, ...]
    Always includes all years from 2010 to current year, even with 0 plays.
    """
    from datetime import datetime

    conn = db.get_db_connection()
    extra_clause, extra_params = _build_filters(request.args)

    rows = conn.execute(
        f"""
        SELECT
          CAST(strftime('%Y', {_played_at_expr()}) AS INTEGER) AS year,
          COUNT(*) AS count
        FROM scrobble
        WHERE uts IS NOT NULL
        {extra_clause}
        GROUP BY year
        ORDER BY year ASC
        """,
        extra_params,
    ).fetchall()

    # Build a dict of year -> count from the query results
    year_counts = {r["year"]: r["count"] for r in rows}

    # Generate all years from 2010 to current year
    current_year = datetime.now().year
    start_year = 2010

    result = []
    for year in range(start_year, current_year + 1):
        result.append({"year": year, "count": year_counts.get(year, 0)})

    return jsonify(result)


@daterange_bp.get("/months")
def months():
    """
    Query params: year=2011
    Returns: [{month: 1..12, count: N}, ...]
    """
    year = _coerce_int(request.args.get("year"))
    if not year:
        return jsonify({"error": "Missing year"}), 400

    conn = db.get_db_connection()
    extra_clause, extra_params = _build_filters(request.args)

    rows = conn.execute(
        f"""
        SELECT
          CAST(strftime('%m', {_played_at_expr()}) AS INTEGER) AS month,
          COUNT(*) AS count
        FROM scrobble
        WHERE CAST(strftime('%Y', {_played_at_expr()}) AS INTEGER) = ?
        {extra_clause}
        GROUP BY month
        ORDER BY month ASC
        """,
        [year, *extra_params],
    ).fetchall()

    return jsonify([{"month": r["month"], "count": r["count"]} for r in rows])


@daterange_bp.get("/days")
def days():
    """
    Query params: year=2011&month=11
    Returns: [{day: 1..31, count: N}, ...]
    """
    year = _coerce_int(request.args.get("year"))
    month = _coerce_int(request.args.get("month"))
    if not year or not month:
        return jsonify({"error": "Missing year or month"}), 400

    conn = db.get_db_connection()
    extra_clause, extra_params = _build_filters(request.args)

    rows = conn.execute(
        f"""
        SELECT
          CAST(strftime('%d', {_played_at_expr()}) AS INTEGER) AS day,
          COUNT(*) AS count
        FROM scrobble
        WHERE CAST(strftime('%Y', {_played_at_expr()}) AS INTEGER) = ?
          AND CAST(strftime('%m', {_played_at_expr()}) AS INTEGER) = ?
        {extra_clause}
        GROUP BY day
        ORDER BY day ASC
        """,
        [year, month, *extra_params],
    ).fetchall()

    return jsonify([{"day": r["day"], "count": r["count"]} for r in rows])


@daterange_bp.get("/results")
def results():
    """
    Query params:
      from=YYYY-MM-DD
      to=YYYY-MM-DD  (inclusive)
      limit=50
      (optional) artist=..., album=..., track=...
    Returns:
      {
        "range": {"from": "...", "to": "..."},
        "top_artists": [...],
        "top_albums": [...],
        "rows": [...]   # raw scrobbles (optional; used for daily)
      }
    """
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    limit = _coerce_int(request.args.get("limit"), 50) or 50

    if not date_from or not date_to:
        return jsonify({"error": "Missing from/to"}), 400

    # Inclusive date range; convert to datetime boundaries:
    # from: 00:00:00, to: 23:59:59
    dt_from = f"{date_from} 00:00:00"
    dt_to = f"{date_to} 23:59:59"

    conn = db.get_db_connection()
    extra_clause, extra_params = _build_filters(request.args)

    # Top artists in range
    top_artists = conn.execute(
        f"""
        SELECT artist, COUNT(*) AS plays
        FROM scrobble
        WHERE {_played_at_expr()} BETWEEN ? AND ?
        {extra_clause}
        GROUP BY artist
        ORDER BY plays DESC, artist ASC
        LIMIT ?
        """,
        [dt_from, dt_to, *extra_params, limit],
    ).fetchall()

    # Top albums in range
    top_albums = conn.execute(
        f"""
        SELECT artist, album, COUNT(*) AS plays
        FROM scrobble
        WHERE {_played_at_expr()} BETWEEN ? AND ?
        {extra_clause}
        GROUP BY artist, album
        ORDER BY plays DESC, artist ASC, album ASC
        LIMIT ?
        """,
        [dt_from, dt_to, *extra_params, limit],
    ).fetchall()

    # Raw scrobbles (useful for daily view)
    rows = conn.execute(
        f"""
        SELECT {_played_at_expr()} AS played_at, artist, album, track
        FROM scrobble
        WHERE {_played_at_expr()} BETWEEN ? AND ?
        {extra_clause}
        ORDER BY uts ASC
        LIMIT 500
        """,
        [dt_from, dt_to, *extra_params],
    ).fetchall()

    return jsonify(
        {
            "range": {"from": date_from, "to": date_to},
            "top_artists": [{"artist": r["artist"], "plays": r["plays"]} for r in top_artists],
            "top_albums": [{"artist": r["artist"], "album": r["album"], "plays": r["plays"]} for r in top_albums],
            "rows": [
                {"played_at": r["played_at"], "artist": r["artist"], "album": r["album"], "track": r["track"]}
                for r in rows
            ],
        }
    )
