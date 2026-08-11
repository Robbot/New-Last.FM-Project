#!/usr/bin/env python3
"""
Collapse duplicate canonical album entities created by the album_art backfill.

Symptom: an album_art row's album_id points at a "dead" canonical album entity
that has 0 scrobbles, while the real scrobbles for the same (artist, album) text
live under a DIFFERENT, scrobble-seeded "live" album_id. Root cause: an album_art
backfill minted fresh high-id album entities (~4100+) instead of reusing the
scrobble-seeded ones, so every contributing artist on a big compilation
("22 Polish Punk Classics", "50 Greatest Pieces of Classical Music", soundtrack
OSTs, ...) got its own redundant entity that the art row hangs off.

This is a REPOINT, not a delete: these albums have plays. For each mismatch
(dead_id -> live_id, both sharing the same title):

    album_art.album_id    dead -> live   (art is stranded on the dead entity)
    album_alias.album_id  dead -> live   (repoint the name-variant alias)
    album_tracks.album_id dead -> live   (move the cached tracklist along)
    album row             DELETE dead    (nothing references it once repointed)

Verified collision-free before each run: no dead alias clashes with a live or
sibling alias (album_alias PK is (artist_id, norm_title)), and no dead track
clashes with an existing live track (album_tracks PK is (artist, album, track)).
Each dead entity maps to exactly one live id. Scrobble rows are untouched (they
already point at live).

A timestamped backup is taken before any write. The album detail page resolves
metadata via album_id, so after the repoint the previously-stranded art/tracklist
shows up on the live album automatically.

Usage:
    python -m app.services.repoint_album_art_entities --dry-run
    python -m app.services.repoint_album_art_entities            # apply for real
    python -m app.services.repoint_album_art_entities --no-backup
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


def find_mismatches(conn) -> list[sqlite3.Row]:
    """One row per dead album entity -> its single live album id."""
    return conn.execute(
        """
        SELECT DISTINCT
            aa.album_id AS dead_id,
            (SELECT s.album_id FROM scrobble s
             WHERE s.artist = aa.artist AND s.album = aa.album LIMIT 1) AS live_id,
            aa.artist, aa.album,
            (SELECT COUNT(*) FROM scrobble s
             WHERE s.artist = aa.artist AND s.album = aa.album) AS plays
        FROM album_art aa
        WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
          AND (SELECT COUNT(*) FROM scrobble s
               WHERE s.artist = aa.artist AND s.album = aa.album) > 0
        ORDER BY aa.album_id
        """
    ).fetchall()


def precheck_safe(conn, mismatches: list[sqlite3.Row]) -> None:
    """Abort loudly if the collision-free assumptions no longer hold."""
    if not mismatches:
        return
    dead_ids = [m["dead_id"] for m in mismatches]

    # alias: a dead alias must not clash with a live (or sibling) alias
    alias_clash = conn.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT a1.artist_id, a1.norm_title, m.live_id
          FROM album_alias a1
          JOIN (SELECT DISTINCT aa.album_id AS dead_id,
                       (SELECT s.album_id FROM scrobble s WHERE s.artist=aa.artist
                        AND s.album=aa.album LIMIT 1) AS live_id
                FROM album_art aa
                WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id=aa.album_id)=0
                  AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist=aa.artist
                       AND s.album=aa.album)>0) m ON a1.album_id=m.dead_id
          GROUP BY a1.artist_id, a1.norm_title, m.live_id
          HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    if alias_clash:
        raise RuntimeError(
            f"{alias_clash} alias collision(s) detected; aborting before write. "
            "Re-investigate album_alias PK handling."
        )

    # tracks: a dead track must not clash with an existing live track
    track_clash = conn.execute(
        """
        SELECT COUNT(*)
        FROM album_art aa
        JOIN album_tracks td ON td.album_id = aa.album_id
        WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
          AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist = aa.artist AND s.album = aa.album) > 0
          AND EXISTS (
            SELECT 1 FROM scrobble s
            JOIN album_tracks tl ON tl.album_id = s.album_id
            WHERE s.artist = aa.artist AND s.album = aa.album
              AND tl.artist = td.artist AND tl.album = td.album AND tl.track = td.track
          )
        """
    ).fetchone()[0]
    if track_clash:
        raise RuntimeError(
            f"{track_clash} album_tracks PK collision(s) detected; aborting before write."
        )


def count_targets(conn, dead_ids: list[int]) -> dict:
    ph = ",".join("?" for _ in dead_ids)
    return {
        "album": len(dead_ids),
        "alias": conn.execute(f"SELECT COUNT(*) FROM album_alias WHERE album_id IN ({ph})", dead_ids).fetchone()[0],
        "art": conn.execute(f"SELECT COUNT(*) FROM album_art WHERE album_id IN ({ph})", dead_ids).fetchone()[0],
        "tracks": conn.execute(f"SELECT COUNT(*) FROM album_tracks WHERE album_id IN ({ph})", dead_ids).fetchone()[0],
    }


def run(dry_run: bool, do_backup: bool) -> dict:
    conn = get_connection()
    mismatches = find_mismatches(conn)
    precheck_safe(conn, mismatches)

    dead_ids = [m["dead_id"] for m in mismatches]
    live_ids = sorted({m["live_id"] for m in mismatches})
    counts = count_targets(conn, dead_ids) if dead_ids else {"album": 0, "alias": 0, "art": 0, "tracks": 0}

    if dry_run:
        conn.close()
        return {"dry_run": True, "mismatches": mismatches, "live_ids": live_ids,
                "counts": counts, "backup_path": None}

    backup_path = None
    if do_backup:
        logger.info("Checkpointing WAL and backing up database...")
        checkpoint_wal(DB_PATH)
        backup_path = create_backup(DB_PATH, BACKUP_DIR)
        if backup_path is None:
            conn.close()
            raise RuntimeError("Backup failed; aborting repoint.")
        logger.info("Backup created: %s", backup_path)

    try:
        for m in mismatches:
            dead, live = m["dead_id"], m["live_id"]
            conn.execute("UPDATE album_art    SET album_id = ? WHERE album_id = ?", (live, dead))
            conn.execute("UPDATE album_alias  SET album_id = ? WHERE album_id = ?", (live, dead))
            conn.execute("UPDATE album_tracks SET album_id = ? WHERE album_id = ?", (live, dead))
            conn.execute("DELETE FROM album WHERE album_id = ?", (dead,))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        conn.close()
        raise

    remaining = conn.execute(
        """
        SELECT COUNT(*) FROM album_art aa
        WHERE (SELECT COUNT(*) FROM scrobble s WHERE s.album_id = aa.album_id) = 0
          AND (SELECT COUNT(*) FROM scrobble s WHERE s.artist = aa.artist AND s.album = aa.album) > 0
        """
    ).fetchone()[0]
    conn.close()

    return {"dry_run": False, "mismatches": mismatches, "live_ids": live_ids,
            "counts": counts, "backup_path": str(backup_path) if backup_path else None,
            "remaining": remaining}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repoint album_art/alias/tracks off dead duplicate album entities onto their live entity."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--no-backup", action="store_true", help="Skip the pre-run backup")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, do_backup=not args.no_backup)
    prefix = "[DRY RUN] " if result["dry_run"] else ""
    c = result["counts"]

    print(f"{prefix}Dead duplicate entities to collapse: {c['album']}")
    print(f"{prefix}Live entities receiving them: {len(result['live_ids'])}")
    print(f"{prefix}Rows to repoint -> album_alias: {c['alias']}, "
          f"album_art: {c['art']}, album_tracks: {c['tracks']}")
    if result["backup_path"]:
        print(f"{prefix}Backup: {result['backup_path']}")

    if args.dry_run:
        print(f"\n{prefix}Top live targets (by # of dead entities fanning in):")
        by_live: dict[int, int] = {}
        for m in result["mismatches"]:
            by_live[m["live_id"]] = by_live.get(m["live_id"], 0) + 1
        for live_id, n in sorted(by_live.items(), key=lambda kv: -kv[1])[:12]:
            row = next(m for m in result["mismatches"] if m["live_id"] == live_id)
            print(f"    live {live_id:<6} <- {n:>3} dead  | {row['artist']} | {row['album']}")
    else:
        print(f"{prefix}Remaining mismatches after run: {result['remaining']} (expect 0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
