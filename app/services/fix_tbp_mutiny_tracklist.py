#!/usr/bin/env python3
"""
Consolidate The Birthday Party "Mutiny / The Bad Seed EP" — fix the two 0-play
tracklist rows AND fold three duplicate canonical album entities into the one
real release.

Symptom (reported): on the track listing for "Mutiny / The Bad Seed EP", track 2
"Wildworld" and track 5 "Jennifers Veil" show 0 plays.

Root cause: play counts join scrobble.track_id = album_tracks.track_id (scoped by
album_id). The album tracklist was first fetched from Last.fm under misspelled
track names ("Wildworld", "Jennifers Veil") BEFORE the alias mappings existed, so
the Resolver minted empty canonical track entities (26874, 25233) that the
tracklist rows still point at. The scrobbles later arrived under the correct
names ("Wild World", "Jennifer's Veil") and resolved to different entities
(47905, 47894) that carry the plays. Result: tracklist track_id != scrobble
track_id -> 0 plays, and the wrong spelling is what's displayed.

The same release is also split across THREE canonical album entities:
  5294 "Mutiny / The Bad Seed EP" (mbid 1fb4a566…, 12 scrobbles) — the real one,
       but it has NO cover art row.
  5292 "Mutiny / the Bad Seed"     (no mbid, 0 scrobbles) — owns the cover art.
  3440 "Mutiny - the Bad Seeds E.R" (no mbid, 0 scrobbles) — owns a 2nd cover art.

This script consolidates everything onto 5294, in one transaction:

  1. Repoint the two canonical-album tracklist rows to the correct text +
     track_id (Wildworld->Wild World/47905, Jennifers Veil->Jennifer's Veil/47894),
     AND backfill album_mbid onto every canonical tracklist row. The MBID is
     required because the album page selects its tracklist by album_mbid once the
     cover-art row carries one (step 3) — NULL album_mbid rows are invisible to
     get_album_tracks_by_mbid.
  2. Delete the duplicate tracklists owned by the orphan albums 5292/3440.
  3. Move the stranded cover art onto the canonical album (5294), drop the spare.
  4. Repoint the variant album aliases (mutiny the bad seed / ...seeds er) -> 5294.
  5. Delete the now-empty orphan album entities 5292 and 3440.
  6. Delete the now-unreferenced orphan track entities 26874 and 25233.

Idempotent: every WHERE clause no longer matches after the first run, so
re-running is a no-op. Scoped strictly by artist + album_id (never by album_mbid
alone — one MBID can legitimately span multiple albums).

Future re-fetches are safe: the alias rows "wildworld"->47905 and
"jennifers veil"->47894 already exist, so a fresh tracklist pull will resolve to
the correct entities rather than minting new orphans.

Usage:
    python -m app.services.fix_tbp_mutiny_tracklist --dry-run
    python -m app.services.fix_tbp_mutiny_tracklist
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

# --- Canonical target -------------------------------------------------------
ARTIST = "The Birthday Party"
ARTIST_ID = 1276
CANONICAL_ALBUM = "Mutiny / The Bad Seed EP"
CANONICAL_MBID = "1fb4a566-940d-3981-9a48-5ffa2220e8da"
CANONICAL_ALBUM_ID = 5294

# Orphan canonical album entities for the same release (0 scrobbles each).
ORPHAN_ALBUM_IDS = (5292, 3440)
# norm_title aliases currently pointing at the orphans -> repoint to canonical.
ALIAS_NORMS_TO_REPOINT = ("mutiny the bad seed", "mutiny the bad seeds er")

# --- Tracklist corrections (album 5294) -------------------------------------
# (wrong text, wrong track_id, correct text, correct track_id)
TRACK_FIXES = [
    ("Wildworld", 26874, "Wild World", 47905),
    ("Jennifers Veil", 25233, "Jennifer's Veil", 47894),
]
ORPHAN_TRACK_IDS = (26874, 25233)


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if not db_path.exists():
        raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")
    return str(db_path)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _count(conn, sql, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, dry_run: bool) -> int:
    print("=" * 72)
    print(f"TBP Mutiny/Bad Seed consolidation  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    orphan_ids_sql = ",".join("?" for _ in ORPHAN_ALBUM_IDS)

    # --- pre-state snapshot --------------------------------------------------
    wrong_track_rows = sum(
        _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=? AND track_id=?",
               (CANONICAL_ALBUM_ID, wid))
        for _, wid, _, _ in TRACK_FIXES
    )
    orphan_tracklists = _count(
        conn, f"SELECT COUNT(*) FROM album_tracks WHERE album_id IN ({orphan_ids_sql})",
        ORPHAN_ALBUM_IDS,
    )
    canon_art = _count(conn, "SELECT COUNT(*) FROM album_art WHERE album_id=?", (CANONICAL_ALBUM_ID,))
    orphan_arts = _count(
        conn, f"SELECT COUNT(*) FROM album_art WHERE album_id IN ({orphan_ids_sql})", ORPHAN_ALBUM_IDS,
    )
    orphan_album_entities = _count(
        conn, f"SELECT COUNT(*) FROM album WHERE album_id IN ({orphan_ids_sql})", ORPHAN_ALBUM_IDS,
    )
    orphan_track_entities = _count(
        conn, "SELECT COUNT(*) FROM track WHERE track_id IN (?,?)", ORPHAN_TRACK_IDS,
    )
    tracklist_missing_mbid = _count(
        conn,
        "SELECT COUNT(*) FROM album_tracks WHERE album_id=? AND (album_mbid IS NULL OR album_mbid != ?)",
        (CANONICAL_ALBUM_ID, CANONICAL_MBID),
    )
    print(f"[pre] canonical-album tracklist rows with wrong track_id: {wrong_track_rows}")
    print(f"[pre] canonical-album tracklist rows missing album_mbid: {tracklist_missing_mbid}")
    print(f"[pre] tracklist rows on orphan albums {ORPHAN_ALBUM_IDS}: {orphan_tracklists}")
    print(f"[pre] cover-art rows: canonical {CANONICAL_ALBUM_ID}={canon_art}, orphans={orphan_arts}")
    print(f"[pre] orphan album entities to delete: {orphan_album_entities}")
    print(f"[pre] orphan track entities to delete: {orphan_track_entities}")

    if (wrong_track_rows == 0 and tracklist_missing_mbid == 0 and orphan_tracklists == 0
            and orphan_arts == 0 and orphan_album_entities == 0
            and orphan_track_entities == 0 and canon_art >= 1):
        print("[pre] Nothing to do — already consolidated (idempotent no-op).")
        return 0

    # --- Step 1: reconcile canonical-album tracklist (text, track_id, mbid) -
    print("\n[1/6] Reconciling tracklist rows on canonical album")
    for wrong_text, wrong_id, right_text, right_id in TRACK_FIXES:
        cur = conn.execute(
            "UPDATE album_tracks SET track=?, track_id=? "
            "WHERE album_id=? AND track_id=?",
            (right_text, right_id, CANONICAL_ALBUM_ID, wrong_id),
        )
        if cur.rowcount:
            print(f"      {wrong_text!r} (track_id {wrong_id}) -> {right_text!r} (track_id {right_id}): {cur.rowcount} row(s)")
        else:
            print(f"      {wrong_text!r} (track_id {wrong_id}) -> already correct, 0 rows")
    # Backfill album_mbid on every canonical tracklist row so the album page's
    # MBID-keyed tracklist query (get_album_tracks_by_mbid) can see them.
    cur = conn.execute(
        "UPDATE album_tracks SET album_mbid=? WHERE album_id=? AND (album_mbid IS NULL OR album_mbid != ?)",
        (CANONICAL_MBID, CANONICAL_ALBUM_ID, CANONICAL_MBID),
    )
    print(f"      album_mbid backfilled on canonical tracklist: {cur.rowcount} row(s) -> {CANONICAL_MBID}")

    # --- Step 2: delete duplicate tracklists owned by orphan albums ---------
    print("\n[2/6] Deleting tracklists on orphan albums")
    cur = conn.execute(
        f"DELETE FROM album_tracks WHERE album_id IN ({orphan_ids_sql})", ORPHAN_ALBUM_IDS,
    )
    print(f"      album_tracks rows deleted: {cur.rowcount}")

    # --- Step 3: move cover art onto the canonical album --------------------
    print("\n[3/6] Moving cover art onto canonical album")
    # Prefer the orphan that actually holds art (5292 here); fall back to 3440.
    source_id = next(
        (aid for aid in ORPHAN_ALBUM_IDS
         if _count(conn, "SELECT COUNT(*) FROM album_art WHERE album_id=?", (aid,)) > 0),
        None,
    )
    if source_id is not None:
        cur = conn.execute(
            "UPDATE album_art SET album=?, album_mbid=?, album_id=? WHERE album_id=?",
            (CANONICAL_ALBUM, CANONICAL_MBID, CANONICAL_ALBUM_ID, source_id),
        )
        print(f"      moved art from album_id {source_id} -> {CANONICAL_ALBUM_ID} ({CANONICAL_ALBUM!r}, mbid {CANONICAL_MBID}): {cur.rowcount} row(s)")
        # Drop any other art rows still clinging to the orphan ids (the spare cover).
        cur = conn.execute(
            f"DELETE FROM album_art WHERE album_id IN ({orphan_ids_sql})", ORPHAN_ALBUM_IDS,
        )
        if cur.rowcount:
            print(f"      spare orphan art rows deleted: {cur.rowcount}")
    else:
        print("      no orphan art row found to move (canonical already has art, or none exists)")

    # --- Step 4: repoint variant album aliases -> canonical -----------------
    print("\n[4/6] Repointing album aliases to canonical album")
    cur = conn.execute(
        "UPDATE album_alias SET album_id=? "
        "WHERE artist_id=? AND norm_title IN (?,?)",
        (CANONICAL_ALBUM_ID, ARTIST_ID, *ALIAS_NORMS_TO_REPOINT),
    )
    print(f"      alias rows repointed -> {CANONICAL_ALBUM_ID}: {cur.rowcount}")
    # Ensure the canonical alias itself is present.
    conn.execute(
        "INSERT OR IGNORE INTO album_alias (artist_id, norm_title, album_id) VALUES (?,?,?)",
        (ARTIST_ID, "mutiny the bad seed ep", CANONICAL_ALBUM_ID),
    )
    print(f"      canonical alias 'mutiny the bad seed ep' -> {CANONICAL_ALBUM_ID} ensured")

    # --- Step 5: delete empty orphan album entities -------------------------
    print("\n[5/6] Deleting orphan album entities")
    album_refs = (_count(conn, f"SELECT COUNT(*) FROM album_alias WHERE album_id IN ({orphan_ids_sql})",
                         ORPHAN_ALBUM_IDS)
                  + _count(conn, "SELECT COUNT(*) FROM track WHERE album_id IN (?,?)", ORPHAN_ALBUM_IDS))
    if album_refs == 0:
        cur = conn.execute(
            f"DELETE FROM album WHERE album_id IN ({orphan_ids_sql})", ORPHAN_ALBUM_IDS,
        )
        print(f"      album entities deleted: {cur.rowcount} (ids {ORPHAN_ALBUM_IDS})")
    else:
        print(f"      !! kept orphan albums: still {album_refs} FK reference(s) (alias/track.album_id)")

    # --- Step 6: delete unreferenced orphan track entities ------------------
    print("\n[6/6] Deleting orphan track entities")
    track_refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id IN (?,?)", ORPHAN_TRACK_IDS)
                  + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id IN (?,?)", ORPHAN_TRACK_IDS)
                  + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id IN (?,?)", ORPHAN_TRACK_IDS))
    if track_refs == 0:
        cur = conn.execute(
            "DELETE FROM track WHERE track_id IN (?,?)", ORPHAN_TRACK_IDS,
        )
        print(f"      track entities deleted: {cur.rowcount} (ids {ORPHAN_TRACK_IDS})")
    else:
        print(f"      !! kept orphan tracks: still {track_refs} reference(s)")

    # --- commit or rollback --------------------------------------------------
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")

    # --- post-state (sees committed or rolled-back state) -------------------
    print("\n--- post-state ---")
    for right_text, right_id in (("Wild World", 47905), ("Jennifer's Veil", 47894)):
        plays = _count(
            conn,
            "SELECT COUNT(*) FROM scrobble s "
            "JOIN album_tracks at ON at.track_id = s.track_id AND s.album_id = at.album_id "
            "WHERE at.album_id=? AND at.track_id=?",
            (CANONICAL_ALBUM_ID, right_id),
        )
        row = conn.execute(
            "SELECT track, track_id FROM album_tracks WHERE album_id=? AND track_id=?",
            (CANONICAL_ALBUM_ID, right_id),
        ).fetchone()
        print(f"  {right_text!r}: tracklist={dict(row) if row else None}, joined plays={plays}")
    print(f"  orphan album entities remaining: {_count(conn, f'SELECT COUNT(*) FROM album WHERE album_id IN ({orphan_ids_sql})', ORPHAN_ALBUM_IDS)} (expect 0)")
    print(f"  orphan track entities remaining: {_count(conn, 'SELECT COUNT(*) FROM track WHERE track_id IN (?,?)', ORPHAN_TRACK_IDS)} (expect 0)")
    print(f"  canonical album cover-art rows : {_count(conn, 'SELECT COUNT(*) FROM album_art WHERE album_id=?', (CANONICAL_ALBUM_ID,))} (expect 1)")
    print(f"  total scrobbles on canonical   : {_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album_id=?', (CANONICAL_ALBUM_ID,))} (expect 12, unchanged)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate The Birthday Party Mutiny/Bad Seed album + tracklist"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
