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
import re
import requests
from pathlib import Path
from config import get_api_key  # your helper: returns (api_key, username)

# ---------- Constants ----------
BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BASE_URL = "https://ws.audioscrobbler.com/2.0/"


# ---------- Cleaning helpers ----------

# Regex patterns to remove remastered/remaster suffixes
# Matches variants like:
#   - " - Remastered 2014"
#   - " - Remaster 2009"
#   - " - remastered 1995"
#   - " - Remastered"
#   - " 2014 Remaster"
#   - " 2009 Remastered"
#   - " Remastered"
#   - "(Remastered)" or "[Remastered 2014]"
_REMASTER_PATTERNS = [
    r" -\s+(?:Remastered?|remastered?)(?:\s+\d{4})?\s*$",  # " - Remastered 2014" or " - Remaster"
    r"\s+(?:Remastered?|remastered?)(?:\s+\d{4})?\s*$",    # " 2014 Remaster" or " Remastered"
    r"\s*[\(\[]\s*(?:Remastered?|remastered?)(?:\s+\d{4})?\s*[\)\]]\s*$",  # "(Remastered)" or "[Remastered 2014]"
]

def clean_remastered_suffix(title: str) -> str:
    """
    Remove artificial remastered/remaster suffixes from album or track titles.
    These are added by Last.fm/music services and are not part of the original title.

    Args:
        title: The original title from Last.fm API

    Returns:
        Cleaned title with remastered suffixes removed
    """
    if not title:
        return title

    cleaned = title
    for pattern in _REMASTER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


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
            artist           TEXT NOT NULL,
            album            TEXT NOT NULL,
            album_mbid       TEXT,
            artist_mbid      TEXT,
            image_small      TEXT,
            image_medium     TEXT,
            image_large      TEXT,
            image_xlarge     TEXT,
            last_updated     INTEGER,
            year_col         INTEGER,
            PRIMARY KEY (artist, album)
        );
    """)

    # Add index on album_mbid for lookups when available
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_album_art_mbid
        ON album_art(album_mbid)
        WHERE album_mbid IS NOT NULL
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
                album_name = clean_remastered_suffix(t["album"]["#text"])
                album_mbid = t["album"].get("mbid") or None
            else:
                album_name = clean_remastered_suffix(t.get("album", ""))
                album_mbid = None

            if album_mbid == "":
                album_mbid = None

            track_name = clean_remastered_suffix(t["name"])
            track_mbid = t.get("mbid") or None

            scrobble_batch.append(
                (artist_name, artist_mbid, album_name,
                 album_mbid, track_name, track_mbid, uts)
            )

            # Collect album_art info for ALL albums (with or without MBID)
            if album_name:  # Only skip if album name is missing/empty
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

                # Only add to batch if we have at least one image URL
                if img_small or img_medium or img_large or img_xlarge:
                    album_batch.append({
                        "artist": artist_name,
                        "album": album_name,
                        "album_mbid": album_mbid,
                        "artist_mbid": artist_mbid,
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

        # Optional: sort album_art batch by (artist, album) then time
        if album_batch:
            album_batch.sort(key=lambda a: (a["artist"], a["album"], a["last_updated"]))
            for a in album_batch:
                cur.execute(
                    """
                    INSERT INTO album_art (
                        artist, album, album_mbid, artist_mbid,
                        image_small, image_medium, image_large, image_xlarge,
                        last_updated
                    )
                    VALUES (
                        :artist, :album, :album_mbid, :artist_mbid,
                        :image_small, :image_medium, :image_large, :image_xlarge,
                        :last_updated
                    )
                    ON CONFLICT(artist, album) DO UPDATE SET
                        album_mbid      = COALESCE(excluded.album_mbid, album_art.album_mbid),
                        artist_mbid     = COALESCE(excluded.artist_mbid, album_art.artist_mbid),
                        image_small     = COALESCE(excluded.image_small, album_art.image_small),
                        image_medium    = COALESCE(excluded.image_medium, album_art.image_medium),
                        image_large     = COALESCE(excluded.image_large, album_art.image_large),
                        image_xlarge    = COALESCE(excluded.image_xlarge, album_art.image_xlarge),
                        last_updated    = excluded.last_updated;
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
