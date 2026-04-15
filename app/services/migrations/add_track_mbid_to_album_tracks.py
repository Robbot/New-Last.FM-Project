#!/usr/bin/env python3
"""
Migration: Add track_mbid column to album_tracks table.

This migration:
1. Adds track_mbid column to album_tracks
2. Creates index on track_mbid
3. Populates track_mbid from existing scrobble data
4. Preserves existing data

Usage:
    python -m app.services.migrations.add_track_mbid_to_album_tracks
"""

import sqlite3
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[3]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"

logger = logging.getLogger(__name__)


def migrate_add_track_mbid():
    """Add track_mbid column to album_tracks table."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    try:
        # Check if migration already run
        cur.execute("PRAGMA table_info(album_tracks)")
        columns = [col[1] for col in cur.fetchall()]

        if 'track_mbid' in columns:
            logger.info("Migration already completed: track_mbid column exists")
            return

        # Add track_mbid column
        logger.info("Adding track_mbid column to album_tracks...")
        cur.execute("ALTER TABLE album_tracks ADD COLUMN track_mbid TEXT")

        # Create index on track_mbid
        logger.info("Creating index on track_mbid...")
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_album_tracks_track_mbid
            ON album_tracks(track_mbid)
            WHERE track_mbid IS NOT NULL
            """
        )

        # Populate from existing scrobble data
        logger.info("Populating track_mbid from scrobble data...")
        cur.execute(
            """
            UPDATE album_tracks
            SET track_mbid = (
                SELECT s.track_mbid
                FROM scrobble s
                WHERE s.artist = album_tracks.artist
                  AND s.album = album_tracks.album
                  AND s.track = album_tracks.track
                  AND s.track_mbid IS NOT NULL
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1 FROM scrobble s
                WHERE s.artist = album_tracks.artist
                  AND s.album = album_tracks.album
                  AND s.track = album_tracks.track
                  AND s.track_mbid IS NOT NULL
            )
            """
        )

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM album_tracks WHERE track_mbid IS NOT NULL")
        populated = cur.fetchone()[0]

        logger.info(f"Migration completed: {populated} tracks populated with MBID")

    except Exception as e:
        conn.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_add_track_mbid()
