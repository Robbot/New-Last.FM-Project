#!/usr/bin/env python3
"""
Enhanced album year backfill script.

Falls back through multiple sources:
1. MusicBrainz API (for albums with MBID)
2. Last.fm album.getInfo API (for all albums)
3. Wikipedia article (if Wikipedia URL is available in database)

Usage:
    python -m app.services.backfill_album_years_enhanced
"""

from __future__ import annotations

import sqlite3
import time
import re
import requests
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
TABLE = "album_art"
MBID_COL = "album_mbid"
ARTIST_COL = "artist"
ALBUM_COL = "album"
YEAR_COL = "year_col"

# MusicBrainz settings
MB_BASE_URL = "https://musicbrainz.org"
MB_TIMEOUT = 15
MB_SLEEP_SECONDS = 1.5
MB_USER_AGENT = "ScrobblesApp/1.0 (https://github.com/user/repo)"

# Last.fm settings
LF_BASE_URL = "https://ws.audioscrobbler.com/2.0/"
LF_TIMEOUT = 10
LF_SLEEP_SECONDS = 0.5

YEAR_RE = re.compile(r"^(\d{4})")


def fetch_year_from_wikipedia(wikipedia_url: str) -> Optional[str]:
    """
    Try to get release year from Wikipedia article.
    Returns year string or None.
    """
    wikipedia_url = (wikipedia_url or "").strip()
    if not wikipedia_url:
        return None

    try:
        from .fetch_wikipedia import fetch_album_year_from_wikipedia as fetch_wiki_year

        return fetch_wiki_year(wikipedia_url)
    except Exception as e:
        print(f"  [Wikipedia error: {e}]")
        return None


def get_lastfm_credentials() -> tuple[str, str]:
    """Get Last.fm API key and username from config.ini."""
    from .config import get_api_key
    return get_api_key()


def year_only(date_str: str | None) -> str | None:
    """Extract year from date string."""
    if not date_str:
        return None
    m = YEAR_RE.match(date_str.strip())
    return m.group(1) if m else None


