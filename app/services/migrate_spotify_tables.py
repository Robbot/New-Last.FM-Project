#!/usr/bin/env python3
"""
Create database tables for Spotify integration.

Run this script to add the necessary tables for Spotify API integration:
- spotify_tokens: Store OAuth tokens
- spotify_track_cache: Cache Spotify track URIs
- playlist_history: Track generated playlists

Usage:
    python -m app.services.migrate_spotify_tables
"""

import sys
import sqlite3
import logging
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.logging_config import setup_logging, get_logger
from app.db.connections import DB_PATH

setup_logging()
logger = get_logger(__name__)


def migrate():
    """Create Spotify integration tables."""
    logger.info("Starting Spotify tables migration...")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if tables already exist
    cursor.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type='table' AND name IN ('spotify_tokens', 'spotify_track_cache', 'playlist_history')
    """
    )

    existing_tables = {row[0] for row in cursor.fetchall()}

    # Create spotify_tokens table
    if "spotify_tokens" not in existing_tables:
        logger.info("Creating spotify_tokens table...")
        cursor.execute(
            """
            CREATE TABLE spotify_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL UNIQUE,
                access_token TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """
        )
        logger.info("✓ Created spotify_tokens table")
    else:
        logger.info("⊙ spotify_tokens table already exists")

    # Create spotify_track_cache table
    if "spotify_track_cache" not in existing_tables:
        logger.info("Creating spotify_track_cache table...")
        cursor.execute(
            """
            CREATE TABLE spotify_track_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT NOT NULL,
                album TEXT,
                track TEXT NOT NULL,
                spotify_uri TEXT NOT NULL,
                last_updated INTEGER DEFAULT (strftime('%s', 'now')),
                UNIQUE(artist, album, track)
            )
        """
        )
        # Create index for faster lookups
        cursor.execute(
            """
            CREATE INDEX idx_spotify_cache_lookup
            ON spotify_track_cache(artist, track)
        """
        )
        logger.info("✓ Created spotify_track_cache table")
    else:
        logger.info("⊙ spotify_track_cache table already exists")

    # Create playlist_history table
    if "playlist_history" not in existing_tables:
        logger.info("Creating playlist_history table...")
        cursor.execute(
            """
            CREATE TABLE playlist_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_type TEXT NOT NULL,
                playlist_name TEXT NOT NULL,
                spotify_playlist_id TEXT,
                track_count INTEGER,
                generated_at INTEGER DEFAULT (strftime('%s', 'now')),
                parameters TEXT
            )
        """
        )
        # Create index for history queries
        cursor.execute(
            """
            CREATE INDEX idx_playlist_history_type
            ON playlist_history(playlist_type, generated_at DESC)
        """
        )
        logger.info("✓ Created playlist_history table")
    else:
        logger.info("⊙ playlist_history table already exists")

    conn.commit()
    conn.close()

    logger.info("✓ Spotify tables migration completed successfully")


def main():
    """Main entry point."""
    try:
        migrate()
    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
