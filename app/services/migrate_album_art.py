#!/usr/bin/env python3
"""
Migrate album_art table to use (artist, album) as PRIMARY KEY instead of album_mbid.
This allows storing album art for albums without MusicBrainz IDs.
"""

import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def migrate():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print("Starting album_art table migration...")

    # Check if old table exists
    cur.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='album_art'
    """)
    if not cur.fetchone():
        print("album_art table doesn't exist yet, creating fresh...")
        create_new_schema(conn)
        conn.close()
        return

    # Rename old table
    print("1. Renaming old album_art table to album_art_old...")
    cur.execute("ALTER TABLE album_art RENAME TO album_art_old")
    conn.commit()

    # Create new table with (artist, album) as PRIMARY KEY
    print("2. Creating new album_art table with (artist, album) as PRIMARY KEY...")
    create_new_schema(conn)

    # Copy data from old table
    print("3. Copying data from old table...")
    cur.execute("""
        INSERT OR IGNORE INTO album_art
            (artist, album, album_mbid, artist_mbid,
             image_small, image_medium, image_large, image_xlarge,
             last_updated, year_col)
        SELECT
            artist, album, album_mbid, artist_mbid,
            image_small, image_medium, image_large, image_xlarge,
            last_updated, year_col
        FROM album_art_old
        WHERE artist IS NOT NULL AND album IS NOT NULL
    """)
    rows_copied = cur.rowcount
    conn.commit()
    print(f"   Copied {rows_copied} rows")

    # Drop old table
    print("4. Dropping old table...")
    cur.execute("DROP TABLE album_art_old")
    conn.commit()

    print("Migration complete!")
    conn.close()


def create_new_schema(conn):
    """Create the new album_art table schema."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS album_art (
            artist           TEXT NOT NULL,
            album            TEXT NOT NULL,
            album_mbid       TEXT,
            artist_mbid      TEXT,
            image_small      TEXT,
            image_medium     TEXT,
            image_large      TEXT,
            image_xlarge     TEXT,
            last_updated     INTEGER,
            year_col         INTEGER,
            PRIMARY KEY (artist, album)
        )
    """)

    # Add index on album_mbid for lookups when available
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_album_art_mbid
        ON album_art(album_mbid)
        WHERE album_mbid IS NOT NULL
    """)

    conn.commit()


if __name__ == "__main__":
    try:
        migrate()
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
