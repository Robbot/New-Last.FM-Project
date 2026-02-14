#!/usr/bin/env python3
"""
Update all albums in the database that have wikipedia_url = 'N/A' with their correct Wikipedia URLs.

This script:
1. Gets all albums from album_art where wikipedia_url = 'N/A'
2. For each album, tries to fetch the Wikipedia URL using the improved fetch_wikipedia logic
3. Updates the database with the found URLs
4. Prints a summary of changes made
"""
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

# Add parent directory to path to import from app
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.fetch_wikipedia import fetch_album_wikipedia_url
from db import get_db_connection


DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


def get_albums_with_na_wikipedia() -> List[Tuple[str, str, int | None]]:
    """Get all albums where wikipedia_url = 'N/A'."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            """
            SELECT artist, album, year_col
            FROM album_art
            WHERE wikipedia_url = 'N/A'
            ORDER BY year_col DESC
            """
        ).fetchall()
        return [(row["artist"], row["album"], row["year_col"]) for row in rows]
    finally:
        conn.close()


def update_album_wikipedia_url(artist: str, album: str, wikipedia_url: str) -> bool:
    """Update the Wikipedia URL for an album in the database."""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE album_art
            SET wikipedia_url = ?
            WHERE artist = ? AND album = ?
            """,
            (wikipedia_url, artist, album),
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"  Error updating: {e}")
        return False
    finally:
        conn.close()


def main():
    """Main function to update all albums with N/A Wikipedia URLs."""
    print("Updating Wikipedia URLs for albums with 'N/A'...\n")
    print("=" * 80)

    albums = get_albums_with_na_wikipedia()
    print(f"\nFound {len(albums)} albums with wikipedia_url = 'N/A'\n")

    if not albums:
        print("No albums to update!")
        return

    updated_count = 0
    not_found_count = 0
    error_count = 0

    for i, (artist, album, year) in enumerate(albums, 1):
        year_str = f" ({year})" if year else ""
        print(f"[{i}/{len(albums)}] Checking: {artist} - {album}{year_str}")

        try:
            url = fetch_album_wikipedia_url(artist, album)

            if url and url != "N/A":
                # Update the database
                if update_album_wikipedia_url(artist, album, url):
                    print(f"  ✓ Updated: {url}")
                    updated_count += 1
                else:
                    print(f"  ✗ Error updating database")
                    error_count += 1
            elif url == "N/A":
                print(f"  ✗ No Wikipedia page found")
                not_found_count += 1
            else:
                print(f"  ✗ Error fetching Wikipedia URL")
                error_count += 1

        except Exception as e:
            print(f"  ✗ Error: {e}")
            error_count += 1

        # Add a small delay to avoid overwhelming the Wikipedia API
        import time
        time.sleep(0.5)

    # Print summary
    print("\n" + "=" * 80)
    print("\nSUMMARY")
    print("=" * 80)
    print(f"Total albums checked: {len(albums)}")
    print(f"Wikipedia URLs updated: {updated_count}")
    print(f"No Wikipedia page found: {not_found_count}")
    print(f"Errors: {error_count}")
    if updated_count > 0:
        print(f"\nSuccess rate: {100 * updated_count / len(albums):.1f}%")


if __name__ == "__main__":
    main()
