from flask import Flask, render_template, request, url_for
from datetime import datetime, timezone
import math
import db
from flask import abort

app = Flask(__name__)


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


def get_latest_scrobbles():
    conn = db.get_db_connection()
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

def average_scrobbles_per_day():
    conn = db.get_db_connection()
    row = conn.execute(
        """
        WITH bounds AS (
            SELECT
                MIN(uts) AS first_ts,
                MAX(uts) AS last_ts
            FROM scrobble
        ),
        calc AS (
            SELECT
                (SELECT COUNT(*) FROM scrobble) * 1.0
                / ((last_ts - first_ts) / 86400.0 + 1)
                AS per_day
            FROM bounds
        )
        SELECT ROUND(per_day) AS per_day_rounded
        FROM calc;
        """
    ).fetchone()
    conn.close()
       # row is a sqlite3.Row like {'per_day_rounded': 24}
    if row is None:
        return 0

    # either of these is fine, depending on your preference:
    # return int(row[0])
    return int(row["per_day_rounded"])


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

@app.route("/library/scrobbles")
def library_scrobbles():
    # query: total scrobbles, avg per day, latest tracks
    all_rows = get_latest_scrobbles()
    per_day = average_scrobbles_per_day()

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


def get_artist_stats():
    conn = db.get_db_connection()
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT artist) AS total_artists,
               COUNT(*) AS total_scrobbles
        FROM scrobble
        """
    ).fetchone()
    conn.close()
   
    if row is None:
        return {"total_artists": 0, "total_scrobbles": 0}

    return {
        "total_artists": row["total_artists"],
        "total_scrobbles": row["total_scrobbles"]
    }

def get_artists_details():
    conn = db.get_db_connection()
    rows = conn.execute(
        """
        SELECT artist, COUNT(*) AS plays
        FROM scrobble
        GROUP BY artist
        ORDER BY plays DESC
        """
    ).fetchall()
    conn.close()
    return rows


@app.route("/library/artists")
def library_artists():
    stats = get_artist_stats()
    rows = get_artists_details()
    # top_artists = get_top_artists(limit=50)
    return render_template("library_artists.html",
                           active_tab="artists",
                           stats=stats,
                           rows=rows)
                           

@app.route("/library/albums")
def library_albums():
    stats = get_album_stats()
    top_albums = get_top_albums(limit=50)
    return render_template("library_albums.html",
                           active_tab="albums",
                           stats=stats,
                           rows=top_albums)

@app.route("/library/tracks")
def library_tracks():
    stats = get_track_stats()
    top_tracks = get_top_tracks(limit=50)
    return render_template("library_tracks.html",
                           active_tab="tracks",
                           stats=stats,
                           rows=top_tracks)

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