#!/usr/bin/env python3
"""
Migration script to normalize Pink Floyd - Ummagumma track names.

This script fixes:
1. Multi-part track naming inconsistencies (pt. vs Part)
2. Grand Vizier's Garden Party section naming
3. Typos in track names
"""

import sqlite3
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database path
DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


# Normalization map for Ummagumma tracks
UMMAGUMMA_NORMALIZATION = {
    # Sysyphus - standardize to (pt. X) format
    "Sysyphus Part I": "Sysyphus (pt. 1)",
    "Sysyphus Part II": "Sysyphus (pt. 2)",
    "Sysyphus Part III": "Sysyphus (pt. 3)",
    "Sysyphus Part IV": "Sysyphus (pt. 4)",

    # The Narrow Way - standardize to (pt. X) format
    "The Narrow Way Part 1": "The Narrow Way (pt. 1)",
    "The Narrow Way Part 2": "The Narrow Way (pt. 2)",
    "The Narrow Way Part 3": "The Narrow Way (pt. 3)",

    # The Grand Vizier's Garden Party - use descriptive section names
    "The Grand Vizier's Garden Party Part 1": "The Grand Vizier's Garden Party (Entrance)",
    "The Grand Vizier's Garden Party Part 2": "The Grand Vizier's Garden Party (Exit)",
    "The Grand Vizier's Garden Party Part 3": "The Grand Vizier's Garden Party (Entertainment)",

    # Typos and misnamed tracks
    "Careful with the Axe, Eugene": "Careful With That Axe, Eugene",
    "Set the Controls for the Heart": "Set the Controls for the Heart of the Sun",
    "Several Species of Small Furry Animals Gathered Together in a Cave and Grooving with a Pic": "Several Species of Small Furry Animals Gathered Together in a Cave and Grooving with a Pict",
}


def migrate_ummagumma_tracks():
    """Normalize Ummagumma track names in scrobble table."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return 1

    logger.info(f"Opening database: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # Show current state before migration
        cursor.execute(
            """
            SELECT DISTINCT track, COUNT(*) as count
            FROM scrobble
            WHERE artist = 'Pink Floyd' AND album = 'Ummagumma'
            GROUP BY track
            ORDER BY track
            """
        )
        before = cursor.fetchall()
        logger.info(f"\nBefore: {len(before)} distinct track names")

        # Apply normalization
        stats = {'updated': 0, 'rows': 0}
        for old_name, new_name in UMMAGUMMA_NORMALIZATION.items():
            # Check if old name exists
            cursor.execute(
                "SELECT COUNT(*) FROM scrobble WHERE artist = 'Pink Floyd' AND album = 'Ummagumma' AND track = ?",
                (old_name,)
            )
            count = cursor.fetchone()[0]

            if count > 0:
                logger.info(f"  '{old_name}' ({count} rows) → '{new_name}'")
                cursor.execute(
                    """UPDATE scrobble SET track = ?
                    WHERE artist = 'Pink Floyd' AND album = 'Ummagumma' AND track = ?""",
                    (new_name, old_name)
                )
                stats['updated'] += 1
                stats['rows'] += count

        conn.commit()

        # Show state after migration
        cursor.execute(
            """
            SELECT DISTINCT track, COUNT(*) as count
            FROM scrobble
            WHERE artist = 'Pink Floyd' AND album = 'Ummagumma'
            GROUP BY track
            ORDER BY track
            """
        )
        after = cursor.fetchall()
        logger.info(f"\nAfter: {len(after)} distinct track names")

    logger.info(f"\n=== Migration Summary ===")
    logger.info(f"Updated {stats['updated']} track variants, {stats['rows']} total rows")
    logger.info(f"Reduced from {len(before)} to {len(after)} distinct track names")

    return 0


if __name__ == "__main__":
    exit(migrate_ummagumma_tracks())
