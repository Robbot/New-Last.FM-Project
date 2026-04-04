#!/usr/bin/env python3
"""
Migration script to add 'source' column to scrobble table.

This migration:
1. Adds a 'source' column to the scrobble table (TEXT, default 'lastfm')
2. Marks all existing entries with source='lastfm'
3. Creates an index on the source column for efficient querying

This prepares the database for importing additional scrobbles from other sources
(e.g., Excel files with historical data) while maintaining the ability to
distinguish between different data sources.
"""

import logging
import sqlite3
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.logging_config import get_logger

logger = get_logger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


def migrate_add_source_column():
    """
    Add source column to scrobble table and mark existing entries.

    Returns:
        bool: True if migration successful, False otherwise
    """
    if not DB_PATH.exists():
        logger.error(f"Database not found at {DB_PATH}")
        return False

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            cur = conn.cursor()

            # Check if source column already exists
            cur.execute("PRAGMA table_info(scrobble)")
            columns = [row[1] for row in cur.fetchall()]

            if "source" in columns:
                logger.info("Source column already exists in scrobble table. Skipping migration.")
                # Still verify that all entries have a source value
                cur.execute("SELECT COUNT(*) FROM scrobble WHERE source IS NULL")
                null_count = cur.fetchone()[0]
                if null_count > 0:
                    logger.info(f"Found {null_count} scrobbles with NULL source, updating to 'lastfm'")
                    cur.execute("UPDATE scrobble SET source = 'lastfm' WHERE source IS NULL")
                    conn.commit()
                    logger.info(f"Updated {cur.rowcount} scrobbles with source='lastfm'")
                return True

            # Add the source column with default value 'lastfm'
            logger.info("Adding 'source' column to scrobble table...")
            cur.execute("ALTER TABLE scrobble ADD COLUMN source TEXT DEFAULT 'lastfm'")

            # Explicitly set all existing rows to 'lastfm' (in case DEFAULT didn't apply)
            logger.info("Setting source='lastfm' for all existing scrobbles...")
            cur.execute("UPDATE scrobble SET source = 'lastfm' WHERE source IS NULL")
            updated = cur.rowcount
            logger.info(f"Updated {updated} existing scrobbles with source='lastfm'")

            # Create index on source column for efficient filtering
            logger.info("Creating index on source column...")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_scrobble_source ON scrobble(source)")

            # Verify the migration
            cur.execute("SELECT COUNT(*), source FROM scrobble GROUP BY source")
            results = cur.fetchall()
            logger.info("Source column distribution:")
            for count, source in results:
                logger.info(f"  {source or 'NULL'}: {count} scrobbles")

            conn.commit()
            logger.info("Migration completed successfully!")
            return True

    except sqlite3.Error as e:
        logger.error(f"Database error during migration: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Unexpected error during migration: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    print("Starting migration: Add source column to scrobble table")
    print(f"Database: {DB_PATH}")
    logger.info("Starting migration: Add source column to scrobble table")
    logger.info(f"Database: {DB_PATH}")

    success = migrate_add_source_column()

    if success:
        print("Migration completed successfully!")
        logger.info("Migration completed successfully!")
        sys.exit(0)
    else:
        print("Migration failed!")
        logger.error("Migration failed!")
        sys.exit(1)
