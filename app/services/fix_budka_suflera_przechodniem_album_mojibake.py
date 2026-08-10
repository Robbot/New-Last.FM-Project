#!/usr/bin/env python3
"""
Fold Budka Suflera "Przechodniem Bylem Miedzy Wami" (Windows-1250 mojibake
album name) into the canonical "Przechodniem byłem między wami". Re-runnable.

Symptom: a single album is split across two canonical album entities. The
canonical "Przechodniem byłem między wami" (album_id 163, all 29 plays) and a
mojibake variant "Przechodniem Bylem Miedzy Wami" (album_id 5174) where the
Polish diacritics ł/ę/ż/ę collapsed to bare ASCII (ł->l, ę->e, ż->...). The
variant is a pure structural orphan: 0 scrobbles, 0 album_art — only a stale
album_tracks tracklist (6 rows, from a pull done under the mangled name) and one
alias. So this is NOT a scrobble move: it's a straight cleanup of orphan
tracklist rows + alias repoint + entity delete.

The variant's track #6 ("I tylko gwiazda - blask jej znikomy", track_id 46282)
differs from the canonical's track #6 ("I Tylko Gwiazda", track_id 17188) — that
is a separate track-entity split, intentionally left untouched here. The variant
tracklist is DELETED (not repointed) because the canonical album_id 163 already
owns a complete tracklist and repointing would duplicate every track_number.

Normalization note: the album alias normalizer lowercases but keeps accents, so
'przechodniem byłem między wami' (163) and 'przechodniem bylem miedzy wami'
(5174) stayed distinct — the conservative Resolver never merged them.

In one transaction:
  1. scrobble:    UPDATE any stray variant scrobbles onto canonical (0 today;
                  idempotent safety net for a future stray scrobble).
  2. album_tracks: DELETE the 6 orphan variant rows (canonical keeps its list).
  3. album_art:   delete any orphan variant row (0 today; idempotent guard).
  4. album_alias: repoint 'przechodniem bylem miedzy wami' 5174 -> 163.
  5. album entity: delete orphan 5174 (only after no references remain).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_budka_suflera_przechodniem_album_mojibake --dry-run
    python -m app.services.fix_budka_suflera_przechodniem_album_mojibake
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Budka Suflera"
ARTIST_ID = 208

SRC_ALBUM = "Przechodniem Bylem Miedzy Wami"
SRC_ALBUM_ID = 5174

DST_ALBUM = "Przechodniem byłem między wami"
DST_ALBUM_ID = 163
DST_MBID = "5b22688a-f085-37f4-8dfe-9ece716e2a50"


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
    src_scr_sql = "artist=? AND (album_id=? OR album=?)"
    src_scr_params = (ARTIST, SRC_ALBUM_ID, SRC_ALBUM)

    print("=" * 72)
    print(f"Budka Suflera album fold: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE artist=? AND album=?",
                     (ARTIST, SRC_ALBUM))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    dst_exists = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (DST_ALBUM_ID,))
    print(f"[pre] scrobbles under variant name/id: {scr_src}")
    print(f"[pre] aliases pointing at variant entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] variant tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] variant album_art rows: {art_src}")
    print(f"[pre] variant album entity {SRC_ALBUM_ID} present: {entity_src}")
    print(f"[pre] canonical album entity {DST_ALBUM_ID} present: {dst_exists}")

    if not dst_exists:
        print(f"[pre] !! canonical album_id {DST_ALBUM_ID} missing — aborting.")
        return 1

    if (scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
            and entity_src == 0):
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move any stray variant scrobbles onto canonical -----------
    print("\n[1/5] Moving stray variant scrobbles onto canonical (text+mbid+album_id+album_artist)")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        f"WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: delete orphaned variant album_tracks rows -----------------
    # DELETE (not repoint): canonical 163 already owns a complete tracklist;
    # repointing would duplicate every track_number on the canonical.
    print("\n[2/5] Deleting orphaned variant album_tracks rows")
    del_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,),
    ).rowcount
    print(f"      album_tracks rows deleted: {del_tracks}")

    # --- Step 3: delete orphaned variant album_art row ---------------------
    print("\n[3/5] Deleting orphaned variant album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")

    # --- Step 4: repoint album alias (idempotent) --------------------------
    print("\n[4/5] Repointing variant album alias -> canonical")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 5: delete orphan album entity if no references remain --------
    print("\n[5/5] Dropping orphan variant album entity")
    if entity_src:
        remaining_refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM track WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_art WHERE album_id=?", (SRC_ALBUM_ID,)))
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
    print(f"  total plays across listed tracks: {total}")
    print(f"  variant album entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM album WHERE album_id=?', (SRC_ALBUM_ID,))} (expect 0)")
    print(f"  scrobbles still under variant name: "
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
        description="Fold Budka Suflera mojibake album 'Przechodniem Bylem Miedzy Wami' -> canonical"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
