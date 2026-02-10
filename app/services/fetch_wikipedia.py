"""
Wikipedia API service for fetching album Wikipedia URLs.
"""
import requests
from typing import Optional
import urllib.parse
import re


def fetch_album_wikipedia_url(artist_name: str, album_name: str) -> Optional[str]:
    """
    Fetch the Wikipedia URL for an album using the Wikipedia API.

    Args:
        artist_name: Name of the artist
        album_name: Name of the album

    Returns:
        The Wikipedia URL if found, None otherwise
    """
    # Common edition/remaster suffixes to strip for Wikipedia search
    # Wikipedia articles typically don't include these in their titles
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

    # Strip edition suffixes for better Wikipedia matching
    cleaned_album = album_name
    for suffix in edition_suffixes:
        if cleaned_album.endswith(suffix):
            cleaned_album = cleaned_album[:-len(suffix)]
            break

    # Try searching for the album directly with artist
    search_query = f'"{cleaned_album}" (album) {artist_name}'
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album)

    if search_url:
        return search_url

    # Try with quotes around album name
    search_query = f'"{cleaned_album}" {artist_name}'
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album)

    if search_url:
        return search_url

    # Try without quotes
    search_query = f"{cleaned_album} (album) {artist_name}"
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album)

    if search_url:
        return search_url

    # Try just the album name with (album) suffix
    search_query = f'"{cleaned_album}" (album)'
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album)

    # Also try the original album name if all else fails
    if not search_url and cleaned_album != album_name:
        search_query = f'"{album_name}" (album) {artist_name}'
        search_url = _search_wikipedia(search_query, artist_name, album_name, album_name)

    return search_url


def _search_wikipedia(query: str, artist_name: str, album_name: str, cleaned_album: str | None = None) -> Optional[str]:
    """
    Search Wikipedia for a query and return the URL if a direct match is found.

    Args:
        query: The search query string
        artist_name: The original artist name for validation
        album_name: The original album name for validation (may include edition suffixes)
        cleaned_album: The album name with edition suffixes stripped for better matching

    Returns:
        The Wikipedia URL if found, None otherwise
    """
    try:
        # Use Wikipedia API to search
        search_api_url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": 10,
            "srprop": "titles",
        }

        response = requests.get(
            search_api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": "LastFMStats/1.0"},
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if "query" not in data or "search" not in data["query"]:
            return None

        search_results = data["query"]["search"]

        if not search_results:
            return None

        # Find the best match by scoring results
        best_match = None
        best_score = -1

        normalized_artist = _normalize_for_comparison(artist_name)
        normalized_album = _normalize_for_comparison(cleaned_album if cleaned_album else album_name)

        for result in search_results:
            title = result.get("title", "")
            if not title:
                continue

            score = _score_match(title, normalized_artist, normalized_album)

            if score > best_score:
                best_score = score
                best_match = title

        # Only return if we have a decent match (score >= 50, lowered from 60)
        # to catch cases where edition suffixes were stripped
        if best_score >= 50 and best_match:
            return f"https://en.wikipedia.org/wiki/{urllib.parse.quote(best_match.replace(' ', '_'))}"

        return None

    except (requests.RequestException, KeyError, ValueError):
        return None


def _score_match(title: str, normalized_artist: str, normalized_album: str) -> int:
    """
    Score a Wikipedia title match against the expected artist and album.
    Returns a score from 0-100.

    Scoring rules:
    - +50 points if the normalized album name appears in the title
    - +40 points if the title ends with "(album)"
    - -100 points if the title is a song page (contains "(song)")
    - +30 points if the normalized artist name appears in the title
    - +10 points for close word matches
    """
    score = 0
    normalized_title = _normalize_for_comparison(title)

    # MAJOR PENALTY: Songs should never match when looking for albums
    if "(song)" in title:
        return -1000

    # Check if album name is present in title (highest priority)
    if normalized_album in normalized_title:
        score += 50
        # Bonus for exact album match at start
        if normalized_title.startswith(normalized_album):
            score += 10

    # MAJOR BONUS: "(album)" suffix is critical - indicates this is definitely an album page
    if title.endswith("(album)"):
        score += 40
    # Also accept "(album)" anywhere in title as secondary indicator
    elif "(album)" in title:
        score += 20

    # Check if artist name is present in title
    if normalized_artist in normalized_title:
        score += 30

    # Word overlap scoring for partial matches
    title_words = set(normalized_title.split())
    album_words = set(w for w in normalized_album.split() if len(w) > 2)

    if album_words:
        # Calculate how many album words are in the title
        album_word_matches = sum(1 for word in album_words if word in title_words)
        if album_word_matches > 0:
            score += min(10, album_word_matches * 3)

    # Penalty: if title looks like a self-titled album but we're looking for a specific album
    # E.g., "The Beatles (album)" when we want "Abbey Road"
    if "(album)" in title and normalized_album not in normalized_title:
        # Reduce score significantly if it's a self-titled album but we want a specific one
        if " greatest " not in normalized_title.lower():
            score -= 30

    return max(0, score)


def _normalize_for_comparison(text: str) -> str:
    """
    Normalize text for comparison by lowercasing and removing special characters.
    """
    text = text.lower().strip()
    # Remove common suffixes
    for suffix in [" (album)", " album", " - album", "(album)", "(song)", " song"]:
        text = text.replace(suffix, "")
    # Remove punctuation but keep spaces and word boundaries
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
