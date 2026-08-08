#!/usr/bin/env python3
"""
Fold the Foreigner track entity "Tramontane - Instrumental" (track_id 10062)
into the tracklist-canonical "Tramontane (Instrumental)" (track_id 31129).
Re-runnable.

Symptom: on the canonical box-set album page (album_id 1827), track #21
"Tramontane (Instrumental)" shows 0 plays because its 2 scrobbles sit on a
DIFFERENT track entity — "Tramontane - Instrumental" (track_id 10062) — so the
album-page join (album_tracks.track_id = scrobble.track_id) misses them.

The two never auto-merged because the track normalizer lowercases but does not
treat " - " and " (..) " as equivalent, so "tramontane - instrumental" and
"tramontane (instrumental)" resolved to separate aliases/entities. 10062 is
scrobble-only (no tracklist row); 31129 owns the tracklist (track #21), so the
parens form is canonical and 10062 folds into it. (Cf. the ascii->diacritic
track folds in move_bombowe_hity.py.)

In one transaction:
  1. scrobble (2 rows): track_id 10062 -> 31129. (track text left as-is; the
     album page joins on track_id+album_id, and the canonical title comes from
     the track entity / tracklist, matching the Big Cyc track-fold precedent.)
  2. track_alias: carry the variant norm "tramontane - instrumental" onto 31129
     (read->delete->insert; the norm differs from 31129's existing
     "tramontane (instrumental)" so a future dash-tagged scrobble resolves to
     canonical instead of re-splitting).
  3. track entity: delete the now-empty orphan 10062.

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_foreigner_tramontane_track --dry-run
    python -m app.services.fix_foreigner_tramontane_track
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

SRC_TRACK_ID = 10062   # "Tramontane - Instrumental" — scrobble-only orphan
DST_TRACK_ID = 31129   # "Tramontane (Instrumental"  — tracklist owner (track #21)

ALBUM_ID = 1827  # canonical Foreigner box set, for the post-state join


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


def _track_refs(conn, track_id: int) -> int:
    """Total references to a track entity from scrobble/album_tracks/track_alias."""
    return (
        _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (track_id,))
        + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (track_id,))
        + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (track_id,))
    )


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, dry_run: bool) -> int:
    print("=" * 72)
    print(f"Foreigner track fold: track_id {SRC_TRACK_ID} -> {DST_TRACK_ID}  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    src_title = conn.execute("SELECT title FROM track WHERE track_id=?", (SRC_TRACK_ID,)).fetchone()
    dst_title = conn.execute("SELECT title FROM track WHERE track_id=?", (DST_TRACK_ID,)).fetchone()
    print(f"[pre] src {SRC_TRACK_ID}: {src_title['title']!r}" if src_title else f"[pre] src {SRC_TRACK_ID}: (gone)")
    print(f"[pre] dst {DST_TRACK_ID}: {dst_title['title']!r}" if dst_title else f"[pre] dst {DST_TRACK_ID}: (MISSING — abort)")

    if not dst_title:
        print("\n[ABORT] canonical track entity missing.")
        conn.rollback()
        return 1

    scr_src = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (SRC_TRACK_ID,))
    alias_src = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (SRC_TRACK_ID,))
    entity_src = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (SRC_TRACK_ID,))
    print(f"[pre] scrobbles on src: {scr_src}")
    print(f"[pre] aliases on src: {alias_src}")
    print(f"[pre] tracklist rows on src: {tracks_src} (expect 0 — scrobble-only)")
    print(f"[pre] src entity present: {entity_src}")

    # src must be scrobble-only for an unambiguous fold
    if tracks_src:
        print(f"\n[ABORT] src has {tracks_src} tracklist ref(s); expected 0 (scrobble-only). "
              f"Investigate before proceeding.")
        conn.rollback()
        return 1

    if scr_src == 0 and alias_src == 0 and entity_src == 0:
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move scrobbles onto canonical track -----------------------
    print("\n[1/3] Moving scrobbles onto canonical track")
    moved = conn.execute(
        "UPDATE scrobble SET track_id=? WHERE track_id=?",
        (DST_TRACK_ID, SRC_TRACK_ID),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: carry the variant alias onto canonical -------------------
    print("\n[2/3] Carrying variant alias onto canonical track")
    src_aliases = conn.execute(
        "SELECT artist_id, norm_title FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,)
    ).fetchall()
    conn.execute("DELETE FROM track_alias WHERE track_id=?", (SRC_TRACK_ID,))
    copied = 0
    for a in src_aliases:
        copied += conn.execute(
            "INSERT OR IGNORE INTO track_alias (artist_id, norm_title, track_id) VALUES (?,?,?)",
            (a["artist_id"], a["norm_title"], DST_TRACK_ID),
        ).rowcount
    print(f"      aliases carried: {copied} of {len(src_aliases)}")

    # --- Step 3: delete orphan src entity ----------------------------------
    print("\n[3/3] Deleting empty orphan track entity")
    if _track_refs(conn, SRC_TRACK_ID) == 0:
        d = conn.execute("DELETE FROM track WHERE track_id=?", (SRC_TRACK_ID,)).rowcount
        print(f"      deleted orphan {SRC_TRACK_ID}: {d} row(s)")
    else:
        print(f"      !! kept orphan {SRC_TRACK_ID}: still {_track_refs(conn, SRC_TRACK_ID)} reference(s)")

    # --- post-state: same join the album page uses -------------------------
    print(f"\n--- post-state (tracklist row for canonical track on album {ALBUM_ID}) ---")
    row = conn.execute(
        """
        SELECT at.track_number, at.track AS track_name, at.track_id,
               COUNT(s.id) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble s ON s.track_id = at.track_id AND s.album_id = at.album_id
        WHERE at.track_id = ? AND at.album_id = ?
        GROUP BY at.track_id
        """,
        (DST_TRACK_ID, ALBUM_ID),
    ).fetchone()
    if row:
        flag = "  <-- 0 plays" if row["plays"] == 0 else ""
        print(f"  #{row['track_number']:>2}  {row['plays']:>2} plays  tid={row['track_id']:>6}  {row['track_name']!r}{flag}")
    print(f"  scrobbles still on src track_id {SRC_TRACK_ID}: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE track_id=?', (SRC_TRACK_ID,))} (expect 0)")
    print(f"  src entity remaining: "
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
        description="Fold Foreigner 'Tramontane - Instrumental' (track_id 10062) -> 'Tramontane (Instrumental)' (31129)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
