#!/usr/bin/env python3
"""
Purge zero-scrobble orphan albums (album_art row + canonical entity + alias
that nothing ever plays).

An album is a "true-zero orphan" when BOTH hold:
  1. canonical album_id  -> no scrobble.album_id points at it, AND
  2. exact text match    -> no scrobble row shares its (artist, album) text.

These are genuine orphans: album_art + album entity + album_alias exist but
nothing plays them. Safe to purge. See reports/zero_scrobble_albums.md.

Two classes are handled:
  * Class A - album_art rows whose album_id is a true-zero orphan (has art).
  * Class B - bare album entities with NO refs at all (no scrobble.album_id,
              no album_art, no album_alias, no album_tracks). The report's
              album_art-derived query misses these; they are equally dead.

Deletion is FK-safe (PRAGMA foreign_keys=ON): for each album_id we delete
album_alias, album_art, album_tracks (children) before the album row (parent).
A timestamped backup is taken before any write. Cover files under
app/static/covers/ are removed only when an orphan's image column actually
points at a local static path (most orphans hold remote Last.fm URLs, so
usually none).

The three known typo-variants (Genesis 'Trepass', Joy 'Divsion', Steve Howe
'Beginings') are EXCLUDED by default because they should be merged onto their
correctly-spelled live entity, not deleted. Handle them with
fix_typo_album_orphans.py.

Usage:
    python -m app.services.purge_zero_scrobble_albums --dry-run
    python -m app.services.purge_zero_scrobble_albums            # apply for real
    python -m app.services.purge_zero_scrobble_albums --exclude 4297,4459
    python -m app.services.purge_zero_scrobble_albums --no-backup   # skip backup
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger
from app.services.backup_db import checkpoint_wal, create_backup, DB_PATH, BACKUP_DIR

logger = get_logger(__name__)

# Typo-variant album_ids that should be MERGED (not bulk-deleted) onto their
# correctly-spelled live entity. Handled by fix_typo_album_orphans.py.
DEFAULT_EXCLUDE = {4459, 4297, 4388}  # Genesis 'Trepass', Joy 'Divsion', Steve Howe 'Beginings'

COVERS_DIR = DB_PATH.parent.parent / "app" / "static" / "covers"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def find_class_a_orphans(conn) -> list:
    """album_art rows that are true-zero orphans (have art + entity + alias)."""
    return conn.execute(
        """
        SELECT aa.album_id, aa.artist, aa.album
        FROM album_art aa
        WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
          AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist = aa.artist AND s.album = aa.album) = 0
        ORDER BY lower(aa.artist), lower(aa.album)
        """
    ).fetchall()


def find_class_b_orphans(conn) -> list:
    """Bare album entities with no scrobble / art / alias / tracks refs at all."""
    return conn.execute(
        """
        SELECT a.album_id, a.title AS album, a.artist_id
        FROM album a
        WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = a.album_id) = 0
          AND (SELECT COUNT(*) FROM album_art aa WHERE aa.album_id = a.album_id) = 0
          AND (SELECT COUNT(*) FROM album_alias al WHERE al.album_id = a.album_id) = 0
          AND (SELECT COUNT(*) FROM album_tracks t WHERE t.album_id = a.album_id) = 0
        ORDER BY a.album_id
        """
    ).fetchall()


def local_cover_files(conn, album_ids: list[int]) -> list[Path]:
    """Cover files under static/covers/ referenced by the given orphans' image cols."""
    files: list[Path] = []
    if not album_ids:
        return files
    placeholders = ",".join("?" for _ in album_ids)
    rows = conn.execute(
        f"""
        SELECT DISTINCT image_small, image_medium, image_large, image_xlarge
        FROM album_art WHERE album_id IN ({placeholders})
        """,
        album_ids,
    ).fetchall()
    for r in rows:
        for col in ("image_small", "image_medium", "image_large", "image_xlarge"):
            val = r[col]
            if val and "/static/covers/" in val:
                name = val.rsplit("/", 1)[-1]
                p = COVERS_DIR / name
                if p.exists() and p not in files:
                    files.append(p)
    return files


