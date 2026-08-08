#!/usr/bin/env python3
"""
Fold The Strokes "Going Shopping" single into the "Reality Awaits" album.
Re-runnable (idempotent).

Symptom: one release is split across two canonical album entities. The "Going
Shopping" single (album_id 4030) and "Reality Awaits" (album_id 4028) share the
scrobble-level album_mbid a5a80a78... and the single's 2 plays are EXACT
duplicate-timestamp recordings of the album's 2 plays:

    Going Shopping | Going Shopping | uts 1776955439  ==  Reality Awaits | Going Shopping | uts 1776955439
    Going Shopping | Going Shopping | uts 1776968167  ==  Reality Awaits | Going Shopping | uts 1776968167

(same artist, track, mbid, and uts — only the album text differs). So this is
NOT a rename/move: "Reality Awaits" already owns both plays, and rewriting the
single rows onto it would violate UNIQUE(uts, artist, album, track). The correct
fix is to DELETE the duplicate single rows and fold the single entity into the
album. Contrast fix_foreigner_very_best_ellipsis.py, which RENAMES because its
variant scrobbles carry distinct timestamps (no collision).

The shared canonical track entity (track_id 29698, album_id NULL) needs no
work — this is a pure album-side fold, no track-entity merging.

In one transaction:
  1. scrobble: DELETE single rows whose (uts, track) already exist on the album
     (dedup); UPDATE any genuinely distinct single rows onto the album (move).
  2. album_art:    delete the orphan single row.
  3. album_tracks: delete the orphan single row.
  4. album_alias:  repoint 'going shopping' 4030 -> 4028 (idempotent).
  5. album entity: delete orphan 4030 (only after no references remain).

The canonical album mbid is intentionally left NULL (MBID is a conservative
hint, never force-set; the scrobble-level album_mbid a5a80a78... is preserved).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_strokes_going_shopping_single --dry-run
    python -m app.services.fix_strokes_going_shopping_single
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "The Strokes"
ARTIST_ID = 1395

SRC_ALBUM = "Going Shopping"
SRC_ALBUM_ID = 4030
SRC_MBID = None

DST_ALBUM = "Reality Awaits"
DST_ALBUM_ID = 4028
DST_MBID = "a5a80a78-a763-4d07-92fa-dbe000aaee93"


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
    dst_scr_sql = "artist=? AND (album_id=? OR album=?)"
    dst_scr_params = (ARTIST, DST_ALBUM_ID, DST_ALBUM)

    print("=" * 72)
    print(f"The Strokes single fold: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    # single rows that duplicate an album play on (uts, track) -> dedup-delete
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
    to_move = scr_src - collisions  # distinct single plays with no album twin
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE artist=? AND album=?",
                     (ARTIST, SRC_ALBUM))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    print(f"[pre] scrobbles under single name/id: {scr_src}")
    print(f"[pre]   of those, duplicate-timestamp collisions (delete): {collisions}")
    print(f"[pre]   of those, distinct plays to move: {to_move}")
    print(f"[pre] aliases pointing at orphan entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] src tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] src album_art rows: {art_src}")
    print(f"[pre] orphan album entity {SRC_ALBUM_ID} present: {entity_src}")

    if (scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
            and entity_src == 0):
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1a: dedup-delete single rows that duplicate an album play ------
    print("\n[1/5] Deleting duplicate-timestamp single scrobbles (dedup)")
    deduped = conn.execute(
        """
        DELETE FROM scrobble
        WHERE id IN (
            SELECT s.id FROM scrobble s
            WHERE s.artist=? AND (s.album_id=? OR s.album=?)
              AND EXISTS (SELECT 1 FROM scrobble d
                          WHERE d.artist=? AND (d.album_id=? OR d.album=?)
                            AND d.uts=s.uts AND d.track=s.track)
        )
        """,
        (ARTIST, SRC_ALBUM_ID, SRC_ALBUM, ARTIST, DST_ALBUM_ID, DST_ALBUM),
    ).rowcount
    print(f"      scrobbles dedup-deleted: {deduped}")

    # --- Step 1b: move any remaining distinct single scrobbles onto album ---
    print("\n[2/5] Moving remaining distinct single scrobbles onto album")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        f"WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: delete orphaned src album_art row -------------------------
    print("\n[3/5] Deleting orphaned src album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")

    # --- Step 3: delete orphaned src album_tracks rows ---------------------
    print("\n[4/5] Deleting orphaned src album_tracks rows")
    del_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_tracks rows deleted: {del_tracks}")

    # --- Step 4: repoint album alias (idempotent) --------------------------
    print("\n[5/5] Repointing album alias -> album + dropping orphan entity")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 5: delete orphan album entity if no references remain --------
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
    print(f"  total plays: {total}")
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
        description="Fold The Strokes 'Going Shopping' single -> 'Reality Awaits' album"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
