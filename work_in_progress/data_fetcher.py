import requests

API_URL = 'http://ws.audioscrobbler.com/2.0/'


def fetch_lastfm_data(user: str, api_key: str, from_timestamp: int = None) -> list[dict]:
    params = {
        'method': 'user.getrecenttracks',
        'user': user,
        'api_key': api_key,
        'format': 'json',
        'limit': 1000
    }
    if from_timestamp:
        params['from'] = from_timestamp
    
    response = requests.get(API_URL, params=params)
    data = response.json()
    return data['recenttracks']['track']
