import requests

def fetch_album_tracklist_lastfm(api_key: str, artist_name: str, album_name: str):
    """
    Returns list of dicts with track_number and track name in album order.
    Uses Last.fm method album.getInfo.
    Returns empty list if API fails or album not found.
    """
    url = "https://ws.audioscrobbler.com/2.0/"
    params = {
        "method": "album.getInfo",
        "api_key": api_key,
        "artist": artist_name,
        "album": album_name,
        "format": "json",
        "autocorrect": 1,
    }

    try:
        r = requests.get(url, params=params, timeout=12, headers={"User-Agent": "Scrobbles/1.0"})
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"Last.fm API error for {artist_name} - {album_name}: {e}")
        return []

    album = data.get("album")
    if not album:
        return []

    tracks_obj = album.get("tracks", {}).get("track")
    if not tracks_obj:
        return []

    # Last.fm returns either a list or a dict for single-track albums
    if isinstance(tracks_obj, dict):
        tracks_obj = [tracks_obj]

    out = []
    for t in tracks_obj:
        name = (t.get("name") or "").strip()
        rank = t.get("@attr", {}).get("rank")

        if not name:
            continue

        try:
            track_number = int(rank)
        except (TypeError, ValueError):
            # Fallback if rank missing
            track_number = len(out) + 1

        out.append({"track": name, "track_number": track_number})

    # Ensure order
    out.sort(key=lambda x: x["track_number"])
    return out
