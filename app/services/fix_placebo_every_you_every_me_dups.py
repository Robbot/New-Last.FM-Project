#!/usr/bin/env python3
"""
Fold Placebo "Every You, Every Me" onto the canonical track "Every You Every
Me". Re-runnable (idempotent).

Symptom: "Every You Every Me" is split across two canonical track entities. The
canonical "Every You Every Me" (track_id 3376, 74 plays) sits on the album
tracklist of BOTH "Without You I'm Nothing" (album_id 768, track #8, MBID
6d56a758) and "Cruel Intentions" (album_id 49, track #1). A comma variant "Every
You, Every Me" (track_id 26688, 5 plays) is off-tracklist with no MBID — a
Last.fm tagging inconsistency — so its plays never join either album-page row.

After folding 26688 -> 3376:
  Without You I'm Nothing (768): 67 -> 70
  Cruel Intentions (49):          4 ->  6
  A Place for Us to Dream (2726): 3 (unchanged, canonical side only)
  total:                         74 -> 79

A rename that touches only the text will NOT merge (the scrobble still carries
track_id 26688), so this repoints the scrobbles onto the canonical track entity
and folds the variant — same pattern as fix_placebo_black_market_music_dups.py
and fix_budka_suflera_pozegnanie_cyganeria.py.

This is a pure track-side fold — scrobbles are already on the right album
entities, only the track entity is split. track_id 26688 has exactly 5 scrobbles,
1 alias, and 0 album_tracks rows, so the orphan entity deletes cleanly. 0
timestamp collisions between the variant and canonical scrobbles were confirmed.

Recurrence: spotify_track_mappings.json carries
  { artist: Placebo, album: "Without You I'm Nothing",
    from: "Every You, Every Me", to: "Every You Every Me" }
  { artist: Placebo, album: "Cruel Intentions",
    from: "Every You, Every Me", to: "Every You Every Me" }
so sync normalizes the comma variant going forward (the variant appears on both
albums). NOTE: a separate pre-existing Cruel Intentions mapping redirects the
NON-comma text to "Every You Every Me (single mix)" — it is not in effect for
current data and is left untouched; this fold targets the canonical entity title.

In one transaction:
  1. scrobble:   UPDATE the variant scrobble(s) -> canonical text + track_id.
  2. track_alias: repoint the variant alias 26688 -> 3376 (idempotent).
  3. track entity: delete orphan 26688 (only after no references remain).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_placebo_every_you_every_me_dups --dry-run
    python -m app.services.fix_placebo_every_you_every_me_dups
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Placebo"
ARTIST_ID = 1001

SRC_TRACK_ID = 26688
SRC_TITLE = "Every You, Every Me"

DST_TRACK_ID = 3376
DST_TITLE = "Every You Every Me"

# Albums the canonical entity is tracked on (for post-state verification).
PRIMARY_ALBUM_ID = 768   # Without You I'm Nothing (track #8, has MBID)


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
    print(f"Placebo track fold: track_id {SRC_TRACK_ID} -> {DST_TRACK_ID}")
    print(f"  '{SRC_TITLE}'  ->  '{DST_TITLE}'  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (SRC_TRACK_ID,))
    alias_src = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (SRC_TRACK_ID,))
    entity_src = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (SRC_TRACK_ID,))
    dst_exists = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (DST_TRACK_ID,))
    # safety: any variant scrobble that would collide with a canonical play on (uts, album)
    collisions = _count(
        conn,
        """
        SELECT COUNT(*) FROM scrobble s
        WHERE s.track_id=?
          AND EXISTS (SELECT 1 FROM scrobble d
                      WHERE d.track_id=? AND d.uts=s.uts AND d.album=s.album)
        """,
        (SRC_TRACK_ID, DST_TRACK_ID),
    )
    print(f"[pre] scrobbles under variant track_id {SRC_TRACK_ID}: {scr_src}")
    print(f"[pre] aliases pointing at variant entity: {alias_src}")
    print(f"[pre] variant tracklist rows (album_tracks): {tracks_src}")
    print(f"[pre] variant track entity {SRC_TRACK_ID} present: {entity_src}")
    print(f"[pre] canonical track entity {DST_TRACK_ID} present: {dst_exists}")
    print(f"[pre] duplicate-timestamp collisions vs canonical: {collisions} (expect 0)")

    if not dst_exists:
        print(f"[pre] !! canonical track_id {DST_TRACK_ID} missing — aborting.")
        return 1

    if collisions:
        print(f"[pre] !! {collisions} collision(s): rewrite would violate "
              f"UNIQUE(uts, artist, album, track) — aborting, do not blind-fold.")
        return 1

    if scr_src == 0 and alias_src == 0 and tracks_src == 0 and entity_src == 0:
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move variant scrobble(s) onto canonical track entity ------
    print("\n[1/3] Moving variant scrobbles onto canonical track (text + track_id)")
    moved = conn.execute(
        "UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
        (DST_TITLE, DST_TRACK_ID, SRC_TRACK_ID),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: repoint track alias (idempotent) --------------------------
    print("\n[2/3] Repointing variant track alias -> canonical")
    repointed = conn.execute(
        "UPDATE track_alias SET track_id=? WHERE track_id=?",
        (DST_TRACK_ID, SRC_TRACK_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 3: delete orphan track entity if no references remain --------
    print("\n[3/3] Dropping orphan track entity")
    if entity_src:
        remaining_refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (SRC_TRACK_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (SRC_TRACK_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,)))
        if remaining_refs == 0:
            del_ent = conn.execute("DELETE FROM track WHERE track_id=?", (SRC_TRACK_ID,)).rowcount
            print(f"      deleted orphan track entity {SRC_TRACK_ID}: {del_ent} row(s)")
        else:
            print(f"      !! kept track entity {SRC_TRACK_ID}: still {remaining_refs} reference(s)")

    # --- post-state: per-album play counts for the canonical track ---------
    print("\n--- post-state (per-album plays for canonical track_id "
          f"{DST_TRACK_ID} '{DST_TITLE}') ---")
    for r in conn.execute(
        """
        SELECT a.title AS album, COUNT(s.id) AS plays
        FROM scrobble s JOIN album a ON a.album_id = s.album_id
        WHERE s.track_id = ?
        GROUP BY s.album_id ORDER BY plays DESC
        """,
        (DST_TRACK_ID,),
    ):
        print(f"  {r['plays']:>3} plays  {r['album']!r}")
    total = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE artist=? AND track=?",
                   (ARTIST, DST_TITLE))
    print(f"  total '{DST_TITLE}' plays (any album): {total} (expect 79)")
    print(f"  scrobbles still under variant track_id {SRC_TRACK_ID}: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id=?', (SRC_TRACK_ID,))} (expect 0)")
    print(f"  scrobbles still under variant text: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track=?', (SRC_TITLE,))} (expect 0)")
    print(f"  variant track entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM track WHERE track_id=?', (SRC_TRACK_ID,))} (expect 0)")

    # primary album-page sanity: WYIN track #8 should read 70
    wyin = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE track_id=? AND album_id=?",
        (DST_TRACK_ID, PRIMARY_ALBUM_ID),
    )
    print(f"  WYIN (album {PRIMARY_ALBUM_ID}) '{DST_TITLE}': {wyin} plays (expect 70)")

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
        description="Fold Placebo 'Every You, Every Me' -> 'Every You Every Me'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
