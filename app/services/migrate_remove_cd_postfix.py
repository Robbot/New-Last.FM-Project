#!/usr/bin/env python3
"""
Migration script to remove CD1/CD2 postfixes from album titles.

This script cleans up multi-disc album suffixes like:
- "Album Name CD1" → "Album Name"
- "Album Name - CD2" → "Album Name"
- "Album Name Cd1" → "Album Name"
"""

import sqlite3
import re
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


def remove_cd_postfix(album_name: str) -> str:
    """Remove CD1/CD2 postfix from album name.

    Handles patterns like:
    - "Album Name CD1" → "Album Name"
    - "Album Name - CD2" → "Album Name"
    - "Album Name Cd1" → "Album Name"
    """
    if not album_name:
        return album_name

    # Pattern: various separators + CD/Cd/cd + 1/2 (case insensitive)
    # Matches: " CD1", " - CD2", " Cd1", "-cd2", " - CD1 (Album)", etc.
    patterns = [
        r'\s*-\s*[Cc][Dd]\d+\s*(?:\([^)]*\))?\s*$',  # " - CD1", "-Cd2", " - CD1 (Album)"
        r'\s+[Cc][Dd]\d+\s*(?:\([^)]*\))?\s*$',       # " CD1", " Cd2", " CD1 (Album)"
        r'\s*\(\s*[Cc][Dd]\d+\s*\)\s*$',              # "(CD1)", "(Cd2)"
        r'\s*\[\s*[Cc][Dd]\d+\s*\]\s*$',              # "[CD1]", "[Cd2]"
    ]

    result = album_name
    for pattern in patterns:
        result = re.sub(pattern, '', result)
        # Stop if we made a change
        if result != album_name:
            break

    return result.strip()


def migrate_table(conn, table_name: str, album_column: str) -> dict:
    """Migrate album names in a table.

    Returns dict with stats about changes made.
    """
    cursor = conn.cursor()

    # Find all unique albums with CD postfix
    cursor.execute(
        f"""
        SELECT DISTINCT {album_column}, COUNT(*) as count
        FROM {table_name}
        WHERE {album_column} LIKE '%CD1%'
           OR {album_column} LIKE '%CD2%'
           OR {album_column} LIKE '%Cd1%'
           OR {album_column} LIKE '%Cd2%'
           OR {album_column} LIKE '%cd1%'
           OR {album_column} LIKE '%cd2%'
        GROUP BY {album_column}
        ORDER BY count DESC
        """
    )

    affected = cursor.fetchall()
    stats = {
        'unique_albums': len(affected),
        'total_rows': 0,
        'changes_made': {}
    }

    if not affected:
        logger.info(f"No CD1/CD2 postfixes found in {table_name}.{album_column}")
        return stats

    logger.info(f"\n=== {table_name}.{album_column} ===")
    logger.info(f"Found {len(affected)} unique albums with CD postfix:")

    for old_name, count in affected:
        new_name = remove_cd_postfix(old_name)

        if old_name != new_name:
            logger.info(f"  '{old_name}' ({count} rows) → '{new_name}'")
            stats['changes_made'][old_name] = new_name
            stats['total_rows'] += count

    # Apply updates
    for old_name, new_name in stats['changes_made'].items():
        cursor.execute(
            f"UPDATE {table_name} SET {album_column} = ? WHERE {album_column} = ?",
            (new_name, old_name)
        )
        logger.info(f"  Updated {cursor.rowcount} rows: '{old_name}' → '{new_name}'")

    return stats


def main():
    """Run the migration."""
    if not DB_PATH.exists():
        logger.error(f"Database not found: {DB_PATH}")
        return 1

    logger.info(f"Opening database: {DB_PATH}")

    with sqlite3.connect(DB_PATH) as conn:
        # Migrate scrobble table
        scrobble_stats = migrate_table(conn, 'scrobble', 'album')

        # Migrate album_art table
        art_stats = migrate_table(conn, 'album_art', 'album')

        conn.commit()

    # Summary
    logger.info("\n=== Migration Summary ===")
    logger.info(f"scrobble table: {scrobble_stats['unique_albums']} unique albums, {scrobble_stats['total_rows']} total rows updated")
    logger.info(f"album_art table: {art_stats['unique_albums']} unique albums, {art_stats['total_rows']} total rows updated")
    logger.info(f"Total unique albums cleaned: {len(scrobble_stats['changes_made']) + len(art_stats['changes_made'])}")

    return 0


if __name__ == "__main__":
    exit(main())
