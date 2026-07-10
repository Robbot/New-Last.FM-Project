#!/usr/bin/env python3
"""
Track-name-based album routing.

For artists with multiple albums that share a name (e.g. Killing Joke's
self-titled 1980 debut AND 2003 self-titled), album-name-based mapping cannot
disambiguate scrobbles because both albums are tagged with the same name by the
source and the album_mbid is unreliable (it is frequently mis-tagged). The only
reliable signal is the TRACK NAME: such albums have disjoint tracklists.

This module re-associates scrobbles to the correct album based on their track
name, driven by app/services/track_album_routing.json. It is designed to run
after every sync (called from sync_lastfm and periodic_full_sync) so that
ongoing mis-routed scrobbles are continually corrected.

CLI:
    python -m app.services.track_album_routing             # apply for real
    python -m app.services.track_album_routing --dry-run   # preview only
    python -m app.services.track_album_routing --artist "Killing Joke" --dry-run
"""

import argparse
import json
import re
import sqlite3
from pathlib import Path

from app.logging_config import get_logger
from app.db.connections import (
    _normalize_for_matching,
    _normalize_track_name_for_matching,
)

logger = get_logger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
ROUTING_CONFIG_PATH = BASE_DIR / "app" / "services" / "track_album_routing.json"

_routing_cache = None


# ---------- Config loading ----------

def _load_track_routing():
    """Load track-album routing rules from JSON (cached per process)."""
    global _routing_cache
    if _routing_cache is None:
        try:
            if ROUTING_CONFIG_PATH.exists():
                with open(ROUTING_CONFIG_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    _routing_cache = data.get("rules", [])
                    logger.debug(f"Loaded {len(_routing_cache)} track-album routing rule(s)")
            else:
                _routing_cache = []
                logger.debug(f"No track routing config found at {ROUTING_CONFIG_PATH}")
        except Exception as e:
            logger.error(f"Error loading track routing config: {e}")
            _routing_cache = []
    return _routing_cache


def _normalize_for_routing(text: str) -> str:
    """
    Normalize a track name for routing matches.

    Builds on the existing normalizers (smart quotes, dashes, remastered/suffix
    stripping, accent removal, lowercasing) and additionally:
      - converts '&' <-> 'and'
      - strips leading articles (the / a / an)
      - strips any remaining punctuation
    so that e.g. "The Death & Resurrection Show" == "Death and Resurrection Show".
    """
    if not text:
        return ""
    # Track-specific normalizer first (handles remastered/year suffixes, smart quotes)
    text = _normalize_track_name_for_matching(text)
    # General normalizer (accent removal, hyphen->space, punctuation strip, whitespace)
    text = _normalize_for_matching(text)
    # '&' survives _normalize_for_matching (not in its punct class) -> expand it
    text = text.replace("&", " and ")
    # Strip leading article
    text = re.sub(r"^(?:the|a|an)\s+", "", text)
    # Remove any remaining non-alphanumerics
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------- Core routing ----------

def apply_track_album_routing(conn: sqlite3.Connection, dry_run: bool = False, artist_filter: str | None = None) -> dict:
    """
    Re-associate scrobbles on colliding albums to the correct album by track name.

    For each rule, fetch scrobbles whose album is in the rule's conflict_albums,
    match each scrobble's track (normalized) against the rule's route tracklists,
    and move scrobbles whose correct album differs from their current one.

    Args:
        conn: open sqlite3 connection (with row_factory). Caller owns it; this
              function commits only when it makes changes (and not in dry-run).
        dry_run: if True, log what would change and make no changes / no commit.
        artist_filter: if set, only process the rule for that artist.

    Returns:
        dict with per-rule move counts and totals.
    """
    rules = _load_track_routing()
    if artist_filter:
        rules = [r for r in rules if r.get("artist") == artist_filter]

    summary = {"rules": [], "total_moves": 0}

    for rule in rules:
        artist = rule.get("artist")
        conflict_albums = rule.get("conflict_albums") or []
        routes = rule.get("routes") or []
        if not artist or not conflict_albums or not routes:
            continue

        # Build normalized track -> (album, album_mbid) lookup for this rule
        track_to_route = {}
        for route in routes:
            target = (route.get("album"), route.get("album_mbid") or "")
            for track_name in route.get("tracks") or []:
                track_to_route[_normalize_for_routing(track_name)] = target

        placeholders = ",".join("?" * len(conflict_albums))
        rows = conn.execute(
            f"SELECT id, album, album_mbid, track FROM scrobble "
            f"WHERE artist = ? AND album IN ({placeholders})",
            [artist, *conflict_albums],
        ).fetchall()

        moved = 0
        skipped_correct = 0
        unmatched = 0
        for row in rows:
            target = track_to_route.get(_normalize_for_routing(row["track"]))
            if not target:
                unmatched += 1
                continue
            new_album, new_mbid = target
            cur_album = row["album"]
            cur_mbid = row["album_mbid"] or ""
            # Idempotency guard: already on the correct album + mbid
            if cur_album == new_album and cur_mbid == (new_mbid or ""):
                skipped_correct += 1
                continue
            if dry_run:
                logger.info(
                    f"[DRY RUN] {artist} scrobble {row['id']} '{row['track']}': "
                    f"'{cur_album}' -> '{new_album}'"
                )
                moved += 1
            else:
                # UPDATE OR IGNORE so a UNIQUE(uts,artist,album,track) collision
                # skips that row rather than aborting the whole batch.
                cur = conn.execute(
                    "UPDATE OR IGNORE scrobble SET album = ?, album_mbid = ? WHERE id = ?",
                    (new_album, new_mbid, row["id"]),
                )
                moved += cur.rowcount

        logger.info(
            f"Track routing [{artist}]: moved={moved} already_correct={skipped_correct} "
            f"unmatched={unmatched} (dry_run={dry_run})"
        )
        summary["rules"].append(
            {"artist": artist, "moved": moved, "already_correct": skipped_correct, "unmatched": unmatched}
        )
        summary["total_moves"] += moved

    if not dry_run and summary["total_moves"] > 0:
        conn.commit()

    return summary


# ---------- DB connection (for standalone CLI use) ----------

def get_db_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def main():
    parser = argparse.ArgumentParser(description="Route scrobbles to the correct album by track name.")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing.")
    parser.add_argument("--artist", default=None, help="Only process the rule for this artist.")
    args = parser.parse_args()

    conn = get_db_connection()
    try:
        result = apply_track_album_routing(conn, dry_run=args.dry_run, artist_filter=args.artist)
    finally:
        conn.close()

    verb = "Would move" if args.dry_run else "Moved"
    print(f"{verb} {result['total_moves']} scrobble(s) across {len(result['rules'])} rule(s).")
    for r in result["rules"]:
        print(f"  {r['artist']}: moved={r['moved']} already_correct={r['already_correct']} unmatched={r['unmatched']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
