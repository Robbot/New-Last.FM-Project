"""
MusicBrainz API service for fetching artist releases.

Fetches all releases (albums) for an artist from MusicBrainz API,
including release dates and metadata.

Only includes Official releases, filtering out bootlegs, promos, and pseudo-releases.
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

YEAR_RE = re.compile(r"^(\d{4})")


def fetch_artist_releases_from_musicbrainz(artist_mbid: str) -> List[Dict[str, any]]:
    """
    Fetch all releases for an artist from MusicBrainz API.

    Only includes Official releases. This filters out bootlegs, promos, and pseudo-releases.

    Approach: Query the releases endpoint directly with status='Official' filter,
    then extract unique release-groups from those releases.

    Args:
        artist_mbid: The MusicBrainz ID of the artist

    Returns:
        A list of dicts with keys: title, year, mbid, release_type, primary_type, secondary_types
        Returns empty list on error
    """
    if not artist_mbid:
        logger.warning("No artist_mbid provided to fetch_artist_releases_from_musicbrainz")
        return []

    try:
        # Fetch Official releases for the artist
        # We use the releases endpoint with status='Official' to filter
        # inc=release-groups includes the release-group information (type, title, etc.)
        url = f"{MB_BASE_URL}/ws/2/release"
        params = {
            "artist": artist_mbid,
            "status": "official",
            "inc": "release-groups",
            "limit": 100,
            "offset": 0,
            "fmt": "json",
        }

        # Track unique release-groups we've seen
        seen_release_group_ids: Set[str] = set()
        seen_titles: Set[str] = set()
        all_releases = []

        while True:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={"User-Agent": MB_USER_AGENT, "Accept": "application/json"},
                    timeout=MB_TIMEOUT,
                )
                response.raise_for_status()
                data = response.json()

                # Process releases
                releases = data.get("releases", [])
                for release in releases:
                    # Get release-group info
                    release_group = release.get("release-group", {})
                    if not release_group:
                        continue

                    rg_id = release_group.get("id", "")
                    if not rg_id or rg_id in seen_release_group_ids:
                        continue

                    # Get primary type and secondary types
                    primary_type = release_group.get("primary-type", "")
                    if not primary_type:
                        continue

                    secondary_types = release_group.get("secondary-types", [])

                    # Only include releases with Album as primary type
                    if primary_type != "Album":
                        seen_release_group_ids.add(rg_id)
                        continue

                    # Build full type string (e.g., "Album", "Album + Compilation")
                    if secondary_types:
                        release_type = f"{primary_type} + {' + '.join(secondary_types)}"
                    else:
                        release_type = primary_type

                    # Extract title
                    title = release_group.get("title", "").strip()
                    if not title:
                        seen_release_group_ids.add(rg_id)
                        continue

                    # Skip duplicate titles (keep first encountered)
                    normalized_title = _normalize_title(title)
                    if normalized_title in seen_titles:
                        seen_release_group_ids.add(rg_id)
                        continue

                    seen_titles.add(normalized_title)
                    seen_release_group_ids.add(rg_id)

                    # Extract year from first-release-date
                    first_release_date = release_group.get("first-release-date", "")
                    year = _extract_year(first_release_date)

                    all_releases.append({
                        "title": title,
                        "album_title": title,  # Alias for database compatibility
                        "year": year,
                        "release_year": year,  # Alias for database compatibility
                        "mbid": rg_id,
                        "album_mbid": rg_id,  # Alias for database compatibility
                        "release_type": release_type,
                        "primary_type": primary_type,
                        "secondary_types": secondary_types,
                    })

                # Check if we need to fetch more pages
                total_count = data.get("release-count", 0)
                offset = params["offset"]
                if offset + len(releases) >= total_count:
                    break

                params["offset"] += len(releases)

                # Sleep to respect MusicBrainz rate limiting
                time.sleep(MB_SLEEP_SECONDS)

            except requests.RequestException as e:
                logger.error(f"Error fetching releases from MusicBrainz: {e}")
                break

        logger.info(f"Fetched {len(all_releases)} official album releases for artist {artist_mbid}")
        return all_releases

    except Exception as e:
        logger.error(f"Exception in fetch_artist_releases_from_musicbrainz: {e}", exc_info=True)
        return []


def _normalize_title(title: str) -> str:
    """
    Normalize title for comparison.
    Lowercase, remove extra whitespace, remove common suffixes.
    """
    title = title.lower().strip()

    # Remove common suffixes for matching
    suffixes = [
        " - remastered",
        " - remaster",
        " (remastered)",
        " (remaster)",
        " - expanded edition",
        " (expanded edition)",
        " - deluxe edition",
        " (deluxe edition)",
        " - bonus tracks",
        " (bonus tracks)",
    ]

    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[:-len(suffix)].strip()
            break

    # Remove extra whitespace
    title = re.sub(r'\s+', ' ', title)

    return title


def _extract_year(date_str: str) -> Optional[str]:
    """
    Extract year from ISO date string.
    Handles formats: YYYY, YYYY-MM, YYYY-MM-DD
    """
    if not date_str:
        return None

    match = YEAR_RE.match(date_str.strip())
    if match:
        year = match.group(1)
        # Validate year is reasonable
        year_int = int(year)
        if 1900 <= year_int <= datetime.now().year + 2:
            return year

    return None
