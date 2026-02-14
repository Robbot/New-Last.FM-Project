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

    Tries English Wikipedia first, then Polish Wikipedia if not found.
    If no result is found in either language, returns "N/A" to indicate
    the search was executed but no match was found.

    Args:
        artist_name: Name of the artist
        album_name: Name of the album

    Returns:
        The Wikipedia URL if found, "N/A" if search executed but no match,
        None only on error conditions
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
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="en")

    if search_url:
        return search_url

    # Try with quotes around album name
    search_query = f'"{cleaned_album}" {artist_name}'
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="en")

    if search_url:
        return search_url

    # Try without quotes
    search_query = f"{cleaned_album} (album) {artist_name}"
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="en")

    if search_url:
        return search_url

    # Try just the album name with (album) suffix
    search_query = f'"{cleaned_album}" (album)'
    search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="en")

    # Also try the original album name if all else fails
    if not search_url and cleaned_album != album_name:
        search_query = f'"{album_name}" (album) {artist_name}'
        search_url = _search_wikipedia(search_query, artist_name, album_name, album_name, lang="en")

    # If no result in English, try Polish Wikipedia
    if not search_url:
        search_query = f'"{cleaned_album}" (album) {artist_name}'
        search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="pl")

        if not search_url:
            search_query = f'"{cleaned_album}" {artist_name}'
            search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="pl")

        if not search_url:
            search_query = f"{cleaned_album} (album) {artist_name}"
            search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="pl")

        if not search_url:
            search_query = f'"{cleaned_album}" (album)'
            search_url = _search_wikipedia(search_query, artist_name, album_name, cleaned_album, lang="pl")

        if not search_url and cleaned_album != album_name:
            search_query = f'"{album_name}" (album) {artist_name}'
            search_url = _search_wikipedia(search_query, artist_name, album_name, album_name, lang="pl")

    # Return "N/A" if search was executed but no match found in either language
    if not search_url:
        return "N/A"

    return search_url


