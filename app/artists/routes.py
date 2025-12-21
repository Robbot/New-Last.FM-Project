from flask import Blueprint, render_template
import db

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
