"""
Wikipedia API service for fetching artist information.
"""
import logging
import re
from typing import Optional

import requests
import urllib.parse

logger = logging.getLogger(__name__)


def fetch_artist_info(artist_name: str) -> Optional[dict]:
    """
    Fetch artist information from Wikipedia including image URL, bio, and Wikipedia URL.

    Tries English Wikipedia first, then falls back to Polish if not found.
    Returns None only on error conditions. Returns a dict with all fields set to None
    if search was executed but no match was found.

    Args:
        artist_name: Name of the artist

    Returns:
        Dict with keys:
        - image_url: URL to artist image or None
        - bio: Short biography text or None
        - wikipedia_url: Wikipedia article URL or None
        Returns None only on error conditions
    """
    # Try English Wikipedia first
    result = _fetch_from_wikipedia(artist_name, lang="en")
    if result and (result.get("wikipedia_url") or result.get("image_url")):
        return result

    # If no result in English, try Polish Wikipedia
    result = _fetch_from_wikipedia(artist_name, lang="pl")
    if result and (result.get("wikipedia_url") or result.get("image_url")):
        return result

    # Return dict with all None values to indicate search was executed but no match found
    return {"image_url": None, "bio": None, "wikipedia_url": None}


def _fetch_from_wikipedia(artist_name: str, lang: str = "en") -> Optional[dict]:
    """
    Search Wikipedia for an artist and return their information.

    Args:
        artist_name: The artist name to search for
        lang: Wikipedia language code (default: "en", also supports "pl")

    Returns:
        Dict with image_url, bio, and wikipedia_url keys, or None on error
    """
    try:
        # Step 1: Search for the artist page
        search_result = _search_wikipedia(artist_name, lang)

        if not search_result:
            return {"image_url": None, "bio": None, "wikipedia_url": None}

        page_title = search_result

        # Step 2: Get the page content to extract image and bio
        page_content = _get_page_content(page_title, lang)

        if not page_content:
            return {"image_url": None, "bio": None, "wikipedia_url": None}

        # Step 3: Extract image URL
        image_url = _extract_image_url(page_content, lang)

        # Step 4: Get bio using the Wikipedia API's extracts feature (better quality)
        bio = _get_bio_extract(page_title, lang)

        # Fallback to wikitext extraction if API extract fails
        if not bio:
            bio = _extract_bio(page_content)

        wikipedia_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}"

        return {
            "image_url": image_url,
            "bio": bio,
            "wikipedia_url": wikipedia_url,
        }

    except Exception as e:
        logger.error(f"Error fetching artist info from Wikipedia: {e}", exc_info=True)
        return None


def _search_wikipedia(query: str, lang: str = "en") -> Optional[str]:
    """
    Search Wikipedia for a query and return the best matching page title.

    Args:
        query: The search query string
        lang: Wikipedia language code

    Returns:
        The page title if found, None otherwise
    """
    try:
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

        normalized_query = _normalize_for_comparison(query)

        for result in search_results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if not title:
                continue

            score = _score_artist_match(title, snippet, normalized_query)

            if score > best_score:
                best_score = score
                best_match = title

        # Lenient threshold for artists
        if best_score >= 20 and best_match:
            return best_match

        return None

    except (requests.RequestException, KeyError, ValueError) as e:
        logger.error(f"Error searching Wikipedia: {e}", exc_info=True)
        return None