def purge(dry_run: bool, exclude: set[int], do_backup: bool) -> dict:
    conn = get_connection()

    class_a = [r for r in find_class_a_orphans(conn) if r["album_id"] not in exclude]
    class_b = [r for r in find_class_b_orphans(conn) if r["album_id"] not in exclude]

    excluded_a = [r for r in find_class_a_orphans(conn) if r["album_id"] in exclude]
    all_ids = [r["album_id"] for r in class_a] + [r["album_id"] for r in class_b]

    # Pre-counts of what would be removed.
    counts = {
        "album": len(all_ids),
        "album_alias": 0,
        "album_art": 0,
        "album_tracks": 0,
        "cover_files": 0,
    }
    if all_ids:
        ph = ",".join("?" for _ in all_ids)
        counts["album_alias"] = conn.execute(
            f"SELECT COUNT(*) FROM album_alias WHERE album_id IN ({ph})", all_ids
        ).fetchone()[0]
        counts["album_art"] = conn.execute(
            f"SELECT COUNT(*) FROM album_art WHERE album_id IN ({ph})", all_ids
        ).fetchone()[0]
        counts["album_tracks"] = conn.execute(
            f"SELECT COUNT(*) FROM album_tracks WHERE album_id IN ({ph})", all_ids
        ).fetchone()[0]

    covers = local_cover_files(conn, all_ids) if all_ids else []
    counts["cover_files"] = len(covers)

    if dry_run:
        conn.close()
        return {
            "dry_run": True,
            "class_a": class_a,
            "class_b": class_b,
            "excluded": excluded_a,
            "counts": counts,
            "covers": covers,
            "backup_path": None,
        }

    # --- real run ---
    backup_path = None
    if do_backup:
        logger.info("Checkpointing WAL and backing up database...")
        checkpoint_wal(DB_PATH)
        backup_path = create_backup(DB_PATH, BACKUP_DIR)
        if backup_path is None:
            raise RuntimeError("Backup failed; aborting purge.")
        logger.info("Backup created: %s", backup_path)

    try:
        for album_id in all_ids:
            conn.execute("DELETE FROM album_alias  WHERE album_id = ?", (album_id,))
            conn.execute("DELETE FROM album_art    WHERE album_id = ?", (album_id,))
            conn.execute("DELETE FROM album_tracks WHERE album_id = ?", (album_id,))
            conn.execute("DELETE FROM album        WHERE album_id = ?", (album_id,))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        conn.close()
        raise

    # Remove local cover files outside the txn (filesystem, not sqlite).
    for p in covers:
        try:
            p.unlink()
            logger.info("Deleted cover file %s", p.name)
        except OSError as e:
            logger.warning("Could not delete cover %s: %s", p, e)

    conn.close()
    return {
        "dry_run": False,
        "class_a": class_a,
        "class_b": class_b,
        "excluded": excluded_a,
        "counts": counts,
        "covers": covers,
        "backup_path": str(backup_path) if backup_path else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Purge zero-scrobble orphan albums (FK-safe, backs up first)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--exclude",
        default=",".join(str(i) for i in sorted(DEFAULT_EXCLUDE)),
        help="Comma-separated album_ids to skip (default: the 3 typo-variants)",
    )
    parser.add_argument("--no-backup", action="store_true", help="Skip the pre-purge backup")
    args = parser.parse_args()

    exclude = {int(x) for x in args.exclude.split(",") if x.strip()} if args.exclude else set()

    result = purge(dry_run=args.dry_run, exclude=exclude, do_backup=not args.no_backup)
    prefix = "[DRY RUN] " if result["dry_run"] else ""
    c = result["counts"]

    print(f"{prefix}Orphan albums to delete: {c['album']}")
    print(f"{prefix}  Class A (album_art orphans): {len(result['class_a'])}")
    print(f"{prefix}  Class B (bare entity orphans): {len(result['class_b'])}")
    print(f"{prefix}Rows to remove -> album_alias: {c['album_alias']}, "
          f"album_art: {c['album_art']}, album_tracks: {c['album_tracks']}")
    print(f"{prefix}Local cover files to delete: {c['cover_files']}")
    if result["excluded"]:
        print(f"{prefix}Excluded (merge via fix_typo_album_orphans.py): "
              f"{[r['album_id'] for r in result['excluded']]}")
    if result["backup_path"]:
        print(f"{prefix}Backup: {result['backup_path']}")

    if args.dry_run:
        print(f"\n{prefix}Class A orphans (album_id | artist | album):")
        for r in result["class_a"]:
            print(f"    {r['album_id']:<6} {r['artist']} | {r['album']}")
        if result["class_b"]:
            print(f"\n{prefix}Class B orphans (album_id | title | artist_id):")
            for r in result["class_b"]:
                print(f"    {r['album_id']:<6} {r['album']} | artist_id={r['artist_id']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
