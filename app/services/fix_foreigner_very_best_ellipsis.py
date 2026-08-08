#!/usr/bin/env python3
"""
Fold the Foreigner compilation "The Very Best ... and Beyond" (spaced ellipsis)
into its canonical title "The Very Best...and Beyond" (no spaces). Re-runnable.

Symptom: one release is split across two canonical album entities.
"The Very Best ... and Beyond" (album_id 3478, MBID NULL, 32 scrobbles) is the
Spotify/Last.fm spaced-ellipsis variant of "The Very Best...and Beyond"
(album_id 871, MBID 32868118, 100 scrobbles). They are one release, so the 32
spaced-variant scrobbles belong on the canonical album.

Why they didn't auto-merge: the album normalizer produces different norms for
the two — "the very best and beyond" (spaced: " ... " -> " ") vs
"the very bestand beyond" (unspaced: "..." -> "") — so they resolved to
separate aliases/entities. A matching album_name_mappings.json entry now
rewrites the spaced variant to canonical at ingest (cf. the Stone Temple Pilots
"Tiny Music ... " ellipsis precedent, here in the remove-spaces direction).

The tracks already share canonical entities: every spaced-variant scrobble
track_id also appears in the canonical album_tracks (17 rows), so this is a
pure album-side fold — NO track-entity merging needed.

In one transaction:
  1. scrobble (32 rows): album text -> canonical, album_mbid -> 32868118,
     album_id -> 871, album_artist -> "Foreigner".
  2. album_alias: repoint the variant alias (norm
     "the very best and beyond") 3478 -> 871 (idempotent).
  3. album_art: delete the orphan src row (artist+album match).
  4. album entity: set canonical 871's mbid (NULL today); delete orphan 3478.
     (No album_tracks to delete — src had none; canonical's 17 cover the songs.)

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_foreigner_very_best_ellipsis --dry-run
    python -m app.services.fix_foreigner_very_best_ellipsis
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Foreigner"
ARTIST_ID = 442

SRC_ALBUM = "The Very Best ... and Beyond"
SRC_ALBUM_ID = 3478
SRC_MBID = None  # the spaced-variant scrobbles carry no MBID

DST_ALBUM = "The Very Best...and Beyond"
DST_ALBUM_ID = 871
DST_MBID = "32868118-b454-49a9-a7e5-12432455b9fc"

EXPECTED_TOTAL_PLAYS = None  # grows over time; not asserted (cf. box-set script)


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
    # match variant scrobbles by album_id OR album text
    src_scr_sql = "artist=? AND (album_id=? OR album=?)"
    src_scr_params = (ARTIST, SRC_ALBUM_ID, SRC_ALBUM)

    print("=" * 72)
    print(f"Foreigner ellipsis fold: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE artist=? AND album=?",
                     (ARTIST, SRC_ALBUM))
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
    print(f"[pre] scrobbles under spaced-variant name/id: {scr_src}")
    print(f"[pre] aliases pointing at orphan entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] src tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] src album_art rows: {art_src}")
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
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move scrobbles onto canonical album ------------------------
    print("\n[1/4] Moving spaced-variant scrobbles onto canonical album")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        f"WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: repoint album alias (idempotent) --------------------------
    print("\n[2/4] Repointing album alias -> canonical")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 3: delete orphaned src album_art row -------------------------
    print("\n[3/4] Deleting orphaned src album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")
    # (No src album_tracks rows exist to delete — canonical's 17 cover the songs.)

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
    expect_note = f" (expect {EXPECTED_TOTAL_PLAYS})" if EXPECTED_TOTAL_PLAYS is not None else ""
    print(f"  total plays: {total}{expect_note}")
    print(f"  src album entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM album WHERE album_id=?', (SRC_ALBUM_ID,))} (expect 0)")
    print(f"  scrobbles still under src name: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album=?', (SRC_ALBUM,))} (expect 0)")

    # --- commit or rollback (after post-state so dry-run verifies the result) -
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fold Foreigner 'The Very Best ... and Beyond' -> 'The Very Best...and Beyond'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
