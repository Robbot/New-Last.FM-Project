#!/usr/bin/env python3
"""
Migration script to update all artist photos from Wikipedia to Last.fm.

This script will:
1. Fetch all artists from the scrobble table
2. For each artist, scrape their photo from Last.fm website
3. Update the artist_info table with the new Last.fm photo URL
4. Keep the existing Wikipedia URL and bio (only update image_url)
"""

import logging
import sqlite3
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[2]
DB_PATH = BASE_DIR / "files" / "lastfmstats.sqlite"
LASTFM_BASE = "https://www.last.fm"
LASTFM_PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"


def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_all_artists() -> list[str]:
    """Get all unique artist names from scrobbles."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT artist FROM scrobble ORDER BY artist")
    artists = [row["artist"] for row in cur.fetchall()]
    conn.close()
    return artists


def _is_lastfm_placeholder(img_url: str) -> bool:
    """Check if a Last.fm image URL is the default placeholder."""
    return LASTFM_PLACEHOLDER_HASH in img_url


def fetch_artist_image_from_lastfm(artist_name: str) -> Optional[str]:
    """
    Fetch artist image from Last.fm website by scraping.

    Args:
        artist_name: Name of the artist

    Returns:
        URL to the artist image or None
    """
    try:
        encoded_artist = urllib.parse.quote(artist_name)
        artist_url = f"{LASTFM_BASE}/music/{encoded_artist}"

        # Don't send User-Agent - Last.fm blocks Mozilla/5.0 for some artists
        response = requests.get(artist_url, timeout=15)

        if response.status_code != 200:
            logger.debug(f"Last.fm returned {response.status_code} for {artist_name}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Method 1: Try Open Graph image
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_url = og_image["content"]
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 2: Try Twitter image
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            img_url = twitter_image["content"]
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 3: Look for header background image
        header_img = soup.find("img", class_="header-new-background-image")
        if header_img and header_img.get("src"):
            img_url = header_img["src"]
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 4: Find any large Last.fm image
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "lastfm.freetls.fastly.net" in src:
                if any(size in src for size in ["770x0", "500x500", "300x300", "ar0"]):
                    if not _is_lastfm_placeholder(src):
                        return src

        return None

    except Exception as e:
        logger.error(f"Error fetching image for {artist_name}: {e}")
        return None


def update_artist_image(artist_name: str, image_url: Optional[str]) -> bool:
    """
    Update the artist's image URL in the database.

    Keeps the existing bio and wikipedia_url, only updates image_url.

    Args:
        artist_name: Name of the artist
        image_url: New image URL from Last.fm

    Returns:
        True if successful, False otherwise
    """
    conn = get_db_connection()
    try:
        # Check if artist_info record exists
        cur = conn.cursor()
        cur.execute(
            "SELECT bio, wikipedia_url FROM artist_info WHERE artist_name = ?",
            (artist_name,)
        )
        existing = cur.fetchone()

        if existing:
            # Update existing record, preserving bio and wikipedia_url
            cur.execute(
                """
                UPDATE artist_info
                SET image_url = ?, last_updated = CURRENT_TIMESTAMP
                WHERE artist_name = ?
                """,
                (image_url, artist_name)
            )
        else:
            # Insert new record
            cur.execute(
                """
                INSERT INTO artist_info (artist_name, image_url, bio, wikipedia_url, last_updated)
                VALUES (?, ?, NULL, NULL, CURRENT_TIMESTAMP)
                """,
                (artist_name, image_url)
            )

        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error updating artist image for {artist_name}: {e}")
        return False
    finally:
        conn.close()


def main():
    """Main migration function."""
    print("=" * 60)
    print("Artist Photo Migration: Wikipedia → Last.fm")
    print("=" * 60)
    print("Using web scraping (no API key required)...")

    artists = get_all_artists()
    total = len(artists)
    print(f"Found {total} unique artists in database")

    if total == 0:
        print("No artists found. Nothing to migrate.")
        return

    # Ask for confirmation
    print(f"\nThis will update artist photos for {total} artists.")
    response = input("Continue? (y/N): ")

    if response.lower() != 'y':
        print("Migration cancelled.")
        return

    processed = 0
    updated = 0
    not_found = 0
    errors = 0

    for artist in artists:
        processed += 1
        print(f"\n[{processed}/{total}] {artist}")

        image_url = fetch_artist_image_from_lastfm(artist)

        if image_url:
            if update_artist_image(artist, image_url):
                updated += 1
                print(f"  ✓ Updated: {image_url[:60]}...")
            else:
                errors += 1
                print(f"  ✗ Error updating database")
        else:
            not_found += 1
            print(f"  ○ No image found on Last.fm")

        # Rate limiting - be nice to Last.fm (avoid blocking)
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    print(f"Processed: {processed} artists")
    print(f"Updated:   {updated} artist photos")
    print(f"Not found: {not_found} artists (no image on Last.fm)")
    print(f"Errors:    {errors}")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nMigration interrupted by user")
    except Exception as exc:
        logger.exception("Fatal error during migration")
        print(f"\nERROR: {exc}")
