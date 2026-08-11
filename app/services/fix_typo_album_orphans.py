#!/usr/bin/env python3
"""
Merge three typo-variant album orphans onto their correctly-spelled live entity.

These are zero-scrobble album_art rows whose (artist, album) text is a typo of a
real album that DOES have scrobbles under a different canonical album_id. They
are EXCLUDED from purge_zero_scrobble_albums.py because the right fix is a merge
(repoint or delete-onto-live), not a blind delete that loses the cached cover.

Cases (verified 2026-08-11):
  * Genesis 'Trepass' (4459) -> 'Trespass' (3868)
      3868 has 6 scrobbles + 6 tracks + an alias, but NO album_art. So repoint
      the typo's art row and alias onto 3868, then delete the 4459 entity.
      No PK collision: no existing (Genesis, Trespass) art row, and the typo
      alias norm 'trepass' != 3868's existing 'trespass'.
  * Joy 'Divsion' 'Heart and Soul' (4297) -> Joy Division (113)
      113 already has its own album_art + 126 scrobbles, so the typo row is a
      pure duplicate -> delete its art, alias, and entity. (The artist-level
      'Joy Divsion' typo is a separate merge_artists concern; out of scope.)
  * Steve Howe 'Beginings' (4388) -> 'Beginnings' (3346)
      3346 already has album_art + 18 scrobbles -> delete the typo orphan.

Run this BEFORE purge_zero_scrobble_albums.py. It takes the shared backup, so
run the purge with --no-backup immediately after.

Usage:
    python -m app.services.fix_typo_album_orphans --dry-run
    python -m app.services.fix_typo_album_orphans            # apply for real
"""

import argparse
import sqlite3

from app.logging_config import get_logger
from app.services.backup_db import checkpoint_wal, create_backup, DB_PATH, BACKUP_DIR

logger = get_logger(__name__)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# Each case: (orphan_album_id, action). 'repoint' moves art+alias onto the live
# id then deletes the orphan entity; 'delete' just removes the orphan outright.
CASES = [
    {"orphan": 4459, "live": 3868, "artist": "Genesis", "from_album": "Trepass",
     "to_album": "Trespass", "action": "repoint"},
    {"orphan": 4297, "live": 113, "artist": "Joy Divsion", "from_album": "Heart and Soul",
     "to_album": "Heart and Soul", "action": "delete"},
    {"orphan": 4388, "live": 3346, "artist": "Steve Howe", "from_album": "Beginings",
     "to_album": "Beginnings", "action": "delete"},
]


def describe_case(conn, c: dict) -> dict:
    """Pre-flight: confirm the live entity exists and report ref counts."""
    orphan, live = c["orphan"], c["live"]
    c["orphan_art"] = conn.execute(
        "SELECT COUNT(*) FROM album_art WHERE album_id=?", (orphan,)).fetchone()[0]
    c["orphan_alias"] = conn.execute(
        "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (orphan,)).fetchone()[0]
    c["live_scrobs"] = conn.execute(
        "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (live,)).fetchone()[0]
    c["live_art"] = conn.execute(
        "SELECT COUNT(*) FROM album_art WHERE album_id=?", (live,)).fetchone()[0]
    return c


def apply_case(conn, c: dict) -> None:
    orphan, live = c["orphan"], c["live"]
    if c["action"] == "repoint":
        # Move the typo's art row onto the live entity (rename text + album_id).
        conn.execute(
            "UPDATE album_art SET album=?, album_id=? WHERE album_id=?",
            (c["to_album"], live, orphan),
        )
        # Repoint the typo alias so the misspelling still resolves to the live id.
        conn.execute("UPDATE album_alias SET album_id=? WHERE album_id=?", (live, orphan))
    else:  # delete
        conn.execute("DELETE FROM album_art WHERE album_id=?", (orphan,))
        conn.execute("DELETE FROM album_alias WHERE album_id=?", (orphan,))
    # Either way: no scrobbles/tracks live on the orphan; drop the entity last.
    conn.execute("DELETE FROM album_tracks WHERE album_id=?", (orphan,))
    conn.execute("DELETE FROM album WHERE album_id=?", (orphan,))


def run(dry_run: bool, do_backup: bool) -> dict:
    conn = get_connection()
    for c in CASES:
        describe_case(conn, c)

    backup_path = None
    if not dry_run and do_backup:
        logger.info("Checkpointing WAL and backing up database...")
        checkpoint_wal(DB_PATH)
        backup_path = create_backup(DB_PATH, BACKUP_DIR)
        if backup_path is None:
            conn.close()
            raise RuntimeError("Backup failed; aborting.")
        logger.info("Backup created: %s", backup_path)

    try:
        if not dry_run:
            for c in CASES:
                apply_case(conn, c)
            conn.commit()
    except sqlite3.Error:
        conn.rollback()
        conn.close()
        raise

    conn.close()
    return {"dry_run": dry_run, "cases": CASES, "backup_path": str(backup_path) if backup_path else None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge 3 typo-variant album orphans onto live entities.")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--no-backup", action="store_true", help="Skip the pre-run backup")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, do_backup=not args.no_backup)
    prefix = "[DRY RUN] " if result["dry_run"] else ""
    for c in result["cases"]:
        verb = "repoint onto" if c["action"] == "repoint" else "delete (live already has art)"
        print(f"{prefix}{c['artist']} {c['from_album']!r} (id {c['orphan']}) -> {verb} "
              f"id {c['live']} ({c['to_album']!r})")
        print(f"    orphan refs: art={c['orphan_art']} alias={c['orphan_alias']} | "
              f"live: scrobs={c['live_scrobs']} art={c['live_art']}")
    if result["backup_path"]:
        print(f"{prefix}Backup: {result['backup_path']}")
    if not args.dry_run:
        print("\nNow run: python -m app.services.purge_zero_scrobble_albums --no-backup")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
