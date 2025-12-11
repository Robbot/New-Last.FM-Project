import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

def get_db_connection() ->sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

def get_artist_stats():
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