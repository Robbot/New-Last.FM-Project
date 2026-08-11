#!/usr/bin/env python3
"""
Pilot: fix Windows-1250 mojibake tracks (Polish diacritics -> '?') for three
artists — Budka Suflera, Hey, Siekiera. Re-runnable (idempotent).

Each mojibake track_id has a non-mojibake canonical twin already in the DB
(verified against the album_tracks tracklists), so every entry is a pure
track-entity fold: move scrobbles (text + track_id), repoint the mojibake alias
to the canonical entity, delete the orphan mojibake entity. The repointed alias
also means any FUTURE mojibake scrobble of the same name auto-resolves to the
canonical entity, so this self-heals on the next sync.

DST track_id is hardcoded (verified against the track table) rather than
resolved via the Resolver, because the Resolver currently FAILS to find
accented canonical entities: remote commit 0271a87 made the track normalizer
strip accents, but existing aliases were seeded with accents KEPT, so the two
norms never match and resolve_track_id() creates duplicate entities instead of
finding the real one. Using explicit dst ids avoids that. All 14 entries were
verified to (a) have the named canonical entity present with that exact title,
(b) have zero album_tracks references on the mojibake track_id, and (c) have
zero timestamp collisions.

Two entries normalize more than just the '?' (flagged DST_IS_CANONICAL):
  * "A to Nie Tak Mia?o By?"  ->  "To nie tak miało być"   (drops a stray leading "A")
  * "Kto tam Kto jest w ?rodku" -> "Kto tam? Kto jest w Środku?"  (restores ? + Ś)
Both fold onto the existing canonical entity (tid 21178 and 5200 respectively).

Pilot scope: review the dry-run mapping + spellings before applying. The full
sweep covers ~14 Polish artists; this handles 3.

Usage:
    python -m app.services.fix_polish_mojibake_pilot --dry-run
    python -m app.services.fix_polish_mojibake_pilot            # apply
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

# (artist, src_mojibake_track_id, dst_canonical_track_id, corrected_title)
PLAN = [
    # ---------------- Budka Suflera ----------------
    ("Budka Suflera", 26370, 7413, "Ratujmy co się da"),
    ("Budka Suflera", 28324, 21178, "To nie tak miało być"),   # was "A to Nie Tak Mia?o By?"
    ("Budka Suflera", 29174, 5337, "Lepiej bądź na tak"),
    ("Budka Suflera", 28323, 9430, "Szalony koń"),
    # ---------------- Hey ----------------
    ("Hey", 25770, 2136, "Chiński urzędnik państwowy"),
    ("Hey", 25771, 2137, "Miłość! Uwaga! Ratunku! Pomocy!"),
    ("Hey", 25775, 5201, "Nie więcej..."),
    ("Hey", 25769, 2135, "Piersi ćwierć"),
    ("Hey", 25768, 2133, "Umieraj stąd"),
    ("Hey", 25773, 5199, "Boję się o nas"),
    ("Hey", 25774, 5200, "Kto tam? Kto jest w Środku?"),      # folds onto canonical tid 5200
    ("Hey", 25772, 5198, "Stygnę"),
    # ---------------- Siekiera ----------------
    ("Siekiera", 29375, 8334, "Diabelski cień"),
    ("Siekiera", 29376, 8335, "Przekwitło lato"),
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
    print("=" * 78)
    print(f"Polish mojibake track fold — pilot (Budka Suflera, Hey, Siekiera)  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 78)
    print(f"{'artist':<14} {'src_tid':>7} {'dst_tid':>7} {'plays':>5}  "
          f"{'src':<34} -> {'dst'}")
    print("-" * 120)

    total_moved = 0
    details = []

    for artist, src_tid, dst_tid, corrected in PLAN:
        src_row = conn.execute(
            "SELECT title, artist_id FROM track WHERE track_id=?", (src_tid,)
        ).fetchone()
        if not src_row:
            print(f"{artist:<14} {src_tid:>7} {dst_tid:>7}   --    (src entity gone — already folded)")
            continue
        src_title = src_row["title"]

        # Verify the canonical DST entity exists with the expected title.
        dst_row = conn.execute(
            "SELECT title FROM track WHERE track_id=?", (dst_tid,)
        ).fetchone()
        if not dst_row:
            print(f"{artist:<14} {src_tid:>7} {dst_tid:>7}   --    !! dst entity {dst_tid} MISSING — skipping {corrected!r}")
            continue
        if dst_row["title"] != corrected:
            print(f"{artist:<14} {src_tid:>7} {dst_tid:>7}   --    !! dst {dst_tid} title {dst_row['title']!r} != {corrected!r} — skipping")
            continue

        plays = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (src_tid,))
        alias = _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (src_tid,))
        ent = _count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (src_tid,))

        print(f"{artist:<14} {src_tid:>7} {dst_tid:>7} {plays:>5}  "
              f"{src_title!r:<34} -> {corrected!r}")

        # move scrobbles (text + track_id)
        moved = conn.execute(
            "UPDATE scrobble SET track=?, track_id=? WHERE track_id=?",
            (corrected, dst_tid, src_tid),
        ).rowcount
        total_moved += moved

        # repoint mojibake alias -> canonical (so future mojibake scrobbles resolve)
        conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?",
            (dst_tid, src_tid),
        )

        # delete orphan src entity if no references remain
        remaining = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (src_tid,))
                     + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (src_tid,))
                     + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (src_tid,)))
        if remaining == 0:
            conn.execute("DELETE FROM track WHERE track_id=?", (src_tid,))
        else:
            print(f"   !! kept src entity {src_tid}: still {remaining} reference(s)")

        details.append((artist, src_tid, dst_tid, src_title, corrected, moved, alias, ent))

    print("-" * 120)
    print(f"total scrobbles moved: {total_moved}  across {len(details)} track folds")

    # post-state per artist: remaining mid-word '?' mojibake
    print("\n--- post-state: remaining mid-word '?' mojibake scrobbles per pilot artist ---")
    import re
    midq = re.compile(r"[A-Za-z]\?[A-Za-z]")
    for artist in ("Budka Suflera", "Hey", "Siekiera"):
        rows = conn.execute(
            "SELECT DISTINCT track FROM scrobble WHERE artist=? AND track LIKE '%?%'",
            (artist,)).fetchall()
        mid = [r["track"] for r in rows if midq.search(r["track"])]
        print(f"  {artist}: {len(mid)} mid-word mojibake track(s) remain "
              f"({mid if mid else 'none — clean'})")

    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pilot: fold Polish mojibake tracks (Budka Suflera, Hey, Siekiera) onto canonical entities."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
