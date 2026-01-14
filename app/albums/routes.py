from flask import abort, render_template, request, current_app
from app.services.fetch_tracklist import fetch_album_tracklist_lastfm
import db
import math
from . import albums_bp
from app.utils.range import compute_range

@albums_bp.route("/library/albums")
def library_albums():
    from_arg = (request.args.get("from") or request.args.get("start") or "").strip()
    to_arg = (request.args.get("to") or request.args.get("end") or "").strip()
    rangetype = (request.args.get("rangetype") or "").strip()
    start, end = compute_range(from_arg or None, to_arg or None, rangetype or None)

    print(f"Albums - Date params: from={from_arg}, to={to_arg}, rangetype={rangetype}")
    print(f"Albums - Computed range: start={start}, end={end}")

    stats = db.get_album_stats()
    top_albums = db.get_top_albums(start=start, end=end)

    per_page = 50
    page = request.args.get("page", 1, type=int)
    total_rows = len(top_albums)
    total_pages = max(1, math.ceil(total_rows / per_page))

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    offset = (page - 1) * per_page
    limit = offset + per_page
    top_albums = top_albums[offset:limit]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)



    return render_template(
        "library_albums.html",
         active_tab="albums",
           stats=stats, 
           top_albums=top_albums,
           page=page,
           total_pages=total_pages,
           per_page=per_page,
    )


@albums_bp.route("/library/artists/<artist_name>/albums/<album_name>")
def artist_album_detail(artist_name: str, album_name: str):
    # Verify the album exists in our scrobbles
    total = db.get_album_total_plays(artist_name, album_name)
    if total == 0:
        abort(404)

    # Try to fetch tracklist if not already cached
    if not db.album_tracks_exist(artist_name, album_name):
        api_key = current_app.config["api_key"]
        tracks = fetch_album_tracklist_lastfm(api_key, artist_name, album_name)
        if tracks:  # Only insert if we got tracks back
            db.upsert_album_tracks(artist_name, album_name, tracks)

    # Get tracklist from database (may be empty if Last.fm doesn't have it)
    rows = db.get_album_tracks(artist_name, album_name)

    art_row = db.get_album_art(artist_name, album_name)
    release_year = db.get_album_release_year(artist_name, album_name)

    album_mbid = art_row["album_mbid"] if art_row and art_row["album_mbid"] else None
    image_xlarge = art_row["image_xlarge"] if art_row else None

    cache_key = album_mbid or f"{artist_name}_{album_name}"
    cover_url = db.ensure_album_art_cached(artist_name, album_name)

    return render_template(
        "album_detail.html",
        active_tab="albums",
        artist_name=artist_name,
        album_name=album_name,
        release_year=release_year,
        total_plays=total,
        tracks=rows,
        cover_url=cover_url,
    )