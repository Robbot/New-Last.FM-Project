#!/usr/bin/env python3
"""
Migration: introduce canonical entity tables (artist / album / track) plus
alias tables, and add nullable *_id FK columns to the dependent tables.

This is the Phase 0 foundation of the relational rework. It is **additive
and zero behavior change**: every new column is nullable, no existing column
or constraint is touched, and no read/write path is altered. Entity tables are
created empty; they are populated in Phase 1.

Idempotent: safe to run repeatedly and safe to call from `ensure_schema` on
every sync. The one-time `migrate()` entry point also takes a backup first.

Shared schema: `ensure_entity_schema(conn)` is the single source of truth for
the new tables/columns and is reused by `sync_lastfm.ensure_schema` (fresh
installs) and `tests/conftest.py` (test DB) to avoid drift.
"""

import sqlite3
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.logging_config import get_logger
from app.services import backup_db

logger = get_logger(__name__)

DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"
BACKUP_DIR = Path(__file__).parent.parent.parent / "files" / "backups"


# --- Canonical entity + alias tables (single source of truth) -------------

ENTITY_TABLES_DDL = [
    """
    CREATE TABLE IF NOT EXISTS artist (
        artist_id  INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        mbid       TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS album (
        album_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT NOT NULL,
        mbid       TEXT,
        artist_id  INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (artist_id) REFERENCES artist(artist_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track (
        track_id   INTEGER PRIMARY KEY AUTOINCREMENT,
        title      TEXT NOT NULL,
        mbid       TEXT,
        artist_id  INTEGER NOT NULL,
        album_id   INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (artist_id) REFERENCES artist(artist_id),
        FOREIGN KEY (album_id)  REFERENCES album(album_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artist_alias (
        alias_name TEXT PRIMARY KEY,
        norm_name  TEXT NOT NULL,
        artist_id  INTEGER NOT NULL,
        FOREIGN KEY (artist_id) REFERENCES artist(artist_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS album_alias (
        artist_id  INTEGER NOT NULL,
        norm_title TEXT NOT NULL,
        album_id   INTEGER NOT NULL,
        PRIMARY KEY (artist_id, norm_title),
        FOREIGN KEY (album_id) REFERENCES album(album_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track_alias (
        artist_id  INTEGER NOT NULL,
        norm_title TEXT NOT NULL,
        track_id   INTEGER NOT NULL,
        PRIMARY KEY (artist_id, norm_title),
        FOREIGN KEY (track_id) REFERENCES track(track_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS track_mismatch_resolution (
        artist          TEXT NOT NULL,
        album           TEXT NOT NULL,
        source_track    TEXT NOT NULL,
        action          TEXT NOT NULL CHECK (action IN ('map', 'add', 'keep')),
        canonical_track TEXT,
        created_at      TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (artist, album, source_track),
        CHECK (
            (action = 'map' AND canonical_track IS NOT NULL)
            OR action IN ('add', 'keep')
        )
    )
    """,
]

ENTITY_INDEXES_DDL = [
    "CREATE INDEX IF NOT EXISTS idx_artist_alias_norm ON artist_alias(norm_name)",
    "CREATE INDEX IF NOT EXISTS idx_album_alias_album_id ON album_alias(album_id)",
    "CREATE INDEX IF NOT EXISTS idx_track_alias_track_id ON track_alias(track_id)",
    "CREATE INDEX IF NOT EXISTS idx_album_artist_id ON album(artist_id)",
    "CREATE INDEX IF NOT EXISTS idx_track_artist_id ON track(artist_id)",
    "CREATE INDEX IF NOT EXISTS idx_track_album_id ON track(album_id)",
    "CREATE INDEX IF NOT EXISTS idx_artist_mbid ON artist(mbid) WHERE mbid IS NOT NULL",
]

# Nullable FK columns added to existing dependent tables.
# {table: [(column_name, column_def), ...]}
# These stay NULL until Phase 1 backfills them; NULL never violates an FK.
FK_COLUMN_ADDITIONS = {
    "scrobble": [
        ("artist_id", "INTEGER"),
        ("album_id", "INTEGER"),
        ("track_id", "INTEGER"),
    ],
    "album_art": [
        ("artist_id", "INTEGER"),
        ("album_id", "INTEGER"),
    ],
    "album_tracks": [
        ("artist_id", "INTEGER"),
        ("album_id", "INTEGER"),
        ("track_id", "INTEGER"),
    ],
    "artist_info": [
        ("artist_id", "INTEGER"),
    ],
    "musicbrainz_releases": [
        ("artist_id", "INTEGER"),
    ],
    "spotify_track_cache": [
        ("artist_id", "INTEGER"),
        ("track_id", "INTEGER"),
    ],
}