def _score_artist_match(title: str, snippet: str, normalized_query: str) -> int:
    """
    Score a Wikipedia title match against the expected artist name.
    Returns a score from 0-100.

    Scoring rules:
    - +60 points if the normalized artist name exactly matches the title
    - +40 points if the title contains "band", "singer", "musician", etc.
    - -100 points if the title is a song page (contains "(song)")
    - +30 points if the normalized artist name appears in the title
    - +20 points for close word matches
    """
    score = 0
    normalized_title = _normalize_for_comparison(title)

    # MAJOR PENALTY: Songs should never match when looking for artists
    if "(song)" in title:
        return -1000

    # Check if artist name is present in title (highest priority)
    if normalized_query in normalized_title or normalized_title in normalized_query:
        score += 60
        # Bonus for exact match
        if normalized_query == normalized_title:
            score += 20

    # BONUS: Musical artist indicators in title
    if title and any(indicator in title.lower() for indicator in ["band", "singer", "musician", "group", "artist"]):
        score += 40

    # Check if snippet mentions musical terms
    if snippet and any(term in snippet.lower() for term in ["band", "singer", "musician", "musical", "artist", "group"]):
        score += 20

    # Word overlap scoring for partial matches
    title_words = set(normalized_title.split())
    query_words = set(w for w in normalized_query.split() if len(w) > 2)

    if query_words:
        # Calculate how many query words are in the title
        query_word_matches = sum(1 for word in query_words if word in title_words)
        if query_word_matches > 0:
            score += min(20, query_word_matches * 5)

    return max(0, score)


def _get_page_content(page_title: str, lang: str = "en") -> Optional[str]:
    """
    Get the wikitext content of a Wikipedia page.

    Args:
        page_title: The title of the Wikipedia page
        lang: Wikipedia language code

    Returns:
        The wikitext content or None on error
    """
    try:
        api_url = f"https://{lang}.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "prop": "revisions",
            "rvprop": "content",
            "rvslots": "main",
            "titles": page_title,
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
        if "slots" in revisions[0]:
            content = revisions[0]["slots"]["main"].get("*", "")
        else:
            content = revisions[0].get("*", "")

        return content

    except (requests.RequestException, KeyError, ValueError) as e:
        logger.error(f"Error getting page content: {e}", exc_info=True)
        return None


def _extract_image_url(wikitext: str, lang: str = "en") -> Optional[str]:
    """
    Extract the main image URL from a Wikipedia page's wikitext.

    Looks for the infobox image pattern.

    Args:
        wikitext: The wikitext content of the page
        lang: Wikipedia language code

    Returns:
        The image URL or None if not found
    """
    try:
        # Pattern for infobox image: |image=Filename.jpg or |image= [[File:Filename.jpg|...]]
        # This is a simplified pattern that catches most cases

        # First try to find image in infobox
        # Pattern 1: |image=[[File:...]]
        image_match = re.search(r'\|\s*image\s*=\s*\[\[File:([^\]|]+)', wikitext, re.IGNORECASE)
        if image_match:
            filename = image_match.group(1).strip()
            return _build_image_url(filename, lang)

        # Pattern 2: |image=Filename.ext (without wikilink brackets)
        image_match = re.search(r'\|\s*image\s*=\s*([^\n\r|]+?\.(?:jpg|jpeg|png|gif|svg|webp))', wikitext, re.IGNORECASE)
        if image_match:
            filename = image_match.group(1).strip()
            return _build_image_url(filename, lang)

        # Pattern 3: |cover=[[File:...]] (for some album/artist pages)
        image_match = re.search(r'\|\s*cover\s*=\s*\[\[File:([^\]|]+)', wikitext, re.IGNORECASE)
        if image_match:
            filename = image_match.group(1).strip()
            return _build_image_url(filename, lang)

        return None

    except Exception as e:
        logger.error(f"Error extracting image URL: {e}", exc_info=True)
        return None


