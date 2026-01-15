#!/usr/bin/env python3
"""
Backfill album art for existing scrobbles that don't have album art yet.
Fetches album info from Last.fm API for each unique album.
"""

import time
import sqlite3
import requests
from pathlib import Path
from app.services.config import get_api_key

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
BASE_URL = "https://ws.audioscrobbler.com/2.0/"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_album_info(api_key, artist, album):
    """Fetch album info from Last.fm API."""
    params = {
        "method": "album.getInfo",
        "api_key": api_key,
        "artist": artist,
        "album": album,
        "format": "json",
    }

    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            return None

        return data.get("album", {})
    except Exception as e:
        print(f"  Error fetching album info: {e}")
        return None


def backfill():
    api_key, username = get_api_key()
    print(f"Starting album art backfill for user: {username}")

    conn = get_conn()
    cur = conn.cursor()

    # Find albums without album art
    print("\nFinding albums without album art...")
    cur.execute("""
        SELECT DISTINCT s.artist, s.album
        FROM scrobble s
        LEFT JOIN album_art aa ON s.artist = aa.artist AND s.album = aa.album
        WHERE s.album IS NOT NULL
          AND s.album <> ''
          AND aa.artist IS NULL
        ORDER BY s.artist, s.album
    """)

    albums_to_fetch = cur.fetchall()
    total = len(albums_to_fetch)
    print(f"Found {total} albums without album art")

    if total == 0:
        print("Nothing to backfill!")
        conn.close()
        return

    processed = 0
    saved = 0
    now_ts = int(time.time())

    for row in albums_to_fetch:
        artist = row["artist"]
        album = row["album"]
        processed += 1

        print(f"\n[{processed}/{total}] {artist} - {album}")

        album_info = get_album_info(api_key, artist, album)

        if not album_info:
            print("  No album info found")
            time.sleep(0.3)  # Rate limiting
            continue

        # Extract album art URLs
        images = album_info.get("image", []) or []
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

        # Only save if we have at least one image URL
        if not (img_small or img_medium or img_large or img_xlarge):
            print("  No images found")
            time.sleep(0.3)
            continue

        # Extract MBIDs if available
        album_mbid = album_info.get("mbid") or None
        artist_mbid = None
        if "artist" in album_info and isinstance(album_info["artist"], dict):
            artist_mbid = album_info["artist"].get("mbid") or None

        # Insert into album_art table
        cur.execute(
            """
            INSERT INTO album_art (
                artist, album, album_mbid, artist_mbid,
                image_small, image_medium, image_large, image_xlarge,
                last_updated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(artist, album) DO UPDATE SET
                album_mbid   = COALESCE(excluded.album_mbid, album_art.album_mbid),
                artist_mbid  = COALESCE(excluded.artist_mbid, album_art.artist_mbid),
                image_small  = COALESCE(excluded.image_small, album_art.image_small),
                image_medium = COALESCE(excluded.image_medium, album_art.image_medium),
                image_large  = COALESCE(excluded.image_large, album_art.image_large),
                image_xlarge = COALESCE(excluded.image_xlarge, album_art.image_xlarge),
                last_updated = excluded.last_updated
            """,
            (artist, album, album_mbid, artist_mbid,
             img_small, img_medium, img_large, img_xlarge, now_ts)
        )
        conn.commit()
        saved += 1
        print(f"  ✓ Saved album art (MBID: {album_mbid or 'none'})")

        # Rate limiting - be nice to Last.fm API
        time.sleep(0.3)

    conn.close()
    print(f"\n{'='*60}")
    print(f"Backfill complete!")
    print(f"Processed: {processed} albums")
    print(f"Saved: {saved} album art entries")
    print(f"{'='*60}")


if __name__ == "__main__":
    import traceback
    try:
        backfill()
    except KeyboardInterrupt:
        print("\n\nBackfill interrupted by user")
    except Exception as exc:
        print(f"\nERROR: {exc}")
        traceback.print_exc()