# Indexes on the new FK columns so Phase 3 id-based JOINs are fast.
# Each entry is (target_table, ddl) so creation can be skipped when the
# target table does not exist (e.g. the minimal test schema).
FK_INDEXES_DDL = [
    ("scrobble", "CREATE INDEX IF NOT EXISTS idx_scrobble_artist_id ON scrobble(artist_id)"),
    ("scrobble", "CREATE INDEX IF NOT EXISTS idx_scrobble_album_id ON scrobble(album_id)"),
    ("scrobble", "CREATE INDEX IF NOT EXISTS idx_scrobble_track_id ON scrobble(track_id)"),
    ("album_art", "CREATE INDEX IF NOT EXISTS idx_album_art_artist_id ON album_art(artist_id)"),
    ("album_art", "CREATE INDEX IF NOT EXISTS idx_album_art_album_id ON album_art(album_id)"),
    ("album_tracks", "CREATE INDEX IF NOT EXISTS idx_album_tracks_artist_id ON album_tracks(artist_id)"),
    ("album_tracks", "CREATE INDEX IF NOT EXISTS idx_album_tracks_album_id ON album_tracks(album_id)"),
    ("album_tracks", "CREATE INDEX IF NOT EXISTS idx_album_tracks_track_id ON album_tracks(track_id)"),
    ("artist_info", "CREATE INDEX IF NOT EXISTS idx_artist_info_artist_id ON artist_info(artist_id)"),
    ("musicbrainz_releases", "CREATE INDEX IF NOT EXISTS idx_mb_releases_artist_id ON musicbrainz_releases(artist_id)"),
    ("spotify_track_cache", "CREATE INDEX IF NOT EXISTS idx_spotify_cache_artist_id ON spotify_track_cache(artist_id)"),
    ("spotify_track_cache", "CREATE INDEX IF NOT EXISTS idx_spotify_cache_track_id ON spotify_track_cache(track_id)"),
]


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names currently on `table`."""
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cur.fetchone() is not None


def create_entity_tables(conn: sqlite3.Connection) -> None:
    """Create the canonical entity + alias tables and their indexes."""
    cur = conn.cursor()
    for ddl in ENTITY_TABLES_DDL:
        cur.execute(ddl)
    for ddl in ENTITY_INDEXES_DDL:
        cur.execute(ddl)
    conn.commit()


def add_fk_columns(conn: sqlite3.Connection) -> None:
    """Add nullable *_id FK columns to dependent tables (guarded, idempotent)."""
    cur = conn.cursor()
    for table, columns in FK_COLUMN_ADDITIONS.items():
        if not _table_exists(conn, table):
            logger.warning("Table %s missing — skipping its FK columns", table)
            continue
        existing = _existing_columns(conn, table)
        for col_name, col_def in columns:
            if col_name in existing:
                continue
            logger.info("Adding column %s.%s", table, col_name)
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
    conn.commit()


def add_fk_indexes(conn: sqlite3.Connection) -> None:
    """Create indexes on the new FK columns (idempotent).

    Skips any index whose target table does not exist (e.g. the minimal
    test schema that only creates a subset of dependent tables).
    """
    cur = conn.cursor()
    for table, ddl in FK_INDEXES_DDL:
        if not _table_exists(conn, table):
            continue
        cur.execute(ddl)
    conn.commit()


def ensure_entity_schema(conn: sqlite3.Connection) -> None:
    """
    Single source of truth: create entity tables + add FK columns + indexes.
    Idempotent and cheap — safe to call on every sync.
    """
    create_entity_tables(conn)
    add_fk_columns(conn)
    add_fk_indexes(conn)


def verify_schema(conn: sqlite3.Connection) -> bool:
    """Sanity-check that entity tables exist and scrobble got its id columns."""
    ok = True
    for table in ("artist", "album", "track",
                  "artist_alias", "album_alias", "track_alias",
                  "track_mismatch_resolution"):
        if not _table_exists(conn, table):
            logger.error("Verification failed: table %s missing", table)
            ok = False
    if _table_exists(conn, "scrobble"):
        cols = _existing_columns(conn, "scrobble")
        for required in ("artist_id", "album_id", "track_id"):
            if required not in cols:
                logger.error("Verification failed: scrobble.%s missing", required)
                ok = False
    return ok


def migrate() -> bool:
    """
    One-time entry point: backup first, then ensure entity schema, then verify.
    Returns True on success.
    """
    if not DB_PATH.exists():
        logger.error("Database not found at %s", DB_PATH)
        return False

    logger.info("Phase 0 entity migration: backing up database first")
    backup_db.checkpoint_wal(DB_PATH)
    backup_path = backup_db.create_backup(DB_PATH, BACKUP_DIR)
    if backup_path:
        logger.info("Backup created at %s", backup_path)
    else:
        logger.warning("Backup failed; proceeding anyway (schema is additive)")

    try:
        with sqlite3.connect(DB_PATH) as conn:
            ensure_entity_schema(conn)
            if not verify_schema(conn):
                logger.error("Schema verification failed")
                return False
        logger.info("Phase 0 entity migration complete")
        return True
    except sqlite3.Error as e:
        logger.error("Database error during entity migration: %s", e, exc_info=True)
        return False


if __name__ == "__main__":
    print("Phase 0: canonical entity tables + FK columns")
    print(f"Database: {DB_PATH}")
    logger.info("Starting Phase 0 entity migration")
    success = migrate()
    if success:
        print("Migration completed successfully!")
        sys.exit(0)
    else:
        print("Migration failed!")
        sys.exit(1)
