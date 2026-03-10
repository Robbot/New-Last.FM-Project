from flask import abort, render_template, request, current_app, jsonify, url_for
from werkzeug.exceptions import RequestEntityTooLarge
from app.services.fetch_tracklist import fetch_album_tracklist_lastfm
from app.services.fetch_wikipedia import fetch_album_wikipedia_url
from app import db
import math
from . import albums_bp
from app.utils.range import compute_range_validated
from app.utils.validators import validate_int, validate_enum, validate_artist_name, validate_album_name
from app.utils.constants import (
    PAGE_MIN,
    ALLOWED_ALBUM_SORT,
    DEFAULT_ALBUM_SORT,
)

@albums_bp.route("/library/albums")
def library_albums():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    search_term = (request.args.get("search") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    stats = db.get_album_stats()
    top_albums = db.get_top_albums(start=start, end=end, search_term=search_term)

    per_page = 50
    page = validate_int(request.args.get("page"), min_val=PAGE_MIN, default=1)
    total_rows = len(top_albums)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    top_albums = top_albums[offset:limit]

    return render_template(
        "library_albums.html",
         active_tab="albums",
           stats=stats,
           top_albums=top_albums,
           page=page,
           total_pages=total_pages,
           per_page=per_page,
           from_arg=from_arg,
           to_arg=to_arg,
           rangetype=rangetype,
           search_term=search_term,
    )


@albums_bp.route("/library/artists/<path:album_artist_name>/albums/<path:album_name>")
def artist_album_detail(album_artist_name: str, album_name: str):
    # Validate path parameters
    album_artist_name = validate_artist_name(album_artist_name)
    album_name = validate_album_name(album_name)

    # Process date range parameters
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range_validated(from_arg or None, to_arg or None, rangetype or None)

    # Process sort parameter (default: tracklist)
    sort_by = validate_enum(
        request.args.get("sort"),
        ALLOWED_ALBUM_SORT,
        DEFAULT_ALBUM_SORT,
        case_sensitive=False,
    )

    # First check if album has any plays in the database (all-time)
    all_time_total = db.get_album_total_plays(album_artist_name, album_name)
    if all_time_total == 0:
        abort(404)

    # Get plays within the date range (or all-time if no date filter)
    total = db.get_album_total_plays(album_artist_name, album_name, start=start or "", end=end or "")

    # Try to fetch tracklist if not already cached
    if not db.album_tracks_exist(album_artist_name, album_name):
        api_key = current_app.config["api_key"]
        tracks = fetch_album_tracklist_lastfm(api_key, album_artist_name, album_name)
        if tracks:  # Only insert if we got tracks back
            db.upsert_album_tracks(album_artist_name, album_name, tracks)

    # Get tracklist from database (may be empty if Last.fm doesn't have it)
    rows = db.get_album_tracks(album_artist_name, album_name, start=start or "", end=end or "", sort_by=sort_by)

    art_row = db.get_album_art(album_artist_name, album_name)
    release_year = db.get_album_release_year(album_artist_name, album_name)

    album_mbid = art_row["album_mbid"] if art_row and art_row["album_mbid"] else None
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

    return render_template(
        "album_detail.html",
        active_tab="albums",
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
    )


@albums_bp.route("/library/artists/<path:album_artist_name>/albums/<path:album_name>/upload-cover", methods=["POST"])
def upload_album_cover(album_artist_name: str, album_name: str):
    """Handle album cover upload. Only allowed from localhost or local network (192.168.x.x)."""
    from app.logging_config import get_logger
    logger = get_logger(__name__)

    # Security: Only allow uploads from localhost or local network
    if not _is_localhost_request():
        logger.warning(f"Upload attempt from non-local network: {request.remote_addr}")
        return jsonify({"error": "Uploads are only allowed from local network"}), 403

    # Validate path parameters
    album_artist_name = validate_artist_name(album_artist_name)
    album_name = validate_album_name(album_name)

    # Check if album exists
    if db.get_album_total_plays(album_artist_name, album_name) == 0:
        return jsonify({"error": "Album not found"}), 404

    # Check if file is present
    if "cover" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["cover"]

    # Check if filename is empty
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    # Validate and process the image
    result = db.save_uploaded_cover(album_artist_name, album_name, file)

    if result.get("error"):
        logger.error(f"Cover upload failed for {album_artist_name} - {album_name}: {result['error']}")
        return jsonify(result), 400

    logger.info(f"Cover uploaded successfully for {album_artist_name} - {album_name}")
    return jsonify({
        "success": True,
        "cover_url": result["cover_url"]
    })


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