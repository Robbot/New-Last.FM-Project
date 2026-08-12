#!/usr/bin/env python3
"""
Fold 8 case-variant duplicate track entities (one canonical track split across two
track_ids under the same artist). Re-runnable (idempotent).

Root cause: the album_tracks / MB backfill minted a SECOND track entity per track
using a more aggressive normalizer (strips diacritics + punctuation) than the
scrobble Resolver (which preserves them). So each track ended up with two
entities whose track_alias rows carry DIFFERENT norm_titles:

    canonical (scrobble-seeded): preserves diacritics/punct  e.g. "te quiero puta!"
    fold (backfill-minted):      strips them                e.g. "te quiero puta"

The fold entity carries the MB track MBID but few/no scrobbles and is usually off
the album tracklist; the canonical carries the scrobbles + the active tracklist
row. Folding repoints the fold's scrobbles + tracklist rows + aliases onto the
canonical and deletes the empty fold entity. Because the two sides' alias
norm_titles differ, the repoint cannot collide with track_alias PRIMARY KEY
(artist_id, norm_title) — and the canonical entity ends up resolving under BOTH
normalization schemes, which also prevents recurrence (no spotify mapping needed;
these are not source-tag variants).

The 8 pairs:
  Marek Biliński   Gorące lato              15699  <- 47950   (standard)
  Marek Biliński   Szukając Cienia         17363  <- 47951   (standard)
  Mike & The Mech  Nobody's Perfect          9505  <- 47952   (standard)
  Rammstein        Te quiero puta!           1293  <- 47970   (standard)
  Rammstein        AUSLÄNDER                 9962  <- 47971   (standard)
  Tool             H.                        6683  <- 47936   (standard)
  Simple Minds     New Gold Dream (81/...)  11347  <- 47946   (INVERTED: fold owns the
                                                              tracklist row on album 2086;
                                                              repoint it so the page shows
                                                              the 3 scrobbles, currently 0)
  John Lennon      I Don't Wanna Be a ...   47582  <- 47937   (CROSS-ALBUM: both sides 0
                                                              scrobbles; fold's tracklist row
                                                              is on Imagine (322), canonical's
                                                              on Lennon Legend (4102, has MBID).
                                                              Library dedup; both tracklist
                                                              rows survive under one entity.)

Per pair, in one atomic transaction:
  1. scrobble:    UPDATE fold scrobbles -> canonical text + track_id.
  2. album_tracks: UPDATE fold tracklist rows -> canonical track_id (active for
                  Simple Minds + John Lennon; no-op for the 6 standard pairs).
  3. track_alias: UPDATE fold aliases -> canonical track_id.
  4. track:       DELETE the now-empty fold entity (only after 0 references).

Pre-checked: 0 timestamp collisions on every pair, no shared alias norm_titles.
Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_track_entity_case_dups --dry-run
    python -m app.services.fix_track_entity_case_dups
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

# (artist, artist_id, canonical_id, canonical_title, fold_id, fold_title)
FOLDS = [
    ("Marek Biliński", 802, 15699, "Gorące lato", 47950, "Gorące lato"),
    ("Marek Biliński", 802, 17363, "Szukając Cienia", 47951, "Szukając Cienia"),
    ("Mike & The Mechanics", 850, 9505, "Nobody's Perfect", 47952, "Nobody's Perfect"),
    ("Rammstein", 1036, 1293, "Te quiero puta!", 47970, "Te quiero puta!"),
    ("Rammstein", 1036, 9962, "AUSLÄNDER", 47971, "AUSLÄNDER"),
    ("Tool", 1453, 6683, "H.", 47936, "H."),
    ("Simple Minds", 1155, 11347, "New Gold Dream (81/82/83/84)", 47946, "New Gold Dream (81/82/83/84)"),
    ("John Lennon", 631, 47582, "I Don't Wanna Be a Soldier Mama I Don't Wanna Die",
     47937, "I Don't Wanna Be A Soldier Mama I Don't Wanna Die"),
]


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
    print(f"Track-entity case-dup fold: {len(FOLDS)} pairs  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-check every pair; abort ALL if any fails (atomic, reviewable) -----
    print("\n[pre-check] scanning all pairs")
    plan = []  # (artist, can_id, can_title, fol_id, fol_title, scrobs, at_rows, alias_rows)
    abort = False
    for artist, _aid, can_id, can_title, fol_id, fol_title in FOLDS:
        can_exists = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (can_id,))
        fol_exists = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (fol_id,))
        scrobs = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (fol_id,))
        at_rows = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (fol_id,))
        alias_rows = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (fol_id,))
        # bidirectional timestamp collisions on (uts, album)
        coll = (_count(conn, """
            SELECT COUNT(*) FROM scrobble s WHERE s.track_id=?
              AND EXISTS (SELECT 1 FROM scrobble d
                          WHERE d.track_id=? AND d.uts=s.uts AND d.album=s.album)
            """, (fol_id, can_id))
            + _count(conn, """
            SELECT COUNT(*) FROM scrobble s WHERE s.track_id=?
              AND EXISTS (SELECT 1 FROM scrobble d
                          WHERE d.track_id=? AND d.uts=s.uts AND d.album=s.album)
            """, (can_id, fol_id)))
        # would the alias repoint collide with an existing canonical alias norm_title?
        alias_collide = _count(conn, """
            SELECT COUNT(*) FROM track_alias a
            WHERE a.track_id=?
              AND EXISTS (SELECT 1 FROM track_alias b
                          WHERE b.artist_id=a.artist_id AND b.norm_title=a.norm_title
                            AND b.track_id=?)
            """, (fol_id, can_id))
        flag = ""
        if not can_exists:
            flag += " [!! canonical missing]"; abort = True
        if not fol_exists:
            flag += " [already folded]"
        if coll:
            flag += f" [!! {coll} collision(s)]"; abort = True
        if alias_collide:
            flag += f" [!! {alias_collide} alias norm collision]"; abort = True
        print(f"  {artist[:20]:20} fol {fol_id} -> can {can_id}  "
              f"scrobs={scrobs} at_rows={at_rows} alias={alias_rows} coll={coll}{flag}")
        plan.append((artist, can_id, can_title, fol_id, fol_title, scrobs, at_rows, alias_rows))

    work_left = [p for p in plan if _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (p[3],))]
    if abort:
        print("\n[pre-check] !! one or more pairs failed safety checks — aborting, nothing applied.")
        return 1
    if not work_left:
        print("\n[pre-check] Nothing to do — all pairs already folded (idempotent no-op).")
        return 0

    # --- apply every fold ---------------------------------------------------
    total_moved_scr = total_moved_at = total_moved_alias = total_del_ent = 0
    for artist, can_id, can_title, fol_id, fol_title, _s, _at, _al in plan:
        print(f"\n--- {artist}: fold {fol_id} '{fol_title}' -> {can_id} '{can_title}' ---")
        moved = conn.execute(
            "UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
            (can_title, can_id, fol_id),
        ).rowcount
        at = conn.execute(
            "UPDATE album_tracks SET track_id=? WHERE track_id=?",
            (can_id, fol_id),
        ).rowcount
        al = conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?",
            (can_id, fol_id),
        ).rowcount
        remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (fol_id,))
                     + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (fol_id,))
                     + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (fol_id,)))
        deleted = 0
        if remaining == 0 and _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (fol_id,)):
            deleted = conn.execute("DELETE FROM track WHERE track_id=?", (fol_id,)).rowcount
        elif remaining:
            print(f"      !! kept fold entity {fol_id}: still {remaining} reference(s)")
        total_moved_scr += moved
        total_moved_at += at
        total_moved_alias += al
        total_del_ent += deleted
        print(f"      scrobbles moved: {moved} | tracklist rows repointed: {at} | "
              f"aliases repointed: {al} | entity deleted: {deleted}")

    print("\n" + "=" * 72)
    print(f"TOTALS  scrobbles moved: {total_moved_scr} | tracklist rows repointed: {total_moved_at} | "
          f"aliases repointed: {total_moved_alias} | entities deleted: {total_del_ent}")

    # --- post-state ---------------------------------------------------------
    print("\n--- post-state: any remaining case-variant dup pairs? ---")
    dups = conn.execute("""
        SELECT t1.artist_id, count(*) n
        FROM track t1 JOIN track t2
          ON t1.artist_id=t2.artist_id AND lower(t1.title)=lower(t2.title)
             AND t1.track_id<t2.track_id
        GROUP BY t1.artist_id
    """).fetchall()
    print(f"  case-variant dup pairs remaining: {len(dups)} (expect 0)")

    # Simple Minds album 2086 track #6 should now read 3 plays
    sm = conn.execute("""
        SELECT COUNT(*) FROM scrobble s WHERE s.track_id=11347 AND s.album_id=2086
    """).fetchone()[0]
    print(f"  Simple Minds 'New Gold Dream' (album 2086) canonical plays: {sm} (expect 3)")
    print(f"  integrity: {conn.execute('PRAGMA integrity_check').fetchone()[0]}")
    print(f"  dangling track_id refs in scrobble: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id NOT IN (SELECT track_id FROM track)')}")

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
        description="Fold 8 case-variant duplicate track entities onto their canonical entities"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
