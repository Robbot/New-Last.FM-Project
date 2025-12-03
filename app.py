from flask import Flask, render_template, request, url_for
# import csv
from datetime import datetime, timezone
import math
from db import get_db_connection

app = Flask(__name__)

# CSV_FILE = "files/lastfmstats.csv"


def ms_epoch_to_date(ms_str: str) -> str:
    ms_str = ms_str.strip().strip('"')
    if not ms_str:
        return ""
    try:
        ms = int(ms_str)
    except ValueError:
        return ""

    seconds = ms / 1000.0
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# def load_rows():
#     filtered_rows = []

    # with open(CSV_FILE, "r", encoding="utf-8") as f:
    #     reader = csv.reader(f, delimiter=';')

    #     # skip first CSV row if it’s a header / unwanted
    #     next(reader, None)

    #     for row in reader:
    #         if len(row) < 5:
    #             continue

    #         artist = row[0]
    #         album = row[1]
    #         track = row[3]
    #         epoch_raw = row[4]

    #         date_str = ms_epoch_to_date(epoch_raw)
    #         filtered_rows.append([artist, album, track, date_str])
    # filtered_rows.reverse()

    # return filtered_rows

# app.py

def get_latest_scrobbles():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT artist,
               album,
               track,
               strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        ORDER BY uts DESC
        """
    ).fetchall()
    conn.close()
    return rows

@app.route("/")
def index():
    # all_rows = load_rows()
    all_rows = get_latest_scrobbles()

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

# @app.route("/library/scrobbles")
# def library_scrobbles():
#     # query: total scrobbles, avg per day, latest tracks
#     stats = get_scrobble_stats()
#     recent = get_recent_scrobbles(limit=20)
#     return render_template("library_scrobbles.html",
#                            active_tab="scrobbles",
#                            stats=stats,
#                            rows=recent)

# @app.route("/library/artists")
# def library_artists():
#     stats = get_artist_stats()
#     top_artists = get_top_artists(limit=50)
#     return render_template("library_artists.html",
#                            active_tab="artists",
#                            stats=stats,
#                            rows=top_artists)

# @app.route("/library/albums")
# def library_albums():
#     stats = get_album_stats()
#     top_albums = get_top_albums(limit=50)
#     return render_template("library_albums.html",
#                            active_tab="albums",
#                            stats=stats,
#                            rows=top_albums)

# @app.route("/library/tracks")
# def library_tracks():
#     stats = get_track_stats()
#     top_tracks = get_top_tracks(limit=50)
#     return render_template("library_tracks.html",
#                            active_tab="tracks",
#                            stats=stats,
#                            rows=top_tracks)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8001)