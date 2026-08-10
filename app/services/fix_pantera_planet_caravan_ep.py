#!/usr/bin/env python3
"""
Fold Pantera "Planet Caravan EP" into the "Far Beyond Driven" album.
Re-runnable (idempotent).

Symptom: "Planet Caravan" (the Black Sabbath cover that is a Far Beyond Driven
bonus track) is split across two canonical album entities — the EP (album_id
3445, 1 play) and the album (album_id 1195, 17 plays of the same track). The EP
scrobble is a DISTINCT play (uts 1255075992 has no twin on the album), so unlike
fix_strokes_going_shopping_single.py this is a straight MOVE, not a dedup-delete.

The track entity is already shared (track_id 5917 on both sides), so this is a
pure album-side fold: move the one scrobble onto the album entity, drop the
orphan album_art row, repoint the 'planet caravan ep' alias to 1195, and delete
the orphan album entity 3445 once nothing references it.

In one transaction:
  1. scrobble:   UPDATE the EP scrobble onto the album (text + album_mbid +
                 album_id + album_artist together, or the move is invisible).
  2. album_art:  delete the orphan EP row.
  3. album_tracks: delete any orphan EP rows (none today; idempotent guard).
  4. album_alias: repoint 'planet caravan ep' 3445 -> 1195 (idempotent).
  5. album entity: delete orphan 3445 (only after no references remain).

The album-level mbid is left NULL (MBID is a conservative hint, never
force-set); the scrobble-level album_mbid 1a5d0675... is the dominant value on
Far Beyond Driven and is applied to the moved scrobble so it groups with the
album's existing plays.

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_pantera_planet_caravan_ep --dry-run
    python -m app.services.fix_pantera_planet_caravan_ep
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Pantera"
ARTIST_ID = 959

SRC_ALBUM = "Planet Caravan EP"
SRC_ALBUM_ID = 3445

DST_ALBUM = "Far Beyond Driven"
DST_ALBUM_ID = 1195
DST_MBID = "1a5d0675-f8da-4bab-b13a-32f000946951"


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
    print(f"Pantera EP fold: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    # sanity: any EP scrobble that duplicates an album play on (uts, track)?
    collisions = _count(
        conn,
        """
        SELECT COUNT(*) FROM scrobble s
        WHERE s.artist=? AND (s.album_id=? OR s.album=?)
          AND EXISTS (SELECT 1 FROM scrobble d
                      WHERE d.artist=? AND (d.album_id=? OR d.album=?)
                        AND d.uts=s.uts AND d.track=s.track)
        """,
        (ARTIST, SRC_ALBUM_ID, SRC_ALBUM, ARTIST, DST_ALBUM_ID, DST_ALBUM),
    )
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE artist=? AND album=?",
                     (ARTIST, SRC_ALBUM))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    print(f"[pre] scrobbles under EP name/id: {scr_src}")
    print(f"[pre]   of those, duplicate-timestamp collisions: {collisions} (expect 0)")
    print(f"[pre] aliases pointing at orphan entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] src tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] src album_art rows: {art_src}")
    print(f"[pre] orphan album entity {SRC_ALBUM_ID} present: {entity_src}")

    if (scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
            and entity_src == 0):
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move EP scrobble(s) onto the album ------------------------
    print("\n[1/5] Moving EP scrobbles onto album (text + mbid + album_id + album_artist)")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        f"WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: delete orphaned src album_art row -------------------------
    print("\n[2/5] Deleting orphaned src album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")

    # --- Step 3: delete orphaned src album_tracks rows ---------------------
    print("\n[3/5] Deleting orphaned src album_tracks rows")
    del_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_tracks rows deleted: {del_tracks}")

    # --- Step 4: repoint album alias (idempotent) --------------------------
    print("\n[4/5] Repointing album alias -> album")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 5: delete orphan album entity if no references remain --------
    print("\n[5/5] Dropping orphan album entity")
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
    pc_count = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE artist=? AND album=? AND track='Planet Caravan'",
        (ARTIST, DST_ALBUM),
    )
    print(f"  Planet Caravan total on FBD: {pc_count} (expect 18)")
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
        description="Fold Pantera 'Planet Caravan EP' -> 'Far Beyond Driven' album"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