def mb_get_json(url: str) -> dict:
    """Fetch JSON from MusicBrainz API."""
    r = requests.get(
        url,
        headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
        timeout=MB_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def fetch_year_from_musicbrainz(mbid: str) -> Optional[str]:
    """
    Try to get release year from MusicBrainz by MBID.
    Returns year string or None.
    """
    mbid = (mbid or "").strip()
    if not mbid:
        return None

    # 1) Try as release-group
    rg_url = f"{MB_BASE_URL}/ws/2/release-group/{mbid}?fmt=json"
    try:
        rg = mb_get_json(rg_url)
        year = year_only(rg.get("first-release-date"))
        if year:
            return year
    except (requests.HTTPError, requests.RequestException, KeyError):
        pass

    # 2) Try as release, then follow release-group
    rel_url = f"{MB_BASE_URL}/ws/2/release/{mbid}?inc=release-groups&fmt=json"
    try:
        rel = mb_get_json(rel_url)
        rg = rel.get("release-group") or {}
        rgid = rg.get("id")
        if rgid:
            rg2 = mb_get_json(f"{MB_BASE_URL}/ws/2/release-group/{rgid}?fmt=json")
            year = year_only(rg2.get("first-release-date"))
            if year:
                return year
    except (requests.HTTPError, requests.RequestException, KeyError):
        pass

    return None


def fetch_year_from_lastfm(artist: str, album: str, api_key: str) -> Optional[str]:
    """
    Try to get release year from Last.fm album.getInfo API.
    Returns year string or None.
    """
    artist = (artist or "").strip()
    album = (album or "").strip()
    if not artist or not album:
        return None

    params = {
        "method": "album.getInfo",
        "api_key": api_key,
        "artist": artist,
        "album": album,
        "format": "json",
        "autocorrect": 0,  # Don't autocorrect - we want exact matches
    }

    try:
        r = requests.get(LF_BASE_URL, params=params, timeout=LF_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        # Check for errors
        if "error" in data:
            return None

        album_info = data.get("album", {})

        # Try to get year from wiki published date
        wiki = album_info.get("wiki")
        if wiki:
            published = wiki.get("published")
            if published:
                # Last.fm format: "1 Jan 2008" or similar
                # Extract 4-digit year
                year_match = re.search(r"\b(19|20)\d{2}\b", published)
                if year_match:
                    return year_match.group(0)

        # Try to get year from tracks (first track date)
        tracks = album_info.get("tracks", {}).get("track", [])
        if tracks:
            if isinstance(tracks, dict):
                tracks = [tracks]
            for track in tracks:
                date = track.get("@attr", {}).get("nowplaying")  # Not a date
                # Last.fm doesn't always provide year in track info
                break

        return None

    except (requests.HTTPError, requests.RequestException, KeyError):
        return None


def main(limit: int | None = None, skip_musicbrainz: bool = False) -> int:
    """
    Backfill album years from multiple sources.

    Args:
        limit: Maximum number of albums to process (None for all)
        skip_musicbrainz: If True, skip MusicBrainz and use Last.fm only

    Returns:
        Number of albums updated
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0
    mbid_skipped = 0
    lastfm_success = 0
    wikipedia_success = 0

    try:
        # Verify column exists
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()]
        if YEAR_COL not in cols:
            raise SystemExit(f"Column '{YEAR_COL}' not found in {TABLE}. Existing cols: {cols}")

        # Get albums needing year, with artist and album info
        sql = f"""
            SELECT rowid AS rid, {MBID_COL} AS mbid, {ARTIST_COL} AS artist, {ALBUM_COL} AS album,
                   wikipedia_url
            FROM {TABLE}
            WHERE ({YEAR_COL} IS NULL OR {YEAR_COL} = '' OR {YEAR_COL} = 0)
        """
        if limit is not None:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()

        print(f"Found {len(rows)} rows needing backfill in {TABLE}.{YEAR_COL}")

        if not rows:
            print("No albums need year backfill!")
            return 0

        # Get Last.fm credentials
        api_key, username = get_lastfm_credentials()
        print(f"Using Last.fm API for: {username}")

        for i, row in enumerate(rows, start=1):
            rid = row["rid"]
            mbid = (row["mbid"] or "").strip()
            artist = (row["artist"] or "").strip()
            album = (row["album"] or "").strip()
            wikipedia_url = (row["wikipedia_url"] or "").strip() if row["wikipedia_url"] else ""
            year = None
            source = ""

            # Strategy 1: Try MusicBrainz if we have MBID (and not skipped)
            if mbid and not skip_musicbrainz:
                try:
                    year = fetch_year_from_musicbrainz(mbid)
                    if year:
                        source = "MB"
                except Exception as e:
                    print(f"  [MusicBrainz error for {mbid}: {e}]")

            # Strategy 2: Fall back to Last.fm
            if not year and artist and album:
                try:
                    year = fetch_year_from_lastfm(artist, album, api_key)
                    if year:
                        source = "LF"
                except Exception as e:
                    print(f"  [Last.fm error for '{artist}' - '{album}': {e}]")

            # Strategy 3: Fall back to Wikipedia
            if not year and wikipedia_url:
                try:
                    year = fetch_year_from_wikipedia(wikipedia_url)
                    if year:
                        source = "WP"
                except Exception as e:
                    print(f"  [Wikipedia error for '{artist}' - '{album}': {e}]")

            # Update database if we found a year
            if year:
                conn.execute(
                    f"UPDATE {TABLE} SET {YEAR_COL} = ? WHERE rowid = ?",
                    (year, rid),
                )
                conn.commit()
                updated += 1
                if source == "MB":
                    print(f"[{i}/{len(rows)}] ✅ MB: {artist} - {album} -> {year}")
                elif source == "LF":
                    print(f"[{i}/{len(rows)}] ✅ LF: {artist} - {album} -> {year}")
                    lastfm_success += 1
                elif source == "WP":
                    print(f"[{i}/{len(rows)}] ✅ WP: {artist} - {album} -> {year}")
                    wikipedia_success += 1
            else:
                mbid_skipped += 1
                print(f"[{i}/{len(rows)}] ⚠️  {artist} - {album} -> no year found")

            # Sleep based on which source we used
            if source == "MB":
                time.sleep(MB_SLEEP_SECONDS)
            elif source == "WP":
                time.sleep(LF_SLEEP_SECONDS)
            else:
                time.sleep(LF_SLEEP_SECONDS)

        print(f"\n=== Summary ===")
        print(f"Total processed: {len(rows)}")
        print(f"Updated: {updated}")
        print(f"  - Via MusicBrainz: {updated - lastfm_success - wikipedia_success}")
        print(f"  - Via Last.fm: {lastfm_success}")
        print(f"  - Via Wikipedia: {wikipedia_success}")
        print(f"Not found: {mbid_skipped}")
        return updated

    finally:
        conn.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Backfill album years from multiple sources")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of albums to process")
    parser.add_argument("--skip-mb", action="store_true", help="Skip MusicBrainz, use Last.fm only")
    args = parser.parse_args()

    main(limit=args.limit, skip_musicbrainz=args.skip_mb)
