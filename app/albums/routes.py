from flask import render_template, request
import db
import math
from . import albums_bp

@albums_bp.route("/library/albums")
def library_albums():
    stats = db.get_album_stats()
    top_albums = db.get_top_albums()

    per_page = 50
    page = request.args.get("page", 1, type=int)
    total_rows = len(top_albums)
    total_pages = max(1, math.ceil(total_rows / per_page))  

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    top_albums = top_albums[start:end]

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

    rows = db.get_album_tracks(artist_name, album_name)

    album_mbid = art_row["album_mbid"] if art_row else ""
    cover_url = ensure_album_art_cached(album_mbid)

    return render_template(
        "album_detail.html",
        artist_name=artist_name,
        album_name=album_name,
        total_plays=total,
        tracks=rows,
        cover_url=cover_url,
    )