def _build_image_url(filename: str, lang: str = "en") -> Optional[str]:
    """
    Build a direct URL to a Wikipedia image.

    Args:
        filename: The image filename from wikitext
        lang: Wikipedia language code

    Returns:
        The direct image URL or None on error
    """
    try:
        # Clean up the filename - remove any thumbnail/size modifiers
        # e.g., "File:Example.jpg|thumb|200px" -> "File:Example.jpg"
        filename = re.sub(r'\|.*$', '', filename).strip()

        # Remove "File:" prefix if present
        if filename.startswith("File:"):
            filename = filename[5:]

        # URL encode the filename
        encoded_filename = urllib.parse.quote(filename, safe='/:')

        # Use the direct image URL pattern
        # For Wikipedia Commons (most images are hosted there)
        # We need to get the actual URL via the API

        # First character is uppercase for Wikipedia URLs
        first_char = filename[0].upper() if filename else "_"
        if first_char.lower() in filename:
            # Use the actual first character from the file
            first_char = filename[0].upper()

        # Try to get the direct URL via the ImageInfo API
        # Most Wikipedia images are hosted on Wikimedia Commons
        api_bases = [
            "https://commons.wikimedia.org/w/api.php",  # Try Commons first
            f"https://{lang}.wikipedia.org/w/api.php",   # Fallback to language-specific Wikipedia
        ]

        for api_url in api_bases:
            params = {
                "action": "query",
                "format": "json",
                "titles": f"File:{filename}",
                "prop": "imageinfo",
                "iiprop": "url",
                "iiurlwidth": 500,  # Request a reasonable size
            }

            response = requests.get(
                api_url,
                params=params,
                timeout=10,
                headers={"User-Agent": "LastFMStats/1.0 (https://github.com/user/lastfm-stats; contact@example.com)"},
            )

            if response.status_code != 200:
                continue

            data = response.json()

            if "query" not in data or "pages" not in data["query"]:
                continue

            pages = data["query"]["pages"]
            page_id = next(iter(pages.keys()))

            if page_id == "-1":  # Page not found, try next API
                continue

            page = pages[page_id]
            imageinfo = page.get("imageinfo", [])

            if not imageinfo:
                continue

            # Return the thumb URL (resized version) or full URL
            return imageinfo[0].get("thumburl") or imageinfo[0].get("url")

        return None

        page = pages[page_id]
        imageinfo = page.get("imageinfo", [])

        if not imageinfo:
            return None

        # Return the thumb URL (resized version) or full URL
        return imageinfo[0].get("thumburl") or imageinfo[0].get("url")

    except Exception as e:
        logger.error(f"Error building image URL: {e}", exc_info=True)
        return None


