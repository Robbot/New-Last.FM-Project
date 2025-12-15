from flask import Flask, render_template, request, url_for
from datetime import datetime, timezone
import math
import db
from flask import abort

app = Flask(__name__)


# def ms_epoch_to_date(ms_str: str) -> str:
#     ms_str = ms_str.strip().strip('"')
#     if not ms_str:
#         return ""
#     try:
#         ms = int(ms_str)
#     except ValueError:
#         return ""

#     seconds = ms / 1000.0
#     dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
#     return dt.strftime("%Y-%m-%d %H:%M:%S")




# keep this for possible future use when starting date range is needed
# def average_scrobbles_per_day():
#     conn = db.get_db_connection()
#     result = conn.execute(
#         """
#         SELECT COUNT(*) as total_scrobbles,
#                (julianday('now') - julianday(MIN(strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime')))) AS days_active
#         FROM scrobble
#         """
#     ).fetchone()
#     conn.close()
#     if result and result['days_active'] > 0:
#         return result['total_scrobbles'] / result['days_active']
#     return 0

@app.route("/")
def index():
    # all_rows = load_rows()
    all_rows = db.get_latest_scrobbles()

    per_page = 50
    page = request.args.get("page", 1, type=int)

    total_rows = len(all_rows)
    total_pages = max(1, math.ceil(total_rows / per_page))

    # clamp page within range
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page - 1) * per_page
    end = start + per_page
    page_rows = all_rows[start:end]

    print("total_rows:", total_rows)
    print("per_page:", per_page)
    print("total_pages:", total_pages)
    print("current page:", page)


    return render_template(
        "table.html",
        rows=page_rows,
        page=page,
        total_pages=total_pages,
        total_rows=total_rows,
    )

@app.route("/library/scrobbles")
def library_scrobbles():
    # query: total scrobbles, avg per day, latest tracks
    all_rows = db.get_latest_scrobbles()
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

    start = (page - 1) * per_page
    end = start + per_page
    page_rows = all_rows[start:end]

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



@app.route("/library/artists")
def library_artists():
    stats = db.get_artist_stats()
    rows = db.get_artists_details()
    # top_artists = get_top_artists(limit=50)
    return render_template("library_artists.html",
                           active_tab="artists",
                           stats=stats,
                           rows=rows)
                           

@app.route("/library/albums")
def library_albums():
    stats = db.get_album_stats()
    top_albums = db.get_top_albums()
    return render_template("library_albums.html",
                           active_tab="albums",
                           stats=stats,
                           top_albums=top_albums)


@app.route("/library/tracks")
def library_tracks():
    stats = db.get_track_stats()
    top_tracks = db.get_top_tracks()
    return render_template("library_tracks.html",
                           active_tab="tracks",
                           stats=stats,
                           top_tracks=top_tracks)

@app.route("/library/track/<path:artist_name>/<path:track_name>")
def track_detail(artist_name, track_name):
    # stats = db.get_track_overview(track_name)
    # if stats is None:
    #     abort(404)

    # albums = db.get_track_albums(track_name)
    # artists = db.get_track_artists(track_name)

    # return render_template(
    #     "track_detail.html",
    #     active_tab="tracks",      # keeps the Tracks tab highlighted
    #     track_name=track_name,
    #     artist_name=artist_name,
    #     stats=stats,
    #     albums=albums,
    #     artists=artists,
    # )

    return f"Track detail page for {artist_name} - {track_name} (not implemented yet)"
# TODO: replace plain string with track_detail.html + DB stats
def artist_detail(artist_name):
    return render_template(
        "artist_detail.html",
        active_tab="artists",
        artist_name=artist_name
    )

@app.route("/library/artist/<path:artist_name>")
def artist_detail(artist_name):
    stats = db.get_artist_overview(artist_name)
    if stats is None:
        abort(404)

    albums = db.get_artist_albums(artist_name)
    tracks = db.get_artist_tracks(artist_name)

    return render_template(
        "artist_detail.html",
        active_tab="artists",      # keeps the Artists tab highlighted
        artist_name=artist_name,
        stats=stats,
        albums=albums,
        tracks=tracks,
    )

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8001)