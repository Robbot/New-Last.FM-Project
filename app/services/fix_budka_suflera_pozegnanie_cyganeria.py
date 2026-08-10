#!/usr/bin/env python3
"""
Fold Budka Suflera "Po??gnanie Z Cyganeri?" onto the canonical track
"Pożegnanie z cyganerią". Re-runnable (idempotent).

Symptom: track #4 of "Przechodniem byłem między wami" is split across two
canonical track entities. The canonical "Pożegnanie z cyganerią" (track_id 24623,
2 plays) and a Windows-1250 mojibake variant "Po??gnanie Z Cyganeri?" (track_id
25236, 1 play) where the Polish diacritics ż/ą collapsed to literal '?' (0x3F)
and the casing drifted to 'Z Cyganeri?'. A rename that touches only the text
will NOT merge (the scrobble still carries track_id 25236), so this repoints the
scrobble onto the canonical track entity and folds the variant.

The scrobble is already on the correct album entity (album_id 163), so this is a
pure track-side fold — no album work. track_id 25236 has exactly 1 scrobble and
1 alias and no album_tracks rows, so the orphan entity deletes cleanly.

Normalization note: _normalize_for_matching turns the mojibake into
'pognanie z cyganeri' (the '?' are STRIPPED, losing the consonant), while the
correct title normalizes to 'pozegnanie z cyganeria' (ż->z, ą->a) — genuinely
distinct strings, which is why the conservative Resolver never merged them.

In one transaction:
  1. scrobble:   UPDATE the variant scrobble(s) -> canonical text + track_id.
  2. track_alias: repoint the mojibake alias 25236 -> 24623 (idempotent).
  3. track entity: delete orphan 25236 (only after no references remain).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_budka_suflera_pozegnanie_cyganeria --dry-run
    python -m app.services.fix_budka_suflera_pozegnanie_cyganeria
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Budka Suflera"
ARTIST_ID = 208

SRC_TRACK_ID = 25236
SRC_TITLE = "Po??gnanie Z Cyganeri?"

DST_TRACK_ID = 24623
DST_TITLE = "Pożegnanie z cyganerią"


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
    print(f"Budka Suflera track fold: track_id {SRC_TRACK_ID} -> {DST_TRACK_ID}")
    print(f"  '{SRC_TITLE}'  ->  '{DST_TITLE}'  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (SRC_TRACK_ID,))
    alias_src = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (SRC_TRACK_ID,))
    entity_src = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (SRC_TRACK_ID,))
    dst_exists = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (DST_TRACK_ID,))
    print(f"[pre] scrobbles under variant track_id {SRC_TRACK_ID}: {scr_src}")
    print(f"[pre] aliases pointing at variant entity: {alias_src}")
    print(f"[pre] variant tracklist rows (album_tracks): {tracks_src}")
    print(f"[pre] variant track entity {SRC_TRACK_ID} present: {entity_src}")
    print(f"[pre] canonical track entity {DST_TRACK_ID} present: {dst_exists}")

    if not dst_exists:
        print(f"[pre] !! canonical track_id {DST_TRACK_ID} missing — aborting.")
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

    # --- post-state ----------------------------------------------------------
    print("\n--- post-state ---")
    pc = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE artist=? AND track=?",
        (ARTIST, DST_TITLE),
    )
    print(f"  '{DST_TITLE}' total plays: {pc}")
    print(f"  scrobbles still under variant track_id {SRC_TRACK_ID}: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id=?', (SRC_TRACK_ID,))} (expect 0)")
    print(f"  scrobbles still under variant text: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track=?', (SRC_TITLE,))} (expect 0)")
    print(f"  variant track entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM track WHERE track_id=?', (SRC_TRACK_ID,))} (expect 0)")

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
        description="Fold Budka Suflera mojibake 'Po??gnanie Z Cyganeri?' -> 'Pożegnanie z cyganerią'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