def _get_bio_extract(page_title: str, lang: str = "en") -> Optional[str]:
    """
    Get a bio extract from Wikipedia using the API's extracts feature.

    This returns cleaned HTML text from Wikipedia, which is much higher quality
    than parsing wikitext manually.

    Args:
        page_title: The title of the Wikipedia page
        lang: Wikipedia language code

    Returns:
        A short bio text or None if not found
    """
    try:
        api_url = f"https://{lang}.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": 1,  # Only get the intro section
            "explaintext": 1,  # Get plain text, not HTML
            "titles": page_title,
            "redirects": 1,
        }

        response = requests.get(
            api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": "LastFMStats/1.0 (https://github.com/user/lastfm-stats; contact@example.com)"},
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
        extract = page.get("extract", "")

        if not extract:
            return None

        # Take first 2-3 sentences, max ~350 chars
        sentences = [s.strip() for s in extract.split('. ') if s.strip()]
        if sentences:
            bio_sentences = []
            bio_length = 0
            for sentence in sentences[:4]:
                if bio_length + len(sentence) > 350:
                    break
                bio_sentences.append(sentence)
                bio_length += len(sentence)

            if bio_sentences:
                bio = '. '.join(bio_sentences)
                if not bio.endswith('.'):
                    bio += '.'
                return bio

        return None

    except Exception as e:
        logger.error(f"Error getting bio extract: {e}", exc_info=True)
        return None


def _extract_bio(wikitext: str) -> Optional[str]:
    """
    Extract a short bio from the Wikipedia page's wikitext.

    Uses the Wikipedia API to get the parsed HTML extract instead of raw wikitext.

    Args:
        wikitext: The wikitext content of the page

    Returns:
        A short bio text or None if not found
    """
    try:
        # For better quality bios, we should use the Wikipedia API's extracts feature
        # But since we only have wikitext here, we'll do a simpler extraction

        # Find the first heading (end of lead section)
        lead_match = re.search(r'^==\s*[^=]+\s*==', wikitext, re.MULTILINE)
        if lead_match:
            lead_text = wikitext[:lead_match.start()]
        else:
            lead_text = wikitext[:3000]  # First 3000 chars if no heading found

        # Remove infobox templates (they start with {{ and contain lots of metadata)
        lead_text = re.sub(r'\{\{Infobox[^}]*\}\}', '', lead_text, flags=re.DOTALL | re.IGNORECASE)
        lead_text = re.sub(r'\{\{Infobox musical artist[^}]*\}\}', '', lead_text, flags=re.DOTALL | re.IGNORECASE)

        # Remove other templates like {{Use dmy dates}}, {{Short description}}, etc.
        lead_text = re.sub(r'\{\{[Tt]emplate?:[^}]*\}\}', '', lead_text)
        lead_text = re.sub(r'\{\{(?:Use dmy|Use mdy|Short description|About|Listen|Portal|Good article|Featured article)[^}]*\}\}', '', lead_text, flags=re.IGNORECASE)
        lead_text = re.sub(r'\{\{[^}]{20,}\}\}', '', lead_text)  # Remove long templates

        # Remove [[File:...]] and [[Image:...]] with all parameters
        lead_text = re.sub(r'\[\[(?:File|Image):[^\]]+\]\]', '', lead_text, flags=re.IGNORECASE)

        # Remove [[links|with|pipes]] - keep the last part
        lead_text = re.sub(r'\[\[[^\|]+\|([^\]]+)\]\]', r'\1', lead_text)
        # Remove [[simple links]] - keep the text
        lead_text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', lead_text)

        # Remove refs <ref>...</ref>
        lead_text = re.sub(r'<ref[^>]*>.*?</ref>', '', lead_text, flags=re.DOTALL)
        lead_text = re.sub(r'<ref[^>]*/>', '', lead_text)

        # Remove HTML tags
        lead_text = re.sub(r'<[^>]+>', '', lead_text)

        # Clean up formatting
        lead_text = lead_text.replace("'''", "").replace("''", "")
        lead_text = lead_text.replace("&nbsp;", " ")
        lead_text = re.sub(r'\s+', ' ', lead_text).strip()

        # Skip if starts with common template leftovers
        for prefix in ["is a", "are an", "is an", "was a", "were an", "was an"]:
            if lead_text.lower().startswith(prefix):
                break
        else:
            # Find the first actual sentence
            sentence_match = re.search(r'[A-Z][^.!?]+\.(?:\s|$)', lead_text)
            if sentence_match:
                lead_text = lead_text[sentence_match.start():]

        # Take first 2-3 sentences, max ~350 chars
        sentences = [s.strip() for s in re.split(r'[.!?]\s+', lead_text) if s.strip()]
        if sentences:
            bio_sentences = []
            bio_length = 0
            for sentence in sentences[:4]:
                if bio_length + len(sentence) > 350:
                    break
                bio_sentences.append(sentence)
                bio_length += len(sentence)

            if bio_sentences:
                bio = '. '.join(bio_sentences)
                if not bio.endswith('.'):
                    bio += '.'
                return bio

        return None

    except Exception as e:
        logger.error(f"Error extracting bio: {e}", exc_info=True)
        return None


def _normalize_for_comparison(text: str) -> str:
    """
    Normalize text for comparison by lowercasing and removing special characters.
    """
    text = text.lower().strip()
    # Remove common suffixes
    for suffix in [" (band)", " band", " - band", "(band)", "(singer)", " singer"]:
        text = text.replace(suffix, "")
    # Remove punctuation but keep spaces and word boundaries
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text
