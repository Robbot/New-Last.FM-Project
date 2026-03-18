"""
Artist info service for fetching artist information.
Uses Last.fm website (scraping) for artist images and Wikipedia for bio/URL.
"""
import logging
import re
from typing import Optional

import requests
import urllib.parse
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://ws.audioscrobbler.com/2.0/"
LASTFM_BASE = "https://www.last.fm"


def _get_api_key() -> str:
    """Get Last.fm API key from environment or config."""
    import os
    from pathlib import Path
    import configparser

    api_key = os.getenv("LASTFM_API_KEY")
    if api_key:
        return api_key

    config = configparser.ConfigParser()
    config_path = Path(__file__).resolve().parent / "config.ini"
    config.read(config_path)
    return config["last.fm"]["api_key"]


def fetch_artist_info(artist_name: str) -> Optional[dict]:
    """
    Fetch artist information from Last.fm (image) and Wikipedia (bio, URL).
    Falls back to Wikipedia for images if Last.fm doesn't have one.

    Returns None only on error conditions. Returns a dict with all fields set to None
    if search was executed but no match was found.

    Args:
        artist_name: Name of the artist

    Returns:
        Dict with keys:
        - image_url: URL to artist image from Last.fm or Wikipedia, or None
        - bio: Short biography text from Wikipedia or None
        - wikipedia_url: Wikipedia article URL or None
        - image_source: "lastfm" or "wikipedia" or None
        Returns None only on error conditions
    """
    image_url = None
    image_source = None

    # Try Last.fm first
    try:
        image_url = _fetch_artist_image_from_lastfm(artist_name)
        if image_url:
            image_source = "lastfm"
    except Exception as e:
        logger.error(f"Error fetching artist image from Last.fm: {e}", exc_info=True)

    # Fallback to Wikipedia for image if Last.fm failed or returned placeholder
    if not image_url:
        # Try English Wikipedia for image
        wiki_result = _fetch_from_wikipedia(artist_name, lang="en", fetch_image=True)
        if wiki_result and wiki_result.get("image_url"):
            image_url = wiki_result["image_url"]
            image_source = "wikipedia"
        else:
            # Try Polish Wikipedia for image
            wiki_result = _fetch_from_wikipedia(artist_name, lang="pl", fetch_image=True)
            if wiki_result and wiki_result.get("image_url"):
                image_url = wiki_result["image_url"]
                image_source = "wikipedia"

    # Try English Wikipedia first for bio and URL (don't fetch image again)
    result = _fetch_from_wikipedia(artist_name, lang="en", fetch_image=False)
    if not result or not (result.get("wikipedia_url") or result.get("bio")):
        # If no result in English, try Polish Wikipedia
        result = _fetch_from_wikipedia(artist_name, lang="pl", fetch_image=False)

    bio = result.get("bio") if result else None
    wikipedia_url = result.get("wikipedia_url") if result else None

    return {
        "image_url": image_url,
        "bio": bio,
        "wikipedia_url": wikipedia_url,
        "image_source": image_source,
    }


def _fetch_artist_image_from_lastfm(artist_name: str) -> Optional[str]:
    """
    Fetch artist image from Last.fm website by scraping the artist page.

    Args:
        artist_name: Name of the artist

    Returns:
        URL to the artist image or None
    """
    try:
        # Build the Last.fm artist URL
        # URL encode the artist name properly
        encoded_artist = urllib.parse.quote(artist_name)
        artist_url = f"{LASTFM_BASE}/music/{encoded_artist}"

        # Don't send User-Agent - Last.fm blocks Mozilla/5.0 for some artists
        response = requests.get(artist_url, timeout=15)

        if response.status_code != 200:
            logger.warning(f"Last.fm page returned {response.status_code} for {artist_name}")
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Method 1: Try Open Graph image (most reliable for artist photos)
        og_image = soup.find("meta", property="og:image")
        if og_image and og_image.get("content"):
            img_url = og_image["content"]
            # Verify it's not a placeholder image
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 2: Try Twitter image
        twitter_image = soup.find("meta", attrs={"name": "twitter:image"})
        if twitter_image and twitter_image.get("content"):
            img_url = twitter_image["content"]
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 3: Look for header background image (classic Last.fm layout)
        header_img = soup.find("img", class_="header-new-background-image")
        if header_img and header_img.get("src"):
            img_url = header_img["src"]
            if not _is_lastfm_placeholder(img_url):
                return img_url

        # Method 4: Find any large Last.fm image on the page
        for img in soup.find_all("img"):
            src = img.get("src", "")
            if "lastfm.freetls.fastly.net" in src:
                # Look for high-resolution images
                if any(size in src for size in ["770x0", "500x500", "300x300", "ar0"]):
                    if not _is_lastfm_placeholder(src):
                        return src

        return None

    except requests.RequestException as e:
        logger.error(f"Request error fetching from Last.fm website: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Error parsing Last.fm page: {e}", exc_info=True)
        return None


def _is_lastfm_placeholder(img_url: str) -> bool:
    """
    Check if a Last.fm image URL is the default placeholder.

    The placeholder image has the hash: 2a96cbd8b46e442fc41c2b86b821562f

    Args:
        img_url: The image URL to check

    Returns:
        True if this is a placeholder image, False otherwise
    """
    # Last.fm's placeholder image hash
    placeholder_hash = "2a96cbd8b46e442fc41c2b86b821562f"
    return placeholder_hash in img_url


def _fetch_from_wikipedia(artist_name: str, lang: str = "en", fetch_image: bool = False) -> Optional[dict]:
    """
    Search Wikipedia for an artist and return their bio, URL, and optionally image.

    Args:
        artist_name: The artist name to search for
        lang: Wikipedia language code (default: "en", also supports "pl")
        fetch_image: Whether to fetch the image from Wikipedia (default: False)

    Returns:
        Dict with bio, wikipedia_url, and optionally image_url keys, or None on error
    """
    try:
        # Step 1: Search for the artist page
        search_result = _search_wikipedia(artist_name, lang)

        if not search_result:
            return {"bio": None, "wikipedia_url": None, "image_url": None}

        page_title = search_result

        # Step 2: Get bio using the Wikipedia API's extracts feature (better quality)
        bio = _get_bio_extract(page_title, lang)

        # Fallback to wikitext extraction if API extract fails
        if not bio:
            page_content = _get_page_content(page_title, lang)
            if page_content:
                bio = _extract_bio(page_content)

        # Step 3: Optionally fetch image
        image_url = None
        if fetch_image:
            page_content = _get_page_content(page_title, lang)
            if page_content:
                image_url = _extract_image_url(page_content, lang)

        wikipedia_url = f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(page_title.replace(' ', '_'))}"

        result = {
            "bio": bio,
            "wikipedia_url": wikipedia_url,
        }
        if fetch_image:
            result["image_url"] = image_url

        return result

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
        filename = re.sub(r'\|.*$', '', filename).strip()

        # Remove "File:" prefix if present
        if filename.startswith("File:"):
            filename = filename[5:]

        # URL encode the filename
        encoded_filename = urllib.parse.quote(filename, safe='/:')

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

    except Exception as e:
        logger.error(f"Error building image URL: {e}", exc_info=True)
        return None
