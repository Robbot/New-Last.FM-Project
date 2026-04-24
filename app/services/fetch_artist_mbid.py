"""
MusicBrainz MBID lookup service for artists and albums.

Searches MusicBrainz API for artist and album MBIDs by name.
Uses intelligent scoring to find the best match for each artist/album.

Includes Wikidata fallback when MusicBrainz API is unavailable.
"""
import logging
import time
import re
from typing import Optional, List, Dict, Set
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

# MusicBrainz settings
MB_BASE_URL = "https://musicbrainz.org"
MB_TIMEOUT = 15
MB_SLEEP_SECONDS = 1.5
MB_USER_AGENT = "LastFMStats/1.0 (https://github.com/user; lastfmstats@example.com)"


def fetch_artist_mbid(artist_name: str, max_retries: int = 2) -> Optional[str]:
    """
    Search for an artist MBID by name.

    Tries MusicBrainz API first, falls back to Wikidata if MB API fails.

    Args:
        artist_name: Name of the artist to search for
        max_retries: Maximum number of retry attempts for connection errors

    Returns:
        The MusicBrainz ID (MBID) as a string, or None if not found
    """
    if not artist_name:
        logger.warning("No artist_name provided to fetch_artist_mbid")
        return None

    # Try MusicBrainz API first
    mbid = _fetch_from_musicbrainz_api(artist_name, max_retries)
    if mbid:
        return mbid

    # Fallback to Wikidata
    logger.info(f"MusicBrainz API unavailable, trying Wikidata fallback for '{artist_name}'")
    return _fetch_from_wikidata(artist_name)


