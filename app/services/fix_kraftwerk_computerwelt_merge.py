#!/usr/bin/env python3
"""
Normalize the Kraftwerk album "Computerwelt (2009 Remaster, German Version)"
onto the canonical album "Computerwelt". Re-runnable.

Background: the "(2009 Remaster, German Version)" suffix is an edition tag, not a
distinct album. Both MB releases are titled "Computerwelt" — canonical (album_id
3460, MB release 75678f27) and the 2009 remaster (MB release feb6b805). The
remaster scrobbles belong on canonical "Computerwelt". The tracks already share
identical track_ids, so this is purely an album-side fold.

Recurrence: sync's edition-suffix regex does NOT strip the comma-form
"(2009 Remaster, German Version)" tag, so new scrobbles can reappear under the
remaster name. An album_name_mappings.json entry now corrects the album TEXT at
ingest (see clean_album_name). This script is the safety net: it folds ANY
scrobble still carrying the remaster album text OR album_mbid onto canonical, so
re-running after a sync cleans up stragglers. It also deletes remaster album_art
/ album_tracks rows and the orphan remaster album entity if present.

Matching is by album TEXT and album_mbid (NOT album_id), so it works regardless
of which canonical album_id the resolver already assigned — it only fixes the
text/mbid/id that the album library displays.

In one transaction:
  1. scrobble: album text -> "Computerwelt", album_mbid -> 75678f27,
     album_id -> 3460, for rows under the remaster name OR mbid.
     (track text/track_id/track_mbid unchanged — already correct)
  2. album_alias: repoint the variant alias -> canonical (idempotent).
  3. album_tracks / album_art: delete rows under the remaster mbid/name
     (canonical rows already cover them).
  4. album entity: set canonical mbid; delete orphan remaster entity if present.

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_kraftwerk_computerwelt_merge --dry-run
    python -m app.services.fix_kraftwerk_computerwelt_merge
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Kraftwerk"
ARTIST_ID = 711

SRC_ALBUM = "Computerwelt (2009 Remaster, German Version)"
SRC_ALBUM_ID = 4109          # original orphan entity; may already be gone
SRC_MBID = "feb6b805-9f6b-4cac-a9dd-04947e9c33fc"

DST_ALBUM = "Computerwelt"
DST_ALBUM_ID = 3460
DST_MBID = "75678f27-51e0-4802-a367-e7a1f86fc7d3"

EXPECTED_TOTAL_PLAYS = None  # grows over time; not asserted


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
    # match remaster scrobbles by album text OR album_mbid (not album_id)
    src_scr_sql = "artist=? AND (album=? OR album_mbid=?)"
    src_scr_params = (ARTIST, SRC_ALBUM, SRC_MBID)

    print("=" * 72)
    print(f"Kraftwerk normalize: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_mbid=? OR album=?",
                        (SRC_MBID, SRC_ALBUM))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE album_mbid=? OR album=?",
                     (SRC_MBID, SRC_ALBUM))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    dst_mbid_missing = _count(
        conn, "SELECT COUNT(*) FROM album WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_ALBUM_ID, DST_MBID),
    )
    # PK collision check on the rename (src vs existing dst scrobbles)
    collisions = _count(
        conn,
        """
        SELECT COUNT(*) FROM scrobble r
        WHERE r.artist=? AND r.album=?
          AND EXISTS (SELECT 1 FROM scrobble p
                      WHERE p.artist=? AND p.album=? AND p.uts=r.uts AND p.track=r.track)
        """,
        (ARTIST, SRC_ALBUM, ARTIST, DST_ALBUM),
    )
    print(f"[pre] scrobbles under remaster name/mbid: {scr_src}")
    print(f"[pre] aliases pointing at orphan entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] remaster tracklist rows: {tracks_src}")
    print(f"[pre] remaster album_art rows: {art_src}")
    print(f"[pre] orphan album entity {SRC_ALBUM_ID} present: {entity_src}")
    print(f"[pre] dst album mbid missing/wrong: {dst_mbid_missing}")
    print(f"[pre] scrobble PK collisions on rename: {collisions}")

    if collisions:
        print(f"\n[ABORT] {collisions} scrobble PK collision(s) — rename would violate "
              f"UNIQUE(uts,artist,album,track). Investigate before proceeding.")
        conn.rollback()
        return 1

    if (scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
            and entity_src == 0 and dst_mbid_missing == 0):
        print("[pre] Nothing to do — already normalized (idempotent no-op).")
        return 0

    # --- Step 1: move scrobbles onto canonical album ------------------------
    print("\n[1/4] Moving remaster scrobbles onto canonical album")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=? WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: repoint album alias (idempotent) --------------------------
    print("\n[2/4] Repointing album alias -> canonical")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 3: delete orphaned remaster album_tracks / album_art ---------
    print("\n[3/4] Deleting orphaned remaster album_tracks / album_art rows")
    del_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE album_mbid=? OR album=?", (SRC_MBID, SRC_ALBUM),
    ).rowcount
    del_art = conn.execute(
        "DELETE FROM album_art WHERE album_mbid=? OR album=?", (SRC_MBID, SRC_ALBUM),
    ).rowcount
    print(f"      tracklist rows deleted: {del_tracks}, album_art rows deleted: {del_art}")

    # --- Step 4: canonical mbid + delete orphan album entity if present ----
    print("\n[4/4] Setting canonical mbid + dropping orphan album entity")
    set_mbid = conn.execute(
        "UPDATE album SET mbid=? WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_MBID, DST_ALBUM_ID, DST_MBID),
    ).rowcount
    print(f"      canonical album {DST_ALBUM_ID} mbid -> {DST_MBID}: {set_mbid} row(s)")
    if entity_src:
        remaining_refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM track WHERE album_id=?", (SRC_ALBUM_ID,)))
        if remaining_refs == 0:
            del_ent = conn.execute("DELETE FROM album WHERE album_id=?", (SRC_ALBUM_ID,)).rowcount
            print(f"      deleted orphan album entity {SRC_ALBUM_ID}: {del_ent} row(s)")
        else:
            print(f"      !! kept album entity {SRC_ALBUM_ID}: still {remaining_refs} reference(s)")

    # --- commit or rollback -------------------------------------------------
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")

    # --- post-state: same join the album page uses --------------------------
    print("\n--- post-state (album page join: album_tracks <-> scrobble on track_id+album_id) ---")
    rows = conn.execute(
        """
        SELECT at.track_number, at.track AS track_name, at.track_id,
               COUNT(s.id) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble s ON s.track_id = at.track_id AND s.album_id = at.album_id
        WHERE at.album_id = ?
        GROUP BY at.track_id, at.track_number, at.track
        ORDER BY at.track_number
        """,
        (DST_ALBUM_ID,),
    ).fetchall()
    total = 0
    for r in rows:
        total += r["plays"]
        flag = "  <-- 0 plays" if r["plays"] == 0 else ""
        print(f"  #{r['track_number']:>2}  {r['plays']:>2} plays  tid={r['track_id']:>6}  {r['track_name']!r}{flag}")
    print(f"  total plays: {total}")
    print(f"  scrobbles still under remaster name: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album=?', (SRC_ALBUM,))} (expect 0)")
    print(f"  scrobbles still under remaster mbid: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album_mbid=?', (SRC_MBID,))} (expect 0)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Kraftwerk 'Computerwelt (2009 Remaster, German Version)' -> 'Computerwelt'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
