#!/usr/bin/env python3
"""
Sync Last.fm scrobbles into SQLite.

- Uses API key + username from config.ini via config.get_api_key()
- Stores uts as INTEGER Unix timestamp in SECONDS (UTC)
- Inserts scrobbles in chronological order (oldest -> newest)
- Avoids duplicates via UNIQUE index on (uts, artist, album, track)
- Populates album_art with cover URLs per album_mbid
"""

import time
import sqlite3
import requests

from config import get_api_key  # your helper: returns (api_key, username)

DB_PATH = "files/lastfmstats.sqlite"   # adjust if needed
BASE_URL = "https://ws.audioscrobbler.com/2.0/"


# ---------- DB helpers ----------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()

    # Main scrobble table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS scrobble (
            id          INTEGER PRIMARY KEY,
            artist      TEXT NOT NULL,
            artist_mbid TEXT,
            album       TEXT NOT NULL,
            album_mbid  TEXT,
            track       TEXT NOT NULL,
            track_mbid  TEXT,
            uts         INTEGER NOT NULL
        );
    """)

    # Unique scrobble key: one row per (time, artist, album, track)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scrobble_unique
        ON scrobble(uts, artist, album, track);
    """)

    # Album artwork / metadata
    cur.execute("""
        CREATE TABLE IF NOT EXISTS album_art (
            album_mbid       TEXT PRIMARY KEY,
            artist_mbid      TEXT,
            artist           TEXT,
            album            TEXT,
            image_small      TEXT,
            image_medium     TEXT,
            image_large      TEXT,
            image_xlarge     TEXT,
            last_updated  INTEGER
        );
    """)

    conn.commit()


def get_last_uts(conn: sqlite3.Connection) -> int:
    """Return latest uts in seconds (0 if table empty)."""
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(MAX(uts), 0) FROM scrobble;")
    (val,) = cur.fetchone()
    return int(val or 0)


# ---------- Last.fm API ----------

