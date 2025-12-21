from flask import render_template
import db
from . import albums_bp

@albums_bp.route("/library/albums")
def library_albums():
    stats = db.get_album_stats()
    top_albums = db.get_top_albums()
    return render_template("library_albums.html", active_tab="albums", stats=stats, top_albums=top_albums)
