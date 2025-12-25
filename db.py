from os import abort
import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

def get_db_connection() ->sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def average_scrobbles_per_day():
    conn = get_db_connection()
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

def get_artist_overview(artist_name: str):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*)               AS scrobbles,
            COUNT(DISTINCT album)  AS albums,
            COUNT(DISTINCT track)  AS tracks
        FROM scrobble
        WHERE artist = ?
        """,
        (artist_name,),
    ).fetchone()
    conn.close()

    if row is None or row["scrobbles"] == 0:
        return None

    return {
        "scrobbles": row["scrobbles"],
        "albums": row["albums"],
        "tracks": row["tracks"],
    }

def get_library_stats():
    conn = get_db_connection()
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

def get_artist_stats(artist_name: str):
    conn = get_db_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) AS scrobbles,
            COUNT(DISTINCT album) AS albums,
            COUNT(DISTINCT track) AS tracks
        FROM scrobble
        WHERE artist = ?
    """, (artist_name,)).fetchone()
    conn.close()

    return row

def get_top_tracks_for_artist(artist_name):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT
            artist,
            track,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
        GROUP BY track
        ORDER BY plays DESC
    """, (artist_name,)).fetchall()
    conn.close()
    return rows

def get_artists_details():
    conn = get_db_connection()
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


def get_artist_albums(artist_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
        GROUP BY album
        ORDER BY plays DESC
        """,
        (artist_name,),
    ).fetchall()
    conn.close()
    return rows


def get_artist_tracks(artist_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            track,
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE artist = ?
        GROUP BY track, album
        ORDER BY plays DESC
        """,
        (artist_name,),
    ).fetchall()
    conn.close()
    return rows

def get_album_stats():
    """Total distinct albums and total album scrobbles."""
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT album) AS total_albums,
            COUNT(*)              AS total_scrobbles
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_albums": 0, "total_scrobbles": 0}

    return {
        "total_albums": row["total_albums"],
        "total_scrobbles": row["total_scrobbles"],
    }

def get_top_albums():
    """Albums sorted by plays (scrobbles) desc."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            album,
            artist,
            COUNT(*) AS plays
        FROM scrobble
        WHERE album IS NOT NULL AND album != ''
        GROUP BY album, artist
        ORDER BY plays DESC
        """,
    ).fetchall()
    conn.close()
    return rows

def get_track_stats():
    conn = get_db_connection()
    row = conn.execute(
         """
        SELECT
            COUNT(DISTINCT track) AS total_tracks
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        Group BY track
        Order BY total_tracks DESC
        """
    ).fetchone()
    conn.close()

    if row is None:
        return {"total_tracks": 0}
    return {
        "most_tracks": row["total_tracks"]
    }

def get_track_stats_detail(artist_name: str, track_name: str):
    conn = get_db_connection()
    row = conn.execute(
         """
        SELECT
            COUNT(*) AS plays
        FROM scrobble
        WHERE lower(trim(artist)) = lower(trim(?)) and lower(trim(track)) = lower(trim(?))
        """,
        (artist_name, track_name),
    ).fetchone()
    conn.close()
    return row

def get_recent_scrobbles_for_track(artist_name: str, track_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            artist,
            album,
            track,
            strftime('%Y-%m-%d %H:%M:%S', uts, 'unixepoch', 'localtime') AS date
        FROM scrobble
        WHERE
            LOWER(TRIM(artist)) = LOWER(TRIM(?))
            AND LOWER(TRIM(track))  = LOWER(TRIM(?))
        ORDER BY uts DESC
        """,
        (artist_name, track_name),
    ).fetchall()
    conn.close()
    return rows


def get_top_tracks():
    """Tracks sorted by plays (scrobbles) desc."""
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
            track,
            artist,
            album,
            COUNT(*) AS plays
        FROM scrobble
        WHERE track IS NOT NULL AND track != ''
        GROUP BY track, artist, album
        ORDER BY plays DESC
        """,
    ).fetchall()
    conn.close()
    return rows

def get_track_overview(artist_name: str, track_name: str):
    conn = get_db_connection()
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS plays,
        FROM scrobble
        WHERE 
            LOWER(TRIM(artist)) = LOWER(TRIM(?))
            and LOWER(TRIM(track)) = LOWER(TRIM(?))
        """,
        (artist_name, track_name),
    ).fetchone()
    conn.close()

    if row is None or row["scrobbles"] == 0:
        return None

    return {
        "scrobbles": row["scrobbles"],
        "albums": row["albums"],
    }

def get_album_tracks(artist_name: str, album_name: str):
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT
          at.track_number AS track_number,
          s.track         AS track_name,
          COALESCE(s.plays, 0) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble_stats s
          ON s.artist = at.artist
         AND s.album  = at.album
         AND s.track  = at.track
        WHERE at.artist = ?
          AND at.album  = ?
        ORDER BY at.track_number ASC
        """,
        (artist_name, album_name),
    ).fetchall()
    conn.close()

    if not rows:
        # Fallback: if you *do* store track_number directly in stats:
        rows = db.execute(
            """
            SELECT
              track_number,
              track AS track_name,
              COALESCE(plays, 0) AS plays
            FROM scrobble_stats
            WHERE artist = ?
              AND album  = ?
            ORDER BY track_number ASC
            """,
            (artist_name, album_name),
        ).fetchall()

    if not rows:
        abort(404)

    # 2) Total album plays
def get_album_total_plays(artist_name, album_name):
    
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT COALESCE(SUM(plays), 0) AS total
        FROM scrobble_stats
        WHERE artist = ?
          AND album  = ?
        """,
        (artist_name, album_name),
        one=True,
    )
    return row["total"] if row else 0

    # 3) Album art MBID lookup from album_art table
def get_album_art(artist_name, album_name):
    
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT album_mbid, image_xlarge
        FROM album_art
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (artist_name, album_name),
    ).fetchone()
    conn.close()

def album_tracks_exist(artist_name, album_name):
    db = get_db()
    row = db.execute(
        """
        SELECT 1
        FROM album_tracks
        WHERE artist = ?
          AND album  = ?
        LIMIT 1
        """,
        (artist_name, album_name),
    ).fetchone()
    return row is not None

def upsert_album_tracks(artist_name, album_name, tracks):
    """
    tracks = list of dicts:
      [{"track": "The Grudge", "track_number": 1}, ...]
    """
    db = get_db()
    db.executemany(
        """
        INSERT OR REPLACE INTO album_tracks (artist, album, track, track_number)
        VALUES (?, ?, ?, ?)
        """,
        [(artist_name, album_name, t["track"], t["track_number"]) for t in tracks],
    )
    db.commit()

def get_album_tracks(artist_name, album_name):
    db = get_db()
    cur = db.execute(
        """
        SELECT
            at.track_number,
            COALESCE(s.track, at.track) AS track_name,
            COALESCE(s.plays, 0) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble_stats s
          ON s.artist = at.artist
         AND s.album  = at.album
         AND s.track  = at.track
        WHERE at.artist = ?
          AND at.album  = ?
        ORDER BY at.track_number ASC
        """,
        (artist_name, album_name),
    )
    return cur.fetchall()
