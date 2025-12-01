#!/usr/bin/env python3
import os
import time
import sqlite3
import requests

API_KEY = os.environ["LASTFM_API_KEY"]
USERNAME = "your_lastfm_username"  # <- change this
DB_PATH = "files/lastfmstats.sqlite"  # <- change if needed
BASE_URL = "https://ws.audioscrobbler.com/2.0/"

def get_last_uts(conn):
    """Return latest uts from scrobble table (0 if empty)."""
    cur = conn.cursor()
    # use uts if present, otherwise fall back to date column
    try:
        cur.execute("SELECT COALESCE(MAX(uts), 0) FROM scrobble;")
    except sqlite3.OperationalError:
        cur.execute("SELECT COALESCE(MAX(date), 0) FROM scrobble;")
    row = cur.fetchone()
    return row[0] or 0

def fetch_recent_tracks(from_ts=None, page=1, limit=200):
    """Call user.getRecentTracks for a single page."""
    params = {
        "method": "user.getRecentTracks",
        "user": USERNAME,
        "api_key": API_KEY,
        "format": "json",
        "limit": limit,
        "page": page,
    }
    if from_ts:
        params["from"] = int(from_ts)

    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # Handle API-level errors (Last.fm returns them in JSON body)
    if "error" in data:
        raise RuntimeError(f"Last.fm API error {data['error']}: {data.get('message')}")

    return data

def sync_scrobbles():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    last_uts = get_last_uts(conn)
    print(f"Last known uts in DB: {last_uts}")

    page = 1
    total_inserted = 0

    while True:
        data = fetch_recent_tracks(from_ts=last_uts, page=page)
        recent = data.get("recenttracks", {})
        tracks = recent.get("track", [])

        # Last.fm can return a single object instead of a list
        if isinstance(tracks, dict):
            tracks = [tracks]

        batch = []

        for t in tracks:
            # Skip currently playing track (no date/uts, not yet scrobbled)
            if "@attr" in t and t["@attr"].get("nowplaying") == "true":
                continue

            date_info = t.get("date")
            if not date_info:
                continue

            uts = int(date_info["uts"])
            artist = t["artist"]["#text"]
            track = t["name"]
            album = t["album"]["#text"]
            # album may be dict or string depending on serialization
            album_mbid = None
            if isinstance(t.get("album"), dict):
                album_mbid = t["album"].get("mbid")

            track_mbid = t.get("mbid")

            batch.append((artist, album, album_mbid, track, uts, track_mbid))

        if not batch:
            print("No new tracks to insert on this page, stopping.")
            break

        # Adjust column list to match your table structure
        conn.executemany(
            """
            INSERT OR IGNORE INTO scrobble
                (artist, album, album_id, track, uts, track_mbid)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            batch,
        )
        conn.commit()

        inserted = conn.total_changes - total_inserted
        total_inserted = conn.total_changes
        print(f"Page {page}: inserted {inserted} rows (batch size {len(batch)})")

        # pagination info
        attr = recent.get("@attr", {})
        total_pages = int(attr.get("totalPages", page))
        if page >= total_pages:
            break

        page += 1
        # polite rate limiting: ~5 requests/sec is generally safe
        time.sleep(0.25)

    conn.close()
    print(f"Done. Total inserted rows (new): {total_inserted}")

if __name__ == "__main__":
    sync_scrobbles()
