"""
Migration script to create the artist_info table.

This table stores artist metadata including photos, bios, and Wikipedia links
fetched from Wikipedia API.
"""
import logging
from pathlib import Path

from app.db.connections import get_db_connection

logger = logging.getLogger(__name__)


def migrate_artist_info():
    """
    Create the artist_info table if it doesn't exist.

    The table stores:
    - artist_name: Primary key (artist name from scrobbles)
    - image_url: URL to the artist's photo
    - bio: Short biography text
    - wikipedia_url: Link to Wikipedia article
    - last_updated: Timestamp of last data refresh
    """
    conn = get_db_connection()
    try:
        # Check if table already exists
        table_check = conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='artist_info'
            """
        ).fetchone()

        if table_check:
            logger.info("artist_info table already exists")
            return True

        # Create the table
        conn.execute(
            """
            CREATE TABLE artist_info (
                artist_name TEXT PRIMARY KEY,
                image_url TEXT,
                bio TEXT,
                wikipedia_url TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Create index for faster lookups
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_artist_info_wikipedia
            ON artist_info(wikipedia_url)
            """
        )

        conn.commit()
        logger.info("Successfully created artist_info table")
        return True

    except Exception as e:
        logger.error(f"Failed to create artist_info table: {e}", exc_info=True)
        conn.rollback()
        return False
    finally:
        conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    migrate_artist_info()
