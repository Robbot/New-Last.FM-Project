"""
Validation constants for the Last.fm scrobble statistics application.

Defines maximum/minimum values, allowed enum values, and length limits
for input validation across all routes.
"""

# Pagination
PER_PAGE_DEFAULT = 50
PER_PAGE_MIN = 1
PER_PAGE_MAX = 50
PAGE_MIN = 1

# Date ranges
MIN_YEAR = 1900
MAX_YEAR = 2100
MONTH_MIN = 1
MONTH_MAX = 12
DAY_MIN = 1
DAY_MAX = 31

# String lengths - maximum allowed for path parameters and query strings
MAX_ARTIST_NAME_LENGTH = 500
MAX_ALBUM_NAME_LENGTH = 500
MAX_TRACK_NAME_LENGTH = 500

# Enum values - allowed values for various parameters
ALLOWED_RANGETYPES = ["1day", "1month", "year"]
ALLOWED_SORT_BY = ["rank", "artist", "plays", "tracks"]
DEFAULT_SORT_BY = "plays"
ALLOWED_SORT_ORDER = ["asc", "desc"]
DEFAULT_SORT_ORDER = "desc"
ALLOWED_ALBUM_SORT = ["tracklist", "plays"]
DEFAULT_ALBUM_SORT = "tracklist"
ALLOWED_ARTIST_ALBUM_SORT = ["plays", "year"]
DEFAULT_ARTIST_ALBUM_SORT = "plays"

# API limits
DEFAULT_LIMIT = 50
LIMIT_MIN = 1
LIMIT_MAX = 500
