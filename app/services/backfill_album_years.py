#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import time
import re
import requests

DB_PATH = "lastfmstats.sqlite"           # <- adjust if your DB is elsewhere
TABLE = "album_art"
MBID_COL = "album_mbid"
YEAR_COL = "year_col"                   # <- your column name
BASE_URL = "https://musicbrainz.org"
TIMEOUT = 15
SLEEP_SECONDS = 1.0                     # polite default for MusicBrainz

USER_AGENT = "ScrobblesApp/1.0 (contact: you@example.com)"  # <- set yours

YEAR_RE = re.compile(r"^(\d{4})")


def year_only(date_str: str | None) -> str | None:
    if not date_str:
        return None
    m = YEAR_RE.match(date_str.strip())
    return m.group(1) if m else None


def mb_get_json(url: str) -> dict:
    r = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def fetch_year_by_mbid(mbid: str) -> str | None:
    """
    Tries:
      1) release-group/<mbid> -> first-release-date
      2) release/<mbid>?inc=release-groups -> follow release-group -> first-release-date
    """
    mbid = (mbid or "").strip()
    if not mbid:
        return None

    # 1) treat MBID as release-group
    rg_url = f"{BASE_URL}/ws/2/release-group/{mbid}?fmt=json"
    try:
        rg = mb_get_json(rg_url)
        return year_only(rg.get("first-release-date"))
    except requests.HTTPError:
        pass

    # 2) treat MBID as release; follow release-group
    rel_url = f"{BASE_URL}/ws/2/release/{mbid}?inc=release-groups&fmt=json"
    try:
        rel = mb_get_json(rel_url)
        rg = rel.get("release-group") or {}
        rgid = rg.get("id")
        if not rgid:
            return None
        rg2 = mb_get_json(f"{BASE_URL}/ws/2/release-group/{rgid}?fmt=json")
        return year_only(rg2.get("first-release-date"))
    except requests.HTTPError:
        return None


def main(limit: int | None = None) -> int:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    updated = 0

    try:
        # sanity: ensure YEAR_COL exists
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({TABLE})").fetchall()]
        if YEAR_COL not in cols:
            raise SystemExit(
                f"Column '{YEAR_COL}' not found in {TABLE}. "
                f"Existing cols: {cols}"
            )

        sql = f"""
            SELECT rowid AS rid, {MBID_COL} AS mbid
            FROM {TABLE}
            WHERE {MBID_COL} IS NOT NULL
              AND TRIM({MBID_COL}) != ''
              AND ({YEAR_COL} IS NULL OR TRIM({YEAR_COL}) = '')
        """
        if limit is not None:
            sql += " LIMIT ?"
            rows = conn.execute(sql, (limit,)).fetchall()
        else:
            rows = conn.execute(sql).fetchall()

        print(f"Found {len(rows)} rows needing backfill in {TABLE}.{YEAR_COL}")

        for i, row in enumerate(rows, start=1):
            mbid = (row["mbid"] or "").strip()
            year = fetch_year_by_mbid(mbid)

            if year:
                conn.execute(
                    f"UPDATE {TABLE} SET {YEAR_COL} = ? WHERE rowid = ?",
                    (year, row["rid"]),
                )
                conn.commit()
                updated += 1
                print(f"[{i}/{len(rows)}] ✅ {mbid} -> {year}")
            else:
                print(f"[{i}/{len(rows)}] ⚠️  {mbid} -> no year found")

            time.sleep(SLEEP_SECONDS)

        print(f"Done. Updated: {updated}")
        return updated

    finally:
        conn.close()


if __name__ == "__main__":
    # set limit=20 for a test run; set None for full backfill
    main(limit=20)
