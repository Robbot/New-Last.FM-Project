#!/usr/bin/env python3
"""
Find albums that have wikipedia_url = "N/A" but should have valid Wikipedia articles.

This script uses a more lenient approach to find Wikipedia articles:
1. Gets all albums from album_art where wikipedia_url = 'N/A'
2. For each album, manually checks Wikipedia using multiple search strategies
3. Prints a report of albums that should have Wikipedia links but don't
"""
import sqlite3
import requests
import sys
from pathlib import Path
from typing import Optional, List, Tuple
import urllib.parse
import re


# Add parent directory to path to import from app
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.fetch_wikipedia import _normalize_for_comparison


DB_PATH = Path(__file__).parent.parent.parent / "files" / "lastfmstats.sqlite"


def get_db_connection():
    """Get a database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_albums_with_na_wikipedia() -> List[Tuple[str, str, Optional[int]]]:
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


def search_wikipedia_lenient(query: str, lang: str = "en", limit: int = 5) -> List[dict]:
    """
    Search Wikipedia with lenient matching and return top results.

    Args:
        query: Search query string
        lang: Wikipedia language code (default: "en")
        limit: Number of results to return

    Returns:
        List of search results with title, snippet, and url
    """
    try:
        search_api_url = f"https://{lang}.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
        }

        response = requests.get(
            search_api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": "LastFMStats/1.0 (https://github.com/user; lastfmstats@example.com)"},
        )

        if response.status_code != 200:
            return []

        data = response.json()

        if "query" not in data or "search" not in data["query"]:
            return []

        search_results = data["query"]["search"]

        results = []
        for result in search_results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            wordcount = result.get("wordcount", 0)
            results.append({
                "title": title,
                "snippet": snippet,
                "wordcount": wordcount,
                "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
            })

        return results

    except (requests.RequestException, KeyError, ValueError):
        return []


def check_album_wikipedia_manually(artist: str, album: str) -> Optional[dict]:
    """
    Manually check if an album has a Wikipedia article using lenient search.

    Tries multiple search strategies:
    1. Just the album name with "(album)"
    2. Album name with "(album)" and artist
    3. Just the album name (in quotes)
    4. Album name with artist

    Returns:
        Dictionary with found Wikipedia URL and search method, or None
    """
    # Clean edition suffixes
    edition_suffixes = [
        " (Standard Edition)",
        " (Deluxe Edition)",
        " (Expanded Edition)",
        " (Collector's Edition)",
        " (Limited Edition)",
        " (Special Edition)",
        " (Premium Edition)",
        " (Bonus Track Edition)",
        " (Bonus Track Version)",
        " (Remastered)",
        " (Remaster)",
        " - Remastered",
        " - Remaster",
        " (Deluxe Version)",
        " (Explicit Version)",
        " (Clean Version)",
        " (Original Album)",
        " - Original Album",
    ]

    cleaned_album = album
    for suffix in edition_suffixes:
        if cleaned_album.endswith(suffix):
            cleaned_album = cleaned_album[:-len(suffix)]
            break

    normalized_artist = _normalize_for_comparison(artist)
    normalized_album = _normalize_for_comparison(cleaned_album)

    # Search strategies
    search_queries = [
        # Strategy 1: Album name with (album) suffix
        f'"{cleaned_album}" (album)',
        # Strategy 2: Album name with (album) and artist
        f'"{cleaned_album}" (album) {artist}',
        # Strategy 3: Just album name
        f'"{cleaned_album}"',
        # Strategy 4: Album name and artist
        f'"{cleaned_album}" {artist}',
        # Strategy 5: Album (album) without quotes
        f"{cleaned_album} (album)",
    ]

    for query in search_queries:
        results = search_wikipedia_lenient(query, lang="en", limit=5)

        for result in results:
            title = result["title"]
            normalized_title = _normalize_for_comparison(title)
            snippet = result.get("snippet", "")

            # Check if this is clearly the right album
            # Must have "(album)" in title OR exact match with artist
            is_album_page = "(album)" in title.lower()
            has_artist = normalized_artist in normalized_title
            has_album = normalized_album in normalized_title

            # Check if snippet mentions "album" (common in Wikipedia intros)
            snippet_says_album = "album" in snippet.lower()

            # Major penalty for songs
            if "(song)" in title:
                continue

            # More lenient matching criteria:
            # 1. It's explicitly marked as an album page AND has the album name
            # 2. It has the exact album name AND the snippet mentions "album"
            # 3. It has both album AND artist names (strong signal)
            # 4. It's an album page with artist name (for self-titled albums)
            if (is_album_page and has_album) or \
               (has_album and snippet_says_album and normalized_title == normalized_album) or \
               (has_album and has_artist) or \
               (is_album_page and has_artist):
                return {
                    "url": result["url"],
                    "title": title,
                    "query": query,
                    "snippet": snippet,
                }

    return None


def main():
    """Main function to check all albums with N/A Wikipedia URLs."""
    print("Finding albums that should have Wikipedia links but don't...\n")
    print("=" * 80)

    albums = get_albums_with_na_wikipedia()
    print(f"\nFound {len(albums)} albums with wikipedia_url = 'N/A'\n")

    # Filter for popular albums (those with reasonable years and non-empty artist names)
    # Skip Various Artists compilations as they're harder to match
    albums_to_check = [
        (artist, album, year) for artist, album, year in albums
        if artist != "Various Artists" and year and year > 1900
    ]

    print(f"Checking {len(albums_to_check)} non-compilation albums...\n")
    print("=" * 80)

    found_count = 0
    not_found_count = 0

    results = []

    for i, (artist, album, year) in enumerate(albums_to_check, 1):
        print(f"\n[{i}/{len(albums_to_check)}] Checking: {artist} - {album} ({year})")

        result = check_album_wikipedia_manually(artist, album)

        if result:
            found_count += 1
            print(f"  ✓ FOUND: {result['title']}")
            print(f"    URL: {result['url']}")
            print(f"    Query: {result['query']}")
            results.append({
                "artist": artist,
                "album": album,
                "year": year,
                "found": True,
                "wikipedia_title": result["title"],
                "wikipedia_url": result["url"],
                "query": result["query"],
            })
        else:
            not_found_count += 1
            print(f"  ✗ NOT FOUND")
            results.append({
                "artist": artist,
                "album": album,
                "year": year,
                "found": False,
            })

    # Print summary
    print("\n" + "=" * 80)
    print("\nSUMMARY")
    print("=" * 80)
    print(f"Total albums checked: {len(albums_to_check)}")
    print(f"Wikipedia pages found: {found_count}")
    print(f"Wikipedia pages not found: {not_found_count}")
    print(f"Success rate: {100 * found_count / len(albums_to_check):.1f}%")

    # Print detailed report of found albums
    print("\n" + "=" * 80)
    print("ALBUMS THAT SHOULD HAVE WIKIPEDIA LINKS")
    print("=" * 80)

    found_results = [r for r in results if r["found"]]
    if found_results:
        print(f"\nFound {len(found_results)} albums with Wikipedia pages:\n")
        for r in found_results:
            print(f"  • {r['artist']} - {r['album']} ({r['year']})")
            print(f"    Wikipedia: {r['wikipedia_title']}")
            print(f"    URL: {r['wikipedia_url']}")
            print()
    else:
        print("\nNo albums with missing Wikipedia links found.")

    # Print SQL update statements for convenience
    if found_results:
        print("\n" + "=" * 80)
        print("SQL UPDATE STATEMENTS")
        print("=" * 80)
        print("\nTo update the database, you can use these SQL statements:\n")
        for r in found_results:
            artist_escaped = r['artist'].replace("'", "''")
            album_escaped = r['album'].replace("'", "''")
            url_escaped = r['wikipedia_url'].replace("'", "''")
            print(f"UPDATE album_art SET wikipedia_url = '{url_escaped}' WHERE artist = '{artist_escaped}' AND album = '{album_escaped}';")


if __name__ == "__main__":
    main()
