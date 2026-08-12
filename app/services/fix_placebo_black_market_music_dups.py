#!/usr/bin/env python3
"""
Fold Placebo "Placebo, Black-eyed" onto the canonical track "Black-Eyed" on
Black Market Music. Re-runnable (idempotent).

Symptom: track #6 of Black Market Music is split across two canonical track
entities. The canonical "Black-Eyed" (track_id 7636, 40 plays, on the album
tracklist with MBID 674d9c04) and a source mis-tag variant "Placebo, Black-eyed"
(track_id 24845, 26 plays) where the artist name got baked into the track title.
The variant carries no MBID, sits on no album_tracks row, and is NOT on the
tracklist — so its 26 plays never count toward the album page's Black-Eyed row
(the page joins album_tracks <-> scrobble on track_id + album_id). The track
therefore reads 40 instead of 66.

A rename that touches only the text will NOT merge (the scrobble still carries
track_id 24845), so this repoints the scrobbles onto the canonical track entity
and folds the variant — same pattern as fix_budka_suflera_pozegnanie_cyganeria.py.

The scrobbles are already on the correct album entity (album_id 354), so this is
a pure track-side fold — no album work. track_id 24845 has exactly 26 scrobbles,
1 alias, and 0 album_tracks rows, so the orphan entity deletes cleanly. 0
timestamp collisions between the variant and canonical scrobbles were confirmed
(no UNIQUE(uts, artist, album, track) violation on the rewrite).

Recurrence: spotify_track_mappings.json carries
  { artist: Placebo, album: "Black Market Music",
    from: "Placebo, Black-eyed", to: "Black-Eyed" }
so sync_lastfm.clean_spotify_track_name() normalizes the variant going forward
and no fresh orphan entity is minted on the next sync.

In one transaction:
  1. scrobble:   UPDATE the variant scrobble(s) -> canonical text + track_id.
  2. track_alias: repoint the variant alias 24845 -> 7636 (idempotent).
  3. track entity: delete orphan 24845 (only after no references remain).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_placebo_black_market_music_dups --dry-run
    python -m app.services.fix_placebo_black_market_music_dups
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Placebo"
ARTIST_ID = 1001

SRC_TRACK_ID = 24845
SRC_TITLE = "Placebo, Black-eyed"

DST_TRACK_ID = 7636
DST_TITLE = "Black-Eyed"

ALBUM_ID = 354  # Black Market Music (already correct on the variant scrobbles)


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
        (ALBUM_ID,),
    ).fetchall()
    total = 0
    for r in rows:
        total += r["plays"]
        flag = "  <-- 0 plays" if r["plays"] == 0 else ""
        print(f"  #{r['track_number']:>2}  {r['plays']:>2} plays  tid={r['track_id']:>6}  {r['track_name']!r}{flag}")
    print(f"  total plays across listed tracks: {total}")
    be = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE artist=? AND track=?",
        (ARTIST, DST_TITLE),
    )
    print(f"  '{DST_TITLE}' total plays (any album): {be} (expect 66)")
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
        description="Fold Placebo 'Placebo, Black-eyed' -> 'Black-Eyed' on Black Market Music"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
