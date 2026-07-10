#!/usr/bin/env python3
"""
Phase 1: seed canonical entity tables and backfill *_id columns.

Populates `artist` / `album` / `track` (+ `*_alias`) from the existing
free-text data, then sets the nullable `*_id` FK columns on every dependent
table. Idempotent: re-runs only touch rows where the id is still NULL, and the
entity tables dedupe via the alias tables.

Conservative identity policy (see memory: project-entity-resolver-mbid-policy):
MBID is a hint, never a merge key. Only case/accent variants collapse
automatically. Substantive merges are deferred to the Phase 4 manual tool.

Usage:
    python -m app.services.seed_entities            # backfill + verify
    python -m app.services.seed_entities --verify   # stats only, no writes
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.logging_config import get_logger
from app.services import backup_db
from app.db.entities import Resolver
from app.db.connections import _normalize_for_matching

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"
BACKUP_DIR = Path(__file__).parent.parent.parent / "files" / "backups"
MAPPINGS_PATH = Path(__file__).parent / "artist_name_mappings.json"


# --- bulk backfill helper -------------------------------------------------

def _bulk_backfill(conn, table: str, id_col: str, key_cols: list[str],
                   mapping: dict[tuple, int]) -> int:
    """Set `table`.`id_col` for rows matching `key_cols` via a temp table.

    `mapping` maps a tuple of key-column values to the id to assign. Builds a
    temp table, then runs a single correlated-subquery UPDATE. Uses NULL-safe
    `IS` comparison so nullable key columns (e.g. album_artist) match correctly.
    Only touches rows where id_col IS NULL (idempotent). Returns rows updated.
    """
    if not mapping:
        return 0
    tmp = f"tmp_{table}_{id_col}"
    conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    col_defs = ", ".join([f"{c} TEXT" for c in key_cols] + [f"{id_col} INTEGER"])
    conn.execute(f"CREATE TEMP TABLE {tmp} ({col_defs})")
    rows = [list(keys) + [iid] for keys, iid in mapping.items()]
    placeholders = ", ".join(["?"] * (len(key_cols) + 1))
    conn.executemany(f"INSERT INTO {tmp} VALUES ({placeholders})", rows)
    conn.execute(f"CREATE INDEX tmp_{tmp}_ix ON {tmp} ({', '.join(key_cols)})")

    match = " AND ".join(f"tmp.{c} IS {table}.{c}" for c in key_cols)
    sql = (f"UPDATE {table} SET {id_col} = "
           f"(SELECT tmp.{id_col} FROM {tmp} tmp WHERE {match}) "
           f"WHERE {id_col} IS NULL")
    cur = conn.execute(sql)
    updated = cur.rowcount
    conn.execute(f"DROP TABLE IF EXISTS {tmp}")
    return updated


# --- per-table backfill steps --------------------------------------------

def _backfill_artist_id(conn, r: Resolver, table: str, name_col: str) -> int:
    rows = conn.execute(
        f"SELECT DISTINCT {name_col} AS n FROM {table} "
        f"WHERE {name_col} IS NOT NULL AND artist_id IS NULL"
    ).fetchall()
    mapping = {(row["n"],): r.resolve_artist_id(row["n"]) for row in rows}
    return _bulk_backfill(conn, table, "artist_id", [name_col], mapping)


def _backfill_album_id_scrobble(conn, r: Resolver) -> int:
    """Album id on scrobble, keyed by (artist, album, album_artist).

    Owner is the VA sentinel when album_artist reads as 'Various Artists',
    otherwise the scrobble artist — matching how the album is keyed.
    """
    rows = conn.execute(
        "SELECT DISTINCT artist, album, album_artist FROM scrobble "
        "WHERE album_id IS NULL"
    ).fetchall()
    mapping = {}
    for row in rows:
        artist, album, aa = row["artist"], row["album"], row["album_artist"]
        owner = r.va_sentinel_id if Resolver._is_various_artists(aa) else r.resolve_artist_id(artist)
        mapping[(artist, album, aa)] = r.resolve_album_id(owner, album, album_artist_text=aa)
    return _bulk_backfill(conn, "scrobble", "album_id",
                          ["artist", "album", "album_artist"], mapping)


def _backfill_album_id_simple(conn, r: Resolver, table: str) -> int:
    """Album id on tables without an album_artist column (album_art, album_tracks).

    Owner is the table's own artist. VA compilations therefore fragment by
    per-track artist here, matching the legacy string-keyed behavior.
    """
    rows = conn.execute(
        f"SELECT DISTINCT artist, album FROM {table} "
        f"WHERE album_id IS NULL AND artist IS NOT NULL"
    ).fetchall()
    mapping = {}
    for row in rows:
        owner = r.resolve_artist_id(row["artist"])
        mapping[(row["artist"], row["album"])] = r.resolve_album_id(owner, row["album"])
    return _bulk_backfill(conn, table, "album_id", ["artist", "album"], mapping)


def _backfill_track_id(conn, r: Resolver, table: str) -> int:
    rows = conn.execute(
        f"SELECT DISTINCT artist, track FROM {table} "
        f"WHERE track_id IS NULL AND artist IS NOT NULL AND track IS NOT NULL"
    ).fetchall()
    mapping = {}
    for row in rows:
        aid = r.resolve_artist_id(row["artist"])
        mapping[(row["artist"], row["track"])] = r.resolve_track_id(aid, row["track"])
    return _bulk_backfill(conn, table, "track_id", ["artist", "track"], mapping)


# --- artist_name_mappings.json ingestion ---------------------------------

def _apply_artist_mappings(conn, r: Resolver) -> int:
    """Register user-authored {from -> to} artist name corrections as aliases.

    These are explicit merges the user has already vetted, so (unlike MBID)
    they are applied directly and **authoritatively**: the 'from' spelling
    becomes an alias of the 'to' artist, overriding any alias a prior seeding
    pass may have created. Must run BEFORE seeding so the aliases win.

    If overriding leaves the old artist unreferenced (no aliases, no dependent
    rows, no album/track entities), it is deleted; otherwise it is left in
    place (the repointed alias is what matters).
    """
    if not MAPPINGS_PATH.exists():
        logger.info("No artist_name_mappings.json found; skipping alias ingestion")
        return 0
    data = json.loads(MAPPINGS_PATH.read_text(encoding="utf-8"))
    entries = data.get("mappings", []) if isinstance(data, dict) else []
    dep_tables = ["scrobble", "album_art", "album_tracks", "artist_info",
                  "musicbrainz_releases", "spotify_track_cache", "album", "track"]
    applied = 0
    for entry in entries:
        from_name = entry.get("from")
        to_name = entry.get("to")
        if not from_name or not to_name:
            continue
        to_id = r.resolve_artist_id(to_name)

        existing = conn.execute(
            "SELECT artist_id FROM artist_alias WHERE alias_name = ?", (from_name,)
        ).fetchone()
        if existing and existing[0] != to_id:
            old_id = existing[0]
            conn.execute("DELETE FROM artist_alias WHERE alias_name = ?", (from_name,))
            other_aliases = conn.execute(
                "SELECT COUNT(*) FROM artist_alias WHERE artist_id = ?", (old_id,)
            ).fetchone()[0]
            refs = sum(
                conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE artist_id = ?", (old_id,)
                ).fetchone()[0]
                for t in dep_tables
            )
            if other_aliases == 0 and refs == 0:
                try:
                    conn.execute("DELETE FROM artist WHERE artist_id = ?", (old_id,))
                except sqlite3.IntegrityError:
                    logger.warning(
                        "Mapping %r->%r: orphan artist_id %d still FK-referenced; "
                        "left in place", from_name, to_name, old_id,
                    )
            else:
                logger.info(
                    "Mapping %r->%r: old artist_id %d still referenced "
                    "(%d rows, %d aliases); left in place",
                    from_name, to_name, old_id, refs, other_aliases,
                )

        conn.execute(
            "INSERT OR REPLACE INTO artist_alias (alias_name, norm_name, artist_id) "
            "VALUES (?, ?, ?)",
            (from_name, _normalize_for_matching(from_name), to_id),
        )
        # prime the resolver cache so subsequent resolves hit immediately
        r._artist_cache[(from_name, "")] = to_id
        applied += 1
    return applied


# --- orchestration --------------------------------------------------------

def backfill(conn: sqlite3.Connection) -> dict:
    """Run the full seed + backfill. Returns a stats dict."""
    r = Resolver(conn)
    stats = {}

    # 1. User-authored artist name corrections FIRST, so their aliases win and
    #    seeding resolves mapped 'from' spellings to the 'to' artist.
    applied = _apply_artist_mappings(conn, r)
    logger.info("Applied %d artist_name_mappings aliases", applied)

    # 2. Seed artists from every dependent table (scrobble first, with mbids).
    logger.info("Seeding artists from dependent tables")
    for (name, mbid) in conn.execute(
        "SELECT DISTINCT artist, artist_mbid FROM scrobble "
        "WHERE artist IS NOT NULL"
    ).fetchall():
        r.resolve_artist_id(name, mbid)
    for table, col in [("album_art", "artist"), ("album_tracks", "artist"),
                       ("artist_info", "artist_name"),
                       ("musicbrainz_releases", "artist_name"),
                       ("spotify_track_cache", "artist")]:
        for (name,) in conn.execute(
            f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL"
        ).fetchall():
            r.resolve_artist_id(name)

    # 3. Backfill artist_id (dependency order: artist before album/track).
    logger.info("Backfilling artist_id")
    artist_updates = {}
    artist_updates["scrobble"] = _backfill_artist_id(conn, r, "scrobble", "artist")
    artist_updates["album_art"] = _backfill_artist_id(conn, r, "album_art", "artist")
    artist_updates["album_tracks"] = _backfill_artist_id(conn, r, "album_tracks", "artist")
    artist_updates["artist_info"] = _backfill_artist_id(conn, r, "artist_info", "artist_name")
    artist_updates["musicbrainz_releases"] = _backfill_artist_id(conn, r, "musicbrainz_releases", "artist_name")
    artist_updates["spotify_track_cache"] = _backfill_artist_id(conn, r, "spotify_track_cache", "artist")
    stats["artist_id"] = artist_updates
    conn.commit()

    # 4. Backfill album_id.
    logger.info("Backfilling album_id")
    album_updates = {}
    album_updates["scrobble"] = _backfill_album_id_scrobble(conn, r)
    album_updates["album_art"] = _backfill_album_id_simple(conn, r, "album_art")
    album_updates["album_tracks"] = _backfill_album_id_simple(conn, r, "album_tracks")
    stats["album_id"] = album_updates
    conn.commit()

    # 5. Backfill track_id.
    logger.info("Backfilling track_id")
    track_updates = {}
    track_updates["scrobble"] = _backfill_track_id(conn, r, "scrobble")
    track_updates["album_tracks"] = _backfill_track_id(conn, r, "album_tracks")
    track_updates["spotify_track_cache"] = _backfill_track_id(conn, r, "spotify_track_cache")
    stats["track_id"] = track_updates
    conn.commit()

    return stats


# --- verification ---------------------------------------------------------

def verify(conn: sqlite3.Connection) -> None:
    """Print null counts, a collapse spot-check, and the MBID-collision review list."""
    logger.info("=== Verification ===")

    tables_idcols = [
        ("scrobble", ["artist_id", "album_id", "track_id"]),
        ("album_art", ["artist_id", "album_id"]),
        ("album_tracks", ["artist_id", "album_id", "track_id"]),
        ("artist_info", ["artist_id"]),
        ("musicbrainz_releases", ["artist_id"]),
        ("spotify_track_cache", ["artist_id", "track_id"]),
    ]
    for table, cols in tables_idcols:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            continue
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        parts = []
        for col in cols:
            nulls = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"
            ).fetchone()[0]
            parts.append(f"{col}={nulls} null")
        logger.info("  %-24s %d rows | %s", table, total, ", ".join(parts))

    # entity counts
    for ent in ("artist", "album", "track"):
        n = conn.execute(f"SELECT COUNT(*) FROM {ent}").fetchone()[0]
        logger.info("  entity %-7s %d rows", ent, n)

    # spot-check: case/accent variants collapse; substantive variants do not.
    def _artist_id_for(name):
        row = conn.execute(
            "SELECT artist_id FROM artist_alias WHERE alias_name=?", (name,)
        ).fetchone()
        return row[0] if row else None
    for pair in [("INXS", "Inxs"), ("José Feliciano", "Jose Feliciano"),
                 ("Auf der Maur", "Melissa Auf der Maur")]:
        a, b = _artist_id_for(pair[0]), _artist_id_for(pair[1])
        logger.info("  collapse check %-35s %s vs %s -> %s",
                    f"{pair[0]} / {pair[1]}:", a, b,
                    "MERGED" if a and a == b else "separate")

    # MBID-collision review list (candidates for Phase 4 manual merge_entities).
    collisions = conn.execute(
        "SELECT mbid, COUNT(DISTINCT name) n, GROUP_CONCAT(name, ' | ') names "
        "FROM artist WHERE mbid IS NOT NULL "
        "GROUP BY mbid HAVING n > 1 ORDER BY n DESC"
    ).fetchall()
    logger.info("=== MBID collisions (review for manual merge) === %d groups", len(collisions))
    for row in collisions[:40]:
        logger.info("  %s  [%d]  %s", row["mbid"], row["n"], row["names"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 1 entity seed + backfill")
    parser.add_argument("--verify", action="store_true",
                        help="print stats only; do not write")
    args = parser.parse_args()

    if not DB_PATH.exists():
        logger.error("Database not found at %s", DB_PATH)
        return 1

    if not args.verify:
        logger.info("Backing up database before backfill")
        backup_db.checkpoint_wal(DB_PATH)
        bp = backup_db.create_backup(DB_PATH, BACKUP_DIR)
        if bp:
            logger.info("Backup created at %s", bp)
        else:
            logger.warning("Backup failed; aborting backfill")
            return 1

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        if not args.verify:
            stats = backfill(conn)
            for phase, tablemap in stats.items():
                logger.info("%s updated: %s", phase, tablemap)
        verify(conn)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
