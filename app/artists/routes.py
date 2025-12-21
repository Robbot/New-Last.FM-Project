from flask import render_template, abort
import db
from . import artists_bp


@artists_bp.route("/library/artists/<path:artist_name>")
def artist_detail(artist_name: str):
 
    stats = db.get_artist_stats(artist_name)
    if stats is None:
        abort(404, description="Artist not found")
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


@artists_bp.route("/library/artists")
def library_artists():
    stats = db.get_library_stats()
    rows = db.get_artists_details()

    return render_template(
        "library_artists.html",
        active_tab="artists",
        stats=stats,
        rows=rows,
    )
