"""
MusicBrainz API service for fetching album release MBIDs with strict criteria.

Fetches the best matching release MBID for an album from MusicBrainz API,
with strict filtering for CD format and country preference (XE → GB → US).
"""
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# MusicBrainz settings
MB_BASE_URL = "https://musicbrainz.org"
MB_TIMEOUT = 15
MB_USER_AGENT = "LastFMStats/1.0 (https://github.com/robbot/lastfmstats; lastfmstats@robbot.com)"


# Country preference order
COUNTRY_PREFERENCE = ['XE', 'GB', 'US']


def fetch_album_mbid_strict(artist: str, album: str) -> Optional[str]:
    """
    Fetch album MBID with strict criteria: CD format only, country XE/GB/US preference.

    Strict criteria:
    1. Format must be CD (not Vinyl, Cassette, or other)
    2. Country preference: XE (Europe) → GB (UK) → US
    3. Within country preference, picks earliest release date

    Args:
        artist: Artist name
        album: Album name

    Returns:
        MBID string if found, None otherwise
    """
    if not artist or not album:
        logger.warning("No artist or album provided to fetch_album_mbid_strict")
        return None

    try:
        url = f"{MB_BASE_URL}/ws/2/release/"
        params = {
            'query': f'artist:"{artist}" AND release:"{album}" AND type:album',
            'fmt': 'json',
            'limit': 100
        }
        headers = {'User-Agent': MB_USER_AGENT}

        response = requests.get(url, params=params, headers=headers, timeout=MB_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        releases = data.get('releases', [])

        if not releases:
            logger.warning(f"No releases found for {artist} - {album}")
            return None

        # Filter for CD format only
        cd_releases = []
        for rel in releases:
            media = rel.get('media', [])
            if media and media[0].get('format') == 'CD':
                cd_releases.append(rel)

        if not cd_releases:
            logger.warning(f"No CD releases found for {artist} - {album}")
            return None

        # Group by country preference
        countries = {code: [] for code in COUNTRY_PREFERENCE}
        for rel in cd_releases:
            country = rel.get('country')
            if country in countries:
                countries[country].append(rel)

        # Log all found CD releases for debugging
        logger.debug(f"All CD releases found for {artist} - {album}:")
        for rel in cd_releases:
            logger.debug(f"  {rel['id']} | {rel.get('date', 'N/A')} | {rel.get('country', 'N/A')} | {rel.get('media', [{}])[0].get('format', 'N/A')}")

        # Select by country priority
        for country in COUNTRY_PREFERENCE:
            if countries[country]:
                # Pick earliest release date
                best = sorted(countries[country], key=lambda x: x.get('date', '9999'))[0]
                logger.info(f"Selected MBID for {artist} - {album}: {best['id']} ({country}, {best.get('date', 'N/A')})")
                return best['id']

        logger.warning(f"No CD releases found for {artist} - {album} with preferred countries (XE/GB/US)")
        return None

    except requests.RequestException as e:
        logger.error(f"Error fetching album MBID from MusicBrainz for {artist} - {album}: {e}")
        return None
    except Exception as e:
        logger.error(f"Exception in fetch_album_mbid_strict: {e}", exc_info=True)
        return None


def fetch_album_mbid_strict_dry_run(artist: str, album: str) -> dict:
    """
    Dry run version that returns all matching CD releases for inspection.

    Args:
        artist: Artist name
        album: Album name

    Returns:
        Dict with 'all_cd_releases' list and 'selected' MBID (or None)
    """
    if not artist or not album:
        return {'all_cd_releases': [], 'selected': None, 'error': 'No artist or album provided'}

    try:
        url = f"{MB_BASE_URL}/ws/2/release/"
        params = {
            'query': f'artist:"{artist}" AND release:"{album}" AND type:album',
            'fmt': 'json',
            'limit': 100
        }
        headers = {'User-Agent': MB_USER_AGENT}

        response = requests.get(url, params=params, headers=headers, timeout=MB_TIMEOUT)
        response.raise_for_status()
        data = response.json()

        releases = data.get('releases', [])

        if not releases:
            return {'all_cd_releases': [], 'selected': None, 'error': 'No releases found'}

        # Filter for CD format only
        cd_releases = []
        for rel in releases:
            media = rel.get('media', [])
            if media and media[0].get('format') == 'CD':
                cd_releases.append({
                    'id': rel['id'],
                    'date': rel.get('date', 'N/A'),
                    'country': rel.get('country', 'N/A'),
                    'format': media[0].get('format', 'N/A')
                })

        if not cd_releases:
            return {'all_cd_releases': [], 'selected': None, 'error': 'No CD releases found'}

        # Group by country preference and select
        countries = {code: [] for code in COUNTRY_PREFERENCE}
        for rel in cd_releases:
            if rel['country'] in countries:
                countries[rel['country']].append(rel)

        selected_mbid = None
        for country in COUNTRY_PREFERENCE:
            if countries[country]:
                best = sorted(countries[country], key=lambda x: x.get('date', '9999'))[0]
                selected_mbid = best['id']
                break

        return {
            'all_cd_releases': cd_releases,
            'selected': selected_mbid,
            'error': None
        }

    except Exception as e:
        return {'all_cd_releases': [], 'selected': None, 'error': str(e)}


if __name__ == "__main__":
    # Example usage and testing
    import sys

    if len(sys.argv) >= 3:
        artist = sys.argv[1]
        album = sys.argv[2]
    else:
        artist = "Blue Öyster Cult"
        album = "Agents of Fortune"

    print(f"Fetching album MBID for: {artist} - {album}")
    mbid = fetch_album_mbid_strict(artist, album)
    print(f"Result: {mbid}")

    print("\n" + "="*60)
    print("DRY RUN - All CD releases:")
    result = fetch_album_mbid_strict_dry_run(artist, album)
    for rel in result['all_cd_releases']:
        print(f"  {rel['id']} | {rel['date']} | {rel['country']} | {rel['format']}")
    print(f"\nSelected: {result['selected']}")