def _fetch_from_musicbrainz_api(artist_name: str, max_retries: int) -> Optional[str]:
    """Fetch MBID directly from MusicBrainz API."""
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        session = requests.Session()
        session.headers.update({
            "User-Agent": MB_USER_AGENT,
            "Accept": "application/json"
        })

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        url = f"{MB_BASE_URL}/ws/2/artist"
        params = {
            "query": f'artist:"{artist_name}"',
            "limit": 10,
            "fmt": "json",
        }

        response = session.get(url, params=params, timeout=MB_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        artists = data.get("artists", [])
        if not artists:
            logger.warning(f"No MusicBrainz results found for artist: {artist_name}")
            return None

        # Score each result and find the best match
        best_match = None
        best_score = -1

        normalized_query = _normalize_for_comparison(artist_name)

        for artist in artists:
            mbid = artist.get("id", "")
            name = artist.get("name", "")
            score = artist.get("score", 0)

            if not mbid or not name:
                continue

            match_score = _score_artist_match(name, normalized_query, score)

            if match_score > best_score:
                best_score = match_score
                best_match = mbid
                best_match_name = name

        if best_score >= 60 and best_match:
            logger.info(f"Found MBID for '{artist_name}': {best_match} (matched as '{best_match_name}', score: {best_score})")
            return best_match
        else:
            logger.warning(f"No good match found for '{artist_name}' (best score: {best_score})")
            return None

    except requests.RequestException as e:
        logger.debug(f"MusicBrainz API error for '{artist_name}': {e}")
        return None
    except Exception as e:
        logger.debug(f"Exception in MusicBrainz lookup for '{artist_name}': {e}")
        return None
    finally:
        try:
            session.close()
        except:
            pass


def _fetch_from_wikidata(artist_name: str) -> Optional[str]:
    """
    Fetch MBID from Wikidata by searching for the artist's Wikipedia page.

    This is a fallback when MusicBrainz API is unavailable.

    Args:
        artist_name: Name of the artist to search for

    Returns:
        The MusicBrainz ID (MBID) as a string, or None if not found
    """
    try:
        # Step 1: Search Wikipedia for the artist
        wikidata_id = _search_wikipedia_for_artist(artist_name)
        if not wikidata_id:
            return None

        # Step 2: Get the MusicBrainz ID from Wikidata
        return _get_mbid_from_wikidata(wikidata_id, artist_name)

    except Exception as e:
        logger.debug(f"Wikidata lookup failed for '{artist_name}': {e}")
        return None


def _search_wikipedia_for_artist(artist_name: str) -> Optional[str]:
    """Search Wikipedia and return the Wikidata ID for the best matching artist page."""
    try:
        search_api_url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": artist_name,
            "srlimit": 10,
        }

        response = requests.get(
            search_api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": MB_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()

        if "query" not in data or "search" not in data["query"]:
            return None

        search_results = data["query"]["search"]
        if not search_results:
            return None

        # Find the best match
        best_match = None
        best_score = -1

        normalized_query = _normalize_for_comparison(artist_name)

        for result in search_results:
            title = result.get("title", "")
            snippet = result.get("snippet", "")
            if not title:
                continue

            score = _score_wikipedia_match(title, snippet, normalized_query)

            if score > best_score:
                best_score = score
                best_match = title

        if best_score >= 60 and best_match:
            # Get the Wikidata ID for this page
            return _get_wikidata_id_from_page(best_match)

        return None

    except Exception as e:
        logger.debug(f"Wikipedia search failed for '{artist_name}': {e}")
        return None


def _get_wikidata_id_from_page(page_title: str) -> Optional[str]:
    """Get the Wikidata ID for a Wikipedia page."""
    try:
        api_url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "prop": "pageprops",
            "titles": page_title,
            "ppprop": "wikibase_item",
        }

        response = requests.get(
            api_url,
            params=params,
            timeout=10,
            headers={"User-Agent": MB_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()

        if "query" not in data or "pages" not in data["query"]:
            return None

        pages = data["query"]["pages"]
        page_id = next(iter(pages.keys()))

        if page_id == "-1":
            return None

        page = pages[page_id]
        pageprops = page.get("pageprops", {})

        return pageprops.get("wikibase_item")

    except Exception as e:
        logger.debug(f"Failed to get Wikidata ID for page '{page_title}': {e}")
        return None


def _get_mbid_from_wikidata(wikidata_id: str, artist_name: str) -> Optional[str]:
    """
    Get the MusicBrainz artist ID from a Wikidata entity.

    MusicBrainz artist ID is stored as property P434 in Wikidata.
    """
    try:
        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"

        response = requests.get(
            entity_url,
            timeout=10,
            headers={"User-Agent": MB_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()

        entity = data["entities"][wikidata_id]
        claims = entity.get("claims", {})

        # P434 is the MusicBrainz artist ID property
        if "P434" in claims:
            mbid = claims["P434"][0]["mainsnak"]["datavalue"]["value"]
            logger.info(f"Found MBID for '{artist_name}' via Wikidata: {mbid}")
            return mbid

        return None

    except Exception as e:
        logger.debug(f"Failed to get MBID from Wikidata for '{artist_name}': {e}")
        return None


def _score_wikipedia_match(title: str, snippet: str, normalized_query: str) -> int:
    """
    Score a Wikipedia title match against the expected artist name.
    Returns a score from 0-100.
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

    # Word overlap scoring
    title_words = set(normalized_title.split())
    query_words = set(w for w in normalized_query.split() if len(w) > 2)

    if query_words:
        query_word_matches = sum(1 for word in query_words if word in title_words)
        if query_word_matches > 0:
            score += min(20, query_word_matches * 5)

    return max(0, score)


def batch_fetch_artist_mbids(artist_names: List[str], progress_callback=None) -> Dict[str, Optional[str]]:
    """
    Fetch MBIDs for multiple artists in batch.

    Args:
        artist_names: List of artist names to lookup
        progress_callback: Optional callback function(current, total, artist_name)

    Returns:
        Dict mapping artist name to MBID (or None if not found)
    """
    results = {}
    total = len(artist_names)

    for i, artist_name in enumerate(artist_names, 1):
        mbid = fetch_artist_mbid(artist_name)
        results[artist_name] = mbid

        if progress_callback:
            progress_callback(i, total, artist_name)

        # Sleep to respect rate limiting
        if i < total:
            time.sleep(MB_SLEEP_SECONDS)

    found_count = sum(1 for mbid in results.values() if mbid)
    logger.info(f"Batch fetch complete: {found_count}/{total} artists found")

    return results


def fetch_album_mbid(artist_name: str, album_name: str, artist_mbid: Optional[str] = None, max_retries: int = 2) -> Optional[str]:
    """
    Search for an album MBID by artist and album name.

    Tries MusicBrainz API first, falls back to Wikidata if MB API fails.

    Args:
        artist_name: Name of the artist
        album_name: Name of the album
        artist_mbid: MusicBrainz artist ID (optional, but improves accuracy)
        max_retries: Maximum number of retry attempts for connection errors

    Returns:
        The MusicBrainz album ID (MBID) as a string, or None if not found
    """
    if not artist_name or not album_name:
        logger.warning("No artist_name or album_name provided to fetch_album_mbid")
        return None

    # Try MusicBrainz API first
    mbid = _fetch_album_from_musicbrainz_api(artist_name, album_name, artist_mbid, max_retries)
    if mbid:
        return mbid

    # Fallback to Wikidata
    logger.info(f"MusicBrainz API unavailable for album, trying Wikidata fallback for '{artist_name} - {album_name}'")
    return _fetch_album_from_wikidata(artist_name, album_name)


def _fetch_album_from_musicbrainz_api(artist_name: str, album_name: str, artist_mbid: Optional[str], max_retries: int) -> Optional[str]:
    """Fetch album MBID directly from MusicBrainz API."""
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        session = requests.Session()
        session.headers.update({
            "User-Agent": MB_USER_AGENT,
            "Accept": "application/json"
        })

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)

        url = f"{MB_BASE_URL}/ws/2/release-group"
        params = {
            "limit": 10,
            "fmt": "json",
        }

        # Build query - use artist_mbid if available for better accuracy
        if artist_mbid:
            params["query"] = f'arid:{artist_mbid} AND release:"{album_name}"'
        else:
            params["query"] = f'artist:"{artist_name}" AND release:"{album_name}"'

        response = session.get(url, params=params, timeout=MB_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        release_groups = data.get("release-groups", [])
        if not release_groups:
            logger.warning(f"No MusicBrainz results found for album: {artist_name} - {album_name}")
            return None

        # Score each result and find the best match
        best_match = None
        best_score = -1

        normalized_query = _normalize_for_comparison(album_name)

        for release_group in release_groups:
            mbid = release_group.get("id", "")
            title = release_group.get("title", "")
            score = release_group.get("score", 0)

            if not mbid or not title:
                continue

            match_score = _score_album_match(title, normalized_query, score)

            if match_score > best_score:
                best_score = match_score
                best_match = mbid
                best_match_title = title

        if best_score >= 60 and best_match:
            logger.info(f"Found album MBID for '{artist_name} - {album_name}': {best_match} (matched as '{best_match_title}', score: {best_score})")
            return best_match
        else:
            logger.warning(f"No good match found for album '{artist_name} - {album_name}' (best score: {best_score})")
            return None

    except requests.RequestException as e:
        logger.debug(f"MusicBrainz API error for album '{artist_name} - {album_name}': {e}")
        return None
    except Exception as e:
        logger.debug(f"Exception in MusicBrainz album lookup for '{artist_name} - {album_name}': {e}")
        return None
    finally:
        try:
            session.close()
        except:
            pass


def _fetch_album_from_wikidata(artist_name: str, album_name: str) -> Optional[str]:
    """
    Fetch album MBID from Wikidata by searching for the album's Wikipedia page.

    This is a fallback when MusicBrainz API is unavailable.

    Args:
        artist_name: Name of the artist
        album_name: Name of the album

    Returns:
        The MusicBrainz album ID (MBID) as a string, or None if not found
    """
    try:
        # Step 1: Search Wikipedia for the album
        wikidata_id = _search_wikipedia_for_album(artist_name, album_name)
        if not wikidata_id:
            return None

        # Step 2: Get the MusicBrainz ID from Wikidata
        return _get_album_mbid_from_wikidata(wikidata_id, artist_name, album_name)

    except Exception as e:
        logger.debug(f"Wikidata album lookup failed for '{artist_name} - {album_name}': {e}")
        return None


def _search_wikipedia_for_album(artist_name: str, album_name: str) -> Optional[str]:
    """Search Wikipedia and return the Wikidata ID for the best matching album page."""
    try:
        search_api_url = "https://en.wikipedia.org/w/api.php"

        # Search for both "AlbumName" and "Artist AlbumName"
        search_queries = [
            f"{artist_name} {album_name}",
            album_name,
        ]

        for search_query in search_queries:
            params = {
                "action": "query",
                "format": "json",
                "list": "search",
                "srsearch": search_query,
                "srlimit": 10,
            }

            response = requests.get(
                search_api_url,
                params=params,
                timeout=10,
                headers={"User-Agent": MB_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()

            if "query" not in data or "search" not in data["query"]:
                continue

            search_results = data["query"]["search"]
            if not search_results:
                continue

            # Find the best match
            best_match = None
            best_score = -1

            normalized_album = _normalize_for_comparison(album_name)
            normalized_artist = _normalize_for_comparison(artist_name)

            for result in search_results:
                title = result.get("title", "")
                snippet = result.get("snippet", "")
                if not title:
                    continue

                score = _score_album_wikipedia_match(title, snippet, normalized_album, normalized_artist)

                if score > best_score:
                    best_score = score
                    best_match = title

            if best_score >= 60 and best_match:
                # Get the Wikidata ID for this page
                wikidata_id = _get_wikidata_id_from_page(best_match)
                if wikidata_id:
                    return wikidata_id

        return None

    except Exception as e:
        logger.debug(f"Wikipedia search failed for album '{artist_name} - {album_name}': {e}")
        return None


def _score_album_wikipedia_match(title: str, snippet: str, normalized_album: str, normalized_artist: str) -> int:
    """
    Score a Wikipedia title match against the expected album name.
    Returns a score from 0-100.
    """
    score = 0
    normalized_title = _normalize_for_comparison(title)

    # MAJOR PENALTY: Songs should never match when looking for albums
    if "(song)" in title:
        return -1000

    # Check if album name is present in title (highest priority)
    if normalized_album in normalized_title or normalized_title in normalized_album:
        score += 60
        # Bonus for exact match
        if normalized_album == normalized_title:
            score += 20

    # BONUS: Musical album indicators in title
    if title and any(indicator in title.lower() for indicator in ["album", "soundtrack", "ep", "record"]):
        score += 20

    # Check if artist is mentioned in title (for disambiguation)
    if normalized_artist in normalized_title:
        score += 30

    # Check if snippet mentions musical terms
    if snippet and any(term in snippet.lower() for term in ["album", "studio album", "release", "song"]):
        score += 10

    return max(0, score)


def _get_album_mbid_from_wikidata(wikidata_id: str, artist_name: str, album_name: str) -> Optional[str]:
    """
    Get the MusicBrainz release ID from a Wikidata entity.

    MusicBrainz release ID is stored as property P4356 in Wikidata.
    """
    try:
        entity_url = f"https://www.wikidata.org/wiki/Special:EntityData/{wikidata_id}.json"

        response = requests.get(
            entity_url,
            timeout=10,
            headers={"User-Agent": MB_USER_AGENT},
        )
        response.raise_for_status()
        data = response.json()

        entity = data["entities"][wikidata_id]
        claims = entity.get("claims", {})

        # P4356 is the MusicBrainz release group ID property
        if "P4356" in claims:
            mbid = claims["P4356"][0]["mainsnak"]["datavalue"]["value"]
            logger.info(f"Found album MBID for '{artist_name} - {album_name}' via Wikidata: {mbid}")
            return mbid

        return None

    except Exception as e:
        logger.debug(f"Failed to get album MBID from Wikidata for '{artist_name} - {album_name}': {e}")
        return None


def _score_album_match(name: str, normalized_query: str, mb_score: int) -> int:
    """
    Score a MusicBrainz album match against the expected album name.
    Returns a score from 0-100.

    Scoring rules:
    - +50 points for exact match (case-insensitive)
    - +40 points if normalized names match exactly
    - +30 points if the query is contained in the result or vice versa
    - +20 points for word overlap
    - +0-20 points from MusicBrainz relevance score (scaled)
    """
    score = 0
    normalized_name = _normalize_for_comparison(name)

    # Exact match (case-insensitive)
    if name.lower() == normalized_query.lower():
        score += 50

    # Normalized exact match
    if normalized_name == normalized_query:
        score += 40

    # Containment match
    if normalized_query in normalized_name or normalized_name in normalized_query:
        score += 30

    # Word overlap scoring
    name_words = set(normalized_name.split())
    query_words = set(normalized_query.split())

    if query_words:
        query_word_matches = sum(1 for word in query_words if word in name_words)
        if query_word_matches > 0:
            overlap_ratio = query_word_matches / len(query_words)
            score += int(overlap_ratio * 20)

    # Add MusicBrainz's relevance score (0-100 scaled to 0-20)
    score += int(mb_score * 0.2)

    return min(100, score)


def _score_artist_match(name: str, normalized_query: str, mb_score: int) -> int:
    """
    Score a MusicBrainz artist match against the expected artist name.
    Returns a score from 0-100.

    Scoring rules:
    - +50 points for exact match (case-insensitive)
    - +40 points if normalized names match exactly
    - +30 points if the query is contained in the result or vice versa
    - +20 points for word overlap
    - +0-20 points from MusicBrainz relevance score (scaled)
    """
    score = 0
    normalized_name = _normalize_for_comparison(name)

    # Exact match (case-insensitive)
    if name.lower() == normalized_query.lower():
        score += 50

    # Normalized exact match
    if normalized_name == normalized_query:
        score += 40

    # Containment match
    if normalized_query in normalized_name or normalized_name in normalized_query:
        score += 30

    # Word overlap scoring
    name_words = set(normalized_name.split())
    query_words = set(normalized_query.split())

    if query_words:
        query_word_matches = sum(1 for word in query_words if word in name_words)
        if query_word_matches > 0:
            overlap_ratio = query_word_matches / len(query_words)
            score += int(overlap_ratio * 20)

    # Add MusicBrainz's relevance score (0-100 scaled to 0-20)
    score += int(mb_score * 0.2)

    return min(100, score)


def _normalize_for_comparison(text: str) -> str:
    """
    Normalize text for comparison.

    - Lowercase
    - Remove accents/diacritics
    - Remove extra whitespace
    - Remove common suffixes
    """
    import unicodedata

    text = text.lower().strip()

    # Remove accents
    text = unicodedata.normalize('NFKD', text)
    text = ''.join([c for c in text if not unicodedata.combining(c)])

    # Remove common suffixes
    suffixes = [
        " (band)",
        " band",
        " - band",
        "(band)",
        "(singer)",
        " singer",
        "(musician)",
        " musician",
        "(group)",
        " group",
    ]
    for suffix in suffixes:
        if text.endswith(suffix):
            text = text[:-len(suffix)].strip()
            break

    # Remove punctuation but keep spaces and word boundaries
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()

    return text


if __name__ == "__main__":
    # Test with a few artists
    test_artists = ["Marilyn Manson", "The Smashing Pumpkins", "Rush"]

    for artist in test_artists:
        mbid = fetch_artist_mbid(artist)
        if mbid:
            print(f"{artist}: {mbid}")
        else:
            print(f"{artist}: Not found")
        time.sleep(MB_SLEEP_SECONDS)
