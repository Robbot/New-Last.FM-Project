#!/usr/bin/env python3
"""
Clear the last Budka Suflera mojibake remnants on "Przechodniem byłem między
wami" (part 2 of the Windows-1250 cleanup). Re-runnable (idempotent).

Two leftover track-entity issues from the same mojibake source:

  A. "Pie?? Niepokorna" (track_id 28145) — the same ?-for-diacritic collapse as
     the earlier folds. Fold onto the canonical "Pieśń niepokorna" (track_id 13,
     track #1 of the album). The variant entity is artist-scoped, so all 6 of its
     scrobbles move together (3 on this album + 3 on "Greatest Hits"). No
     timestamp collisions, so it's a straight move + alias repoint + entity delete
     (same recipe as fix_budka_suflera_pozegnanie_cyganeria.py).

  B. "I tylko gwiazda - blask jej znikomy" (track_id 46282) — a fuller-title
     variant of track #6 that only ever lived on the mojibake album variant
     (album_id 5174), whose album_tracks rows were deleted by
     fix_budka_suflera_przechodniem_album_mojibake.py. It now has 0 scrobbles and
     0 album_tracks — a pure orphan. Delete entity + alias. The canonical track #6
     "I Tylko Gwiazda" (track_id 17188, 4 plays) is left as the scrobbles carry it.

In one transaction:
  A1. scrobble:   UPDATE all 28145 scrobbles -> canonical text + track_id 13.
  A2. track_alias: repoint 'pie?? niepokorna' 28145 -> 13.
  A3. track entity: delete orphan 28145.
  B1. track_alias: delete orphan 46282 alias.
  B2. track entity: delete orphan 46282.

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_budka_suflera_piesn_niepokorna --dry-run
    python -m app.services.fix_budka_suflera_piesn_niepokorna
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Budka Suflera"

# Part A — Pie?? Niepokorna -> Pieśń niepokorna
A_SRC_TRACK_ID = 28145
A_SRC_TITLE = "Pie?? Niepokorna"
A_DST_TRACK_ID = 13
A_DST_TITLE = "Pieśń niepokorna"

# Part B — orphan "I tylko gwiazda - blask jej znikomy"
B_ORPHAN_TRACK_ID = 46282
B_ORPHAN_TITLE = "I tylko gwiazda - blask jej znikomy"


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
    print(f"Budka Suflera mojibake cleanup (part 2)  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    nothing_to_do = True

    # ===== Part A: fold Pie?? Niepokorna -> Pieśń niepokorna ==============
    print(f"\n[A] Fold track_id {A_SRC_TRACK_ID} ({A_SRC_TITLE!r}) -> "
          f"{A_DST_TRACK_ID} ({A_DST_TITLE!r})")
    scr = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (A_SRC_TRACK_ID,))
    alias = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (A_SRC_TRACK_ID,))
    ent = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (A_SRC_TRACK_ID,))
    dst_exists = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (A_DST_TRACK_ID,))
    print(f"[A pre] scrobbles={scr} alias={alias} entity={ent} dst_exists={dst_exists}")
    if not dst_exists:
        print(f"[A] !! canonical track_id {A_DST_TRACK_ID} missing — skipping A.")
    elif scr or alias or ent:
        nothing_to_do = False
        # A1 — move scrobbles (text + track_id)
        moved = conn.execute(
            "UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
            (A_DST_TITLE, A_DST_TRACK_ID, A_SRC_TRACK_ID),
        ).rowcount
        print(f"[A1] scrobbles moved: {moved}")
        # A2 — repoint alias
        repointed = conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?",
            (A_DST_TRACK_ID, A_SRC_TRACK_ID),
        ).rowcount
        print(f"[A2] aliases repointed: {repointed}")
        # A3 — delete orphan entity if clean
        remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (A_SRC_TRACK_ID,))
                     + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (A_SRC_TRACK_ID,))
                     + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (A_SRC_TRACK_ID,)))
        if remaining == 0:
            dele = conn.execute("DELETE FROM track WHERE track_id=?", (A_SRC_TRACK_ID,)).rowcount
            print(f"[A3] deleted orphan track entity {A_SRC_TRACK_ID}: {dele} row(s)")
        else:
            print(f"[A3] !! kept entity {A_SRC_TRACK_ID}: still {remaining} reference(s)")
    else:
        print("[A] already folded (idempotent no-op)")

    # ===== Part B: delete orphan I tylko gwiazda - blask jej znikomy ======
    print(f"\n[B] Delete orphan track_id {B_ORPHAN_TRACK_ID} ({B_ORPHAN_TITLE!r})")
    b_scr = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (B_ORPHAN_TRACK_ID,))
    b_trk = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (B_ORPHAN_TRACK_ID,))
    b_alias = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (B_ORPHAN_TRACK_ID,))
    b_ent = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (B_ORPHAN_TRACK_ID,))
    print(f"[B pre] scrobbles={b_scr} album_tracks={b_trk} alias={b_alias} entity={b_ent}")
    if b_scr or b_trk:
        print(f"[B] !! not an orphan (scrobbles={b_scr} album_tracks={b_trk}) — skipping B.")
    elif b_alias or b_ent:
        nothing_to_do = False
        # B1 — delete alias
        da = conn.execute("DELETE FROM track_alias WHERE track_id=?", (B_ORPHAN_TRACK_ID,)).rowcount
        print(f"[B1] aliases deleted: {da}")
        # B2 — delete entity
        de = conn.execute("DELETE FROM track WHERE track_id=?", (B_ORPHAN_TRACK_ID,)).rowcount
        print(f"[B2] deleted orphan track entity {B_ORPHAN_TRACK_ID}: {de} row(s)")
    else:
        print("[B] already gone (idempotent no-op)")

    if nothing_to_do:
        print("\n[pre] Nothing to do — both already clean (idempotent no-op).")

    # ===== post-state =====================================================
    print("\n--- post-state ---")
    pc = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE artist=? AND track=?",
                (ARTIST, A_DST_TITLE))
    print(f"  '{A_DST_TITLE}' total plays: {pc} (was 2 on album; variant added 6 across albums)")
    print(f"  scrobbles still under '{A_SRC_TITLE}': "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track=?', (A_SRC_TITLE,))} (expect 0)")
    print(f"  orphan {B_ORPHAN_TRACK_ID} entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM track WHERE track_id=?', (B_ORPHAN_TRACK_ID,))} (expect 0)")
    # album #1 track now has the 3 folded plays
    r = conn.execute(
        """SELECT COUNT(*) FROM scrobble s
           JOIN album_tracks at ON at.track_id=s.track_id AND at.album_id=s.album_id
           WHERE at.album_id=163 AND at.track_number=1""",
    ).fetchone()[0]
    print(f"  Przechodniem track #1 (Pieśń niepokorna) plays via tracklist join: {r}")

    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clear remaining Budka Suflera mojibake: fold 'Pie?? Niepokorna' + drop orphan track #6 entity"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