def _search_wikipedia(query: str, artist_name: str, album_name: str, cleaned_album: str | None = None, lang: str = "en") -> Optional[str]:
    """
    Search Wikipedia for a query and return the URL if a direct match is found.

    Args:
        query: The search query string
        artist_name: The original artist name for validation
        album_name: The original album name for validation (may include edition suffixes)
        cleaned_album: The album name with edition suffixes stripped for better matching
        lang: Wikipedia language code (default: "en", also supports "pl")

    Returns:
        The Wikipedia URL if found, None otherwise
    """
    try:
        # Use Wikipedia API to search with specified language
        search_api_url = f"https://{lang}.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": 10,
        }

        response = requests.get(
            search_api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": "LastFMStats/1.0 (https://github.com/user; lastfmstats@example.com)"},
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
            snippet = result.get("snippet", "")
            if not title:
                continue

            score = _score_match(title, snippet, normalized_artist, normalized_album)

            if score > best_score:
                best_score = score
                best_match = title

        # Lenient threshold: accept scores >= 20 (down from 50)
        # This catches albums like "In Rainbows" that exactly match the title
        # but don't have "(album)" suffix or artist name in the title
        if best_score >= 20 and best_match:
            return f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(best_match.replace(' ', '_'))}"

        return None

    except (requests.RequestException, KeyError, ValueError):
        return None


def _score_match(title: str, snippet: str, normalized_artist: str, normalized_album: str) -> int:
    """
    Score a Wikipedia title match against the expected artist and album.
    Returns a score from 0-100.

    This is a more lenient version that:
    - Checks if the snippet mentions "album" (common in Wikipedia intros)
    - Uses lower threshold for exact title matches
    - More generous scoring for multi-word albums

    Scoring rules:
    - +50 points if the normalized album name appears in the title
    - +40 points if the title ends with "(album)"
    - -100 points if the title is a song page (contains "(song)")
    - +30 points if the normalized artist name appears in the title
    - +20 points if the snippet mentions "album" (for pages without "(album)" in title)
    - +10 points for close word matches
    """
    score = 0
    normalized_title = _normalize_for_comparison(title)

    # MAJOR PENALTY: Songs should never match when looking for albums
    if "(song)" in title:
        return -1000

    # Check if album name is present in title (highest priority)
    album_name_in_title = normalized_album in normalized_title
    if album_name_in_title:
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

    # NEW: Check if snippet mentions "album" (common in Wikipedia intros like "X is the seventh studio album by Y")
    # This helps identify album pages even when "(album)" isn't in the title
    if snippet and "album" in snippet.lower():
        # Only add this bonus if we don't already have "(album)" in the title
        if "(album)" not in title:
            score += 20

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

    # REVISED PENALTY: More lenient for exact title matches
    # Only apply the -40 penalty if:
    # - No "(album)" in title
    # - No artist in title
    # - AND title is not an exact match for the album name
    album_word_count = len(normalized_album.split())
    if "(album)" not in title and normalized_artist not in normalized_title:
        # Skip penalty if title exactly matches album name (this is the key fix!)
        if normalized_title != normalized_album:
            # Also skip penalty for longer album names (3+ words) with good word overlap
            if not (album_word_count >= 3 and album_name_in_title):
                score -= 40  # This brings scores down below threshold for false positives

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


def fetch_album_year_from_wikipedia(wikipedia_url: str) -> Optional[str]:
    """
    Fetch the release year from a Wikipedia album article.

    Looks for the release year in the Wikipedia infobox by parsing
    the page content and extracting the year from common patterns.

    Args:
        wikipedia_url: The Wikipedia URL of the album article

    Returns:
        The release year as a string (e.g., "2005") or None if not found
    """
    try:
        # Get the article title from the URL
        parsed = urllib.parse.urlparse(wikipedia_url)
        title = parsed.path.split('/')[-1]

        # URL decode the title (e.g., %28 -> (, %29 -> ))
        title = urllib.parse.unquote(title)

        # Use Wikipedia API to get the page content
        api_url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": title,
            "redirects": 1,
        }

        response = requests.get(
            api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": "LastFMStats/1.0 (https://github.com/user; lastfmstats@example.com)"},
        )

        if response.status_code != 200:
            return None

        data = response.json()

        if "query" not in data or "pages" not in data["query"]:
            return None

        pages = data["query"]["pages"]
        page_id = next(iter(pages.keys()))

        if page_id == "-1":  # Page not found
            return None

        page = pages[page_id]
        revisions = page.get("revisions", [])

        if not revisions:
            return None

        # Get the wikitext content (handle both old and new API formats)
        # Newer MediaWiki uses "slots" structure
        if "slots" in revisions[0]:
            content = revisions[0]["slots"]["main"].get("*", "")
        else:
            # Older format
            content = revisions[0].get("*", "")

        # Extract year from common infobox patterns
        # Pattern 1: | Released = {{Start date|YYYY (case-insensitive)
        released_match = re.search(r'\|\s*released\s*=\s*{{Start date\|(\d{4})', content, re.IGNORECASE)
        if released_match:
            return released_match.group(1)

        # Pattern 2: | Released = [[YYYY| (case-insensitive)
        released_match = re.search(r'\|\s*released\s*=\s*\[\[(\d{4})', content, re.IGNORECASE)
        if released_match:
            return released_match.group(1)

        # Pattern 3: | Released = YYYY (case-insensitive)
        released_match = re.search(r'\|\s*released\s*=\s*(\d{4})', content, re.IGNORECASE)
        if released_match:
            return released_match.group(1)

        # Pattern 4: | release year = YYYY
        released_match = re.search(r'\|\s*release year\s*=\s*(\d{4})', content, re.IGNORECASE)
        if released_match:
            return released_match.group(1)

        # Pattern 5: | Year = YYYY
        released_match = re.search(r'\|\s*Year\s*=\s*(\d{4})', content)
        if released_match:
            return released_match.group(1)

        # Pattern 6: Look for Infobox album with Released field (various formats, case-insensitive)
        # This catches: "Released = 4 March 2005", "Released = March 4, 2005", etc.
        released_match = re.search(r'\|\s*released\s*=\s*(?:{{hlist\|)?[^{\n]*?(\d{4})', content, re.IGNORECASE)
        if released_match:
            return released_match.group(1)

        # Pattern 7: Look for release date in the first sentence or infobox
        # e.g., "is the third studio album by Artist, released in 2005"
        # or "released on March 15, 2005"
        released_match = re.search(
            r'released\s+(?:on\s+)?(?:in\s+)?'
            r'(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+)?'
            r'(\d{4})',
            content, re.IGNORECASE
        )
        if released_match:
            year = released_match.group(1)
            # Validate it's a reasonable year (1900-2099)
            if 1900 <= int(year) <= 2099:
                return year

        return None

    except (requests.RequestException, KeyError, ValueError):
        return None