def fetch_recent_tracks(api_key: str,
                        username: str,
                        from_ts: int | None,
                        page: int,
                        limit: int = 200) -> dict:
    """Call user.getRecentTracks for one page."""
    params = {
        "method": "user.getRecentTracks",
        "user": username,
        "api_key": api_key,
        "format": "json",
        "limit": limit,
        "page": page,
    }
    if from_ts is not None:
        params["from"] = int(from_ts)

    resp = requests.get(BASE_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Last.fm API error {data['error']}: {data.get('message')}")

    return data


# ---------- Sync logic ----------

def sync_lastfm() -> None:
    api_key, username = get_api_key()
    print(f"Loaded API key + username from config.ini: user={username}")

    conn = get_conn()
    ensure_schema(conn)

    last_uts = get_last_uts(conn)
    print(f"Last known uts in DB (seconds): {last_uts}")

    # Avoid inclusive-from duplicates: Last.fm returns uts >= from
    from_ts = None if last_uts == 0 else last_uts + 1

    total_new_scrobbles = 0
    page = 1

    while True:
        print(f"\nFetching page {page} from_ts={from_ts} ...")
        data = fetch_recent_tracks(api_key, username, from_ts, page)
        recent = data.get("recenttracks", {})
        tracks = recent.get("track", [])

        if isinstance(tracks, dict):
            tracks = [tracks]

        scrobble_batch: list[tuple] = []
        album_batch: list[dict] = []
        now_ts = int(time.time())

        for t in tracks:
            # Skip "now playing" items (not yet scrobbled)
            if "@attr" in t and t["@attr"].get("nowplaying") == "true":
                continue

            date_info = t.get("date")
            if not date_info:
                continue

            uts = int(date_info["uts"])  # Last.fm gives seconds

            # Sanity: if somehow ms sneaks in, normalize to seconds
            if uts > 2_000_000_000:
                uts //= 1000

            artist_name = t["artist"]["#text"]
            artist_mbid = t["artist"].get("mbid") or None

            if isinstance(t.get("album"), dict):
                album_name = t["album"]["#text"]
                album_mbid = t["album"].get("mbid") or None
            else:
                album_name = t.get("album", "")
                album_mbid = None

            if album_mbid == "":
                album_mbid = None

            track_name = t["name"]
            track_mbid = t.get("mbid") or None

            scrobble_batch.append(
                (artist_name, artist_mbid, album_name,
                 album_mbid, track_name, track_mbid, uts)
            )

            # Collect album_art info when album_mbid is present
            if album_mbid:
                images = t.get("image", []) or []
                img_small = img_medium = img_large = img_xlarge = None

                for img in images:
                    url = img.get("#text") or None
                    size = img.get("size")
                    if not url:
                        continue
                    if size == "small":
                        img_small = url
                    elif size == "medium":
                        img_medium = url
                    elif size == "large":
                        img_large = url
                    elif size in ("extralarge", "mega"):
                        img_xlarge = url

                album_batch.append({
                    "album_mbid": album_mbid,
                    "artist_mbid": artist_mbid,
                    "artist": artist_name,
                    "album": album_name,
                    "image_small": img_small,
                    "image_medium": img_medium,
                    "image_large": img_large,
                    "image_xlarge": img_xlarge,
                    "last_updated": now_ts,
                })

        if not scrobble_batch:
            print("No new scrobbles on this page. Stopping.")
            break

        # 🔢 Sort scrobbles chronologically (oldest → newest) before insert
        scrobble_batch.sort(key=lambda row: row[6])  # row[6] = uts

        cur = conn.cursor()
        cur.executemany(
            """
            INSERT OR IGNORE INTO scrobble
                (artist, artist_mbid, album, album_mbid,
                 track, track_mbid, uts)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """,
            scrobble_batch,
        )
        conn.commit()

        new_rows = conn.total_changes - total_new_scrobbles
        total_new_scrobbles = conn.total_changes
        print(f"Page {page}: inserted {new_rows} new scrobbles "
              f"(batch size {len(scrobble_batch)})")

        # Optional: sort album_art batch by album_mbid then time
        if album_batch:
            album_batch.sort(key=lambda a: (a["album_mbid"], a["last_updated"]))
            for a in album_batch:
                cur.execute(
                    """
                    INSERT INTO album_art (
                        album_mbid, artist_mbid, artist, album,
                        image_small, image_medium, image_large, image_xlarge,
                        last_updated
                    )
                    VALUES (
                        :album_mbid, :artist_mbid, :artist, :album,
                        :image_small, :image_medium, :image_large, :image_xlarge,
                        :last_updated
                    )
                    ON CONFLICT(album_mbid) DO UPDATE SET
                        artist_mbid     = excluded.artist_mbid,
                        artist          = excluded.artist,
                        album           = excluded.album,
                        image_small     = COALESCE(excluded.image_small, album_art.image_small),
                        image_medium    = COALESCE(excluded.image_medium, album_art.image_medium),
                        image_large     = COALESCE(excluded.image_large, album_art.image_large),
                        image_xlarge    = COALESCE(excluded.image_xlarge, album_art.image_xlarge),
                        last_updated = excluded.last_updated;
                    """,
                    a,
                )
            conn.commit()
            print(f"Page {page}: upserted {len(album_batch)} album_art rows")

        # Pagination
        attr = recent.get("@attr", {})
        total_pages = int(attr.get("totalPages", page))

        if page >= total_pages:
            break

        page += 1
        # polite delay – you’re nowhere near the rate limit with this
        time.sleep(0.25)

    conn.close()
    print(f"\nDone. Total new scrobbles added: {total_new_scrobbles}")


# ---------- CLI entry point ----------

if __name__ == "__main__":
    import traceback
    try:
        print("Starting Last.fm sync...")
        sync_lastfm()
        print("Sync finished.")
    except Exception as exc:
        print("ERROR during sync:", exc)
        traceback.print_exc()

    import traceback
    try:
        print("Starting Last.fm sync...")
        sync_lastfm()
        print("Sync finished.")
    except Exception as e:
        print("ERROR during sync:", e)
        traceback.print_exc()