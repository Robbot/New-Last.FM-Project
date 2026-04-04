#!/usr/bin/env python3
"""
Migration script to rename Ummagumma tracks to match MusicBrainz naming convention.

MusicBrainz Release: https://musicbrainz.org/release/26afa7c0-c203-4edd-8947-bd54613d2603

Changes:
- Sysyphus (pt. 1/2/3/4) → Sysyphus, Part One/Two/Three/Four
- The Narrow Way (pt. 1/2/3) → The Narrow Way, Part One/Two/Three
- The Grand Vizier's Garden Party (Entrance/Exit/Entertainment) →
  The Grand Vizier's Garden Party, Part One – Entrance / Part Two – Entertainment / Part Three – Exit
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


# Mapping from current track names to MusicBrainz format
# Note: MusicBrainz uses EN DASH (–) not hyphen (-) and smart quotes (')
# The smart quotes here must match exactly (U+2019 RIGHT SINGLE QUOTATION MARK)
MUSICBRAINZ_NORMALIZATION = {
    # Sysyphus
    "Sysyphus (pt. 1)": "Sysyphus, Part One",
    "Sysyphus (pt. 2)": "Sysyphus, Part Two",
    "Sysyphus (pt. 3)": "Sysyphus, Part Three",
    "Sysyphus (pt. 4)": "Sysyphus, Part Four",

    # The Narrow Way
    "The Narrow Way (pt. 1)": "The Narrow Way, Part One",
    "The Narrow Way (pt. 2)": "The Narrow Way, Part Two",
    "The Narrow Way (pt. 3)": "The Narrow Way, Part Three",

    # The Grand Vizier's Garden Party (from parenthesis format to MB format with en dash and smart quotes)
    "The Grand Vizier's Garden Party (Entrance)": "The Grand Vizier's Garden Party, Part One – Entrance",
    "The Grand Vizier's Garden Party (Entertainment)": "The Grand Vizier's Garden Party, Part Two – Entertainment",
    "The Grand Vizier's Garden Party (Exit)": "The Grand Vizier's Garden Party, Part Three – Exit",

    # Several Species (capitalization fix)
    "Several Species of Small Furry Animals Gathered Together in a Cave and Grooving with a Pict": "Several Species of Small Furry Animals Gathered Together in a Cave and Grooving With a Pict",
}


def migrate_to_musicbrainz_naming():
    """Rename Ummagumma tracks to match MusicBrainz convention."""
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
        for old_name, new_name in MUSICBRAINZ_NORMALIZATION.items():
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

    return 0


if __name__ == "__main__":
    exit(migrate_to_musicbrainz_naming())
