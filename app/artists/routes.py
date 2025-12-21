from flask import Blueprint, render_template
import db

# 1) artists details: /artist/<artist_name>
artists_bp = Blueprint("artists", __name__, url_prefix="/artist")

@artists_bp.get("/<artist_name>")
def artist_detail(artist_name: str):
 
    stats = db.get_artist_stats(artist_name)
    albums_rows = db.get_artist_albums(artist_name)          # NEW or existing query
    tracks_rows = db.get_top_tracks_for_artist(artist_name) # your new function



    return render_template(
        "artist_detail.html",
        active_tab="artists",
        artist_name=artist_name,
        stats=stats,
        albums_rows=albums_rows,
        tracks_rows=tracks_rows,
    )

# 2) artists list: /library/artists

artists_library_bp = Blueprint("artists_library", __name__, url_prefix="/library")

@artists_library_bp.get("/artists")
def library_artists():
    stats = db.get_library_stats()
    rows = db.get_artists_details()

    return render_template(
        "library_artists.html",
        active_tab="artists",
        stats=stats,
        rows=rows,
    )
