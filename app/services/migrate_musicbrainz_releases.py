#!/usr/bin/env python3
"""
Migration script to create the musicbrainz_releases table.

This table caches album/release data from MusicBrainz for artists,
including albums that may not have been played yet.

Usage:
    python -m app.services.migrate_musicbrainz_releases
"""
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"


def migrate():
    """Create the musicbrainz_releases table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()

        # Check if table already exists
        cursor.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='musicbrainz_releases'
            """
        )
        if cursor.fetchone():
            print("Table 'musicbrainz_releases' already exists.")
            return

        # Create the table
        cursor.execute(
            """
            CREATE TABLE musicbrainz_releases (
                artist_mbid TEXT NOT NULL,
                artist_name TEXT NOT NULL,
                album_title TEXT NOT NULL,
                release_year INTEGER,
                album_mbid TEXT,
                release_type TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (artist_mbid, album_title),
                UNIQUE(artist_mbid, album_mbid)
            )
            """
        )

        # Create indexes for common queries
        cursor.execute(
            """
            CREATE INDEX idx_mb_releases_artist_name
            ON musicbrainz_releases(artist_name)
            """
        )

        cursor.execute(
            """
            CREATE INDEX idx_mb_releases_year
            ON musicbrainz_releases(release_year)
            """
        )

        conn.commit()
        print("Successfully created 'musicbrainz_releases' table and indexes.")

    except sqlite3.Error as e:
        print(f"Database error: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
