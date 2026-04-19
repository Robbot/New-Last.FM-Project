from flask import render_template, request, current_app, abort
from app import db
import math
from . import compilations_bp
from app.utils.range import compute_range_validated
from app.utils.validators import validate_int, validate_album_name
from app.utils.constants import PAGE_MIN
from app.services.fetch_tracklist import fetch_album_tracklist_lastfm
from app.services.fetch_wikipedia import fetch_album_wikipedia_url


@compilations_bp.route("/library/compilations")
def library_compilations():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    search_term = (request.args.get("search") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_compilation_stats()
    top_compilations = db.get_top_compilations(start=start, end=end, search_term=search_term)

    per_page = 50
    page = validate_int(request.args.get("page"), min_val=PAGE_MIN, default=1)
    total_rows = len(top_compilations)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    top_compilations = top_compilations[offset:limit]

    return render_template(
        "library_compilations.html",
        active_tab="compilations",
        stats=stats,
        top_compilations=top_compilations,
        page=page,
        total_pages=total_pages,
        total_rows=total_rows,
        per_page=per_page,
        from_arg=from_arg,
        to_arg=to_arg,
        rangetype=rangetype,
        search_term=search_term,
    )


@compilations_bp.route("/library/compilations/<path:album_identifier>")
def compilation_detail(album_identifier: str):
    """
    Compilation detail page.
    album_identifier can be either:
    - An album_mbid (UUID format)
    - An album name (for albums without MBID or backward compatibility)
    """
    conn = db.get_db_connection()

    # Try to detect if this is an MBID (UUID-like format)
    # MBIDs are typically 36 character UUIDs with hyphens
    is_mbid = len(album_identifier) == 36 and album_identifier.count('-') == 4

    album_name = None
    album_mbid = None

    if is_mbid:
        # Look up album name by MBID
        row = conn.execute(
            """
            SELECT DISTINCT album, album_mbid
            FROM scrobble
            WHERE album_artist = 'Various Artists'
              AND album_mbid = ?
              AND album IS NOT NULL AND album != ''
            LIMIT 1
            """,
            (album_identifier,)
        ).fetchone()
        if row:
            album_name = row["album"]
            album_mbid = row["album_mbid"]
        conn.close()

        if not album_name:
            abort(404)
    else:
        # Validate album name
        album_name = validate_album_name(album_identifier)

        # Look up MBID for this album
        row = conn.execute(
            """
            SELECT album_mbid
            FROM scrobble
            WHERE album_artist = 'Various Artists'
              AND album = ?
            LIMIT 1
            """,
            (album_name,)
        ).fetchone()
        if row:
            album_mbid = row["album_mbid"]
        conn.close()

    # Process date range parameters
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    # Process sort parameter (default: tracklist)
    sort_by = request.args.get("sort", "tracklist")

    album_artist_name = "Various Artists"

    # First check if compilation has any plays in the database (all-time)
    all_time_total = db.get_album_total_plays_by_mbid(album_mbid, album_name) if album_mbid else db.get_album_total_plays(album_artist_name, album_name)
    if all_time_total == 0:
        abort(404)

    # Get plays within the date range (or all-time if no date filter)
    total = db.get_album_total_plays_by_mbid(album_mbid, album_name, start=start or "", end=end or "") if album_mbid else db.get_album_total_plays(album_artist_name, album_name, start=start or "", end=end or "")

    # Try to fetch tracklist if not already cached
    if not db.album_tracks_exist(album_artist_name, album_name):
        api_key = current_app.config["api_key"]
        tracks = fetch_album_tracklist_lastfm(api_key, album_artist_name, album_name)
        if tracks:  # Only insert if we got tracks back
            db.upsert_album_tracks(album_artist_name, album_name, tracks)

    # Get tracklist from database (may be empty if Last.fm doesn't have it)
    rows = db.get_album_tracks_by_mbid(album_mbid, album_name, start=start or "", end=end or "", sort_by=sort_by) if album_mbid else db.get_album_tracks(album_artist_name, album_name, start=start or "", end=end or "", sort_by=sort_by)

    art_row = db.get_album_art(album_artist_name, album_name)
    release_year = db.get_album_release_year(album_artist_name, album_name)

    artist_mbid = art_row["artist_mbid"] if art_row and art_row["artist_mbid"] else None
    image_xlarge = art_row["image_xlarge"] if art_row else None

    cache_key = album_mbid or f"{album_artist_name}_{album_name}"
    cover_url = db.ensure_album_art_cached(album_artist_name, album_name)

    # Fetch Wikipedia URL
    wikipedia_url = db.get_album_wikipedia_url(album_artist_name, album_name)
    if not wikipedia_url:
        # Try to fetch from Wikipedia API (tries English first, then Polish)
        wikipedia_url = fetch_album_wikipedia_url(album_artist_name, album_name)
        if wikipedia_url:
            # Store the result (including "N/A" to indicate search was executed)
            db.set_album_wikipedia_url(album_artist_name, album_name, wikipedia_url)

    # Get all artists on this compilation
    artists = db.get_compilation_artists_by_mbid(album_mbid, album_name) if album_mbid else db.get_compilation_artists(album_name)

    return render_template(
        "compilation_detail.html",
        active_tab="compilations",
        album_artist_name=album_artist_name,
        album_name=album_name,
        release_year=release_year,
        total_plays=total,
        all_time_total=all_time_total,
        tracks=rows,
        cover_url=cover_url,
        wikipedia_url=wikipedia_url,
        start=start,
        end=end,
        from_arg=from_arg,
        to_arg=to_arg,
        rangetype=rangetype,
        sort_by=sort_by,
        upload_allowed=_is_localhost_request(),
        album_mbid=album_mbid,
        artist_mbid=artist_mbid,
        artists=artists,
    )


def _is_localhost_request() -> bool:
    """Check if the request is coming from localhost or local network (192.168.x.x)."""
    remote_addr = request.remote_addr or ""
    # Check for localhost variants
    localhost_ips = {"127.0.0.1", "::1", "localhost"}
    # Also check if no X-Forwarded-For header (indicates direct local access)
    forwarded_for = request.headers.get("X-Forwarded-For", "")

    # Allow if remote_addr is localhost
    if remote_addr in localhost_ips:
        return True

    # Allow if remote_addr is in local network (192.168.0.0/16)
    if remote_addr.startswith("192.168."):
        return True

    # Allow IPv6 link-local addresses
    if remote_addr.startswith("fe80::"):
        return True

    # Allow if no forwarded header and remote is local
    if not forwarded_for and remote_addr in localhost_ips:
        return True

    return False
