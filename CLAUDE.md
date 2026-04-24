# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Flask-based web application for enhanced Last.fm scrobble statistics. The app syncs listening history from Last.fm into a local SQLite database and provides detailed views for artists, albums, tracks, and scrobbles with pagination, statistics, and unique features like track gap analysis.

## Running the Application

```bash
# Run the development server
python wsgi.py
# App runs on http://0.0.0.0:8001
```

## Key Commands

```bash
# Sync Last.fm scrobbles to database
python -m app.services.sync_lastfm

# Manage Spotify-specific track name mappings
python -m app.services.rename_and_map_track "Artist" "Album" "Wrong Name" "Correct Name"
# Or interactive mode (shows variations, renames scrobbles, AND adds mapping)
python -m app.services.rename_and_map_track

# Manage album name mappings (for incorrect album names)
python -m app.services.add_album_mapping "Artist" "Wrong Album Name" "Correct Album Name"
# Or interactive mode
python -m app.services.add_album_mapping

# Periodic full sync (catches gaps in scrobble data)
python -m app.services.periodic_full_sync

# Clean remastered/expanded suffixes from existing database records
python -m app.services.clean_remastered_db

# Clean deluxe edition suffixes
python -m app.services.clean_deluxe_edition_db

# Clean all edition suffixes (remastered, deluxe, expanded, etc.)
python -m app.services.clean_all_editions_db

# Clean track name case inconsistencies (e.g., "Of Wolf and Man" vs "Of Wolf And Man")
python -m app.services.clean_track_case_db

# Clean small words case (e.g., "of", "and", "the" in titles)
python -m app.services.clean_small_words_db

# Backfill album years from Last.fm API
python -m app.services.backfill_album_years

# Backfill album art from Last.fm API
python -m app.services.backfill_album_art

# Backup database
python -m app.services.backup_db

# Analyze mismatches between scrobble and album_tracks tables
python -m app.services.analyze_mismatches

# Clean mismatches interactively
python -m app.services.clean_mismatches

# Assign tracks to albums for compilation albums
python -m app.services.assign_compilation_tracks

# Merge artists (when one artist has multiple names)
python -m app.services.merge_artists

# Batch update artist MusicBrainz IDs (MBIDs)
python -m app.services.batch_update_artist_mbids
# Or update top N artists
python -m app.services.batch_update_artist_mbids --limit 50
# Or update a single artist
python -m app.services.batch_update_artist_mbids --artist "Artist Name"
# Dry run first (no changes)
python -m app.services.batch_update_artist_mbids --dry-run

# Activate virtual environment (if needed)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Application Structure

The Flask app uses a modular Blueprint architecture:

- **Root `app/__init__.py`**: Factory pattern with `create_app()`, registers all blueprints, configures logging and error handlers
- **Blueprints**: Each functional area is a separate blueprint:
  - `app/scrobbles/`: Recent scrobbles with pagination
  - `app/artists/`: Artist library and artist detail pages with MusicBrainz integration
  - `app/albums/`: Album library and album detail pages
  - `app/tracks/`: Track library and track detail pages
  - `app/trackgaps/`: Unique feature showing tracks sorted by time since last play
  - `app/daterange/`: Date range filtering for all library views
  - `app/admin/`: Admin panel with dashboard, database browser, log viewer, health checks, and sync trigger (localhost only)
- **Database Layer (`app/db.py`)**: All database queries centralized module. Uses `sqlite3.Row` factory for dict-like access. Includes error logging for database operations.
- **Services (`app/services/`)**: External integrations and utilities:
  - `sync_lastfm.py`: Syncs scrobbles from Last.fm API to SQLite with data cleaning (uses logging for progress/errors)
  - `rename_and_map_track.py`: Rename scrobbles AND add to Spotify mappings in one step (recommended)
  - `add_spotify_mapping.py` / `auto_add_spotify_mappings.py`: Tools to add Spotify-specific track name corrections
  - `add_album_mapping.py`: Interactive tool to add album name corrections
  - `spotify_track_mappings.json`: Stores Spotify-to-standard track name mappings
  - `album_name_mappings.json`: Stores incorrect-to-correct album name mappings
  - `fetch_tracklist.py` / `fetch_tracklist_musicbrainz.py`: Fetches album tracklists from Last.fm/MusicBrainz API
  - `fetch_wikipedia.py` / `fetch_wikipedia_lenient.py`: Fetches Wikipedia URLs for albums
  - `fetch_artist_info.py`: Fetches artist info and images from Last.fm API
  - `fetch_artist_mbid.py`: Looks up MusicBrainz artist IDs via MusicBrainz API or Wikidata fallback
  - `batch_update_artist_mbids.py`: Batch update artist MBIDs for all artists missing them in database
  - `clean_remastered_db.py` / `clean_deluxe_edition_db.py` / `clean_all_editions_db.py`: Clean edition suffixes from existing data
  - `clean_track_case_db.py` / `clean_small_words_db.py`: Normalize track name case inconsistencies
  - `backfill_album_years.py` / `backfill_album_years_enhanced.py`: Populate album years from Last.fm API
  - `backfill_album_art.py`: Backfill album artwork from Last.fm API
  - `backfill_album_artist_db.py`: Backfill album_artist field for compilation detection
  - `backup_db.py`: Database backup utility
  - `analyze_mismatches.py` / `find_track_mismatches.py`: Analyze mismatches between scrobble and album_tracks tables
  - `clean_mismatches.py`: Interactive tool to clean up mismatches
  - `assign_compilation_tracks.py`: Assign tracks to albums for compilation albums
  - `merge_artists.py`: Merge artists when one artist has multiple names
  - `periodic_full_sync.py`: Comprehensive scan for gaps in scrobble data (runs daily at 5 AM)
  - `monitor_new_scrobbles.py`: Monitor for new scrobbles in real-time
  - `check_missing_wikipedia.py` / `update_missing_wikipedia.py`: Check/update missing Wikipedia URLs
  - `migrate_*.py`: Various database migration scripts
  - `config.py`: Reads Last.fm API credentials from `config.ini` or environment variables
- **Utils (`app/utils/`)**: Helper functions for range calculations and date handling
- **Static Files (`app/static/`)**: Contains `covers/` subdirectory for cached album artwork
- **Logging (`app/logging_config.py`)**: Centralized logging configuration with file rotation and request tracking

### Data Flow

1. **Data ingestion**: `sync_lastfm.py` calls Last.fm API → inserts into SQLite (`files/lastfmstats.sqlite`)
2. **Request handling**: Flask route → calls function in `app/db.py` → returns `sqlite3.Row` objects
3. **Rendering**: Jinja2 templates in `app/templates/` receive data and render HTML

### Database Schema

- **`scrobble`**: Main table with artist, album, track, timestamps (uts = Unix timestamp seconds UTC)
  - Fields: `id`, `artist`, `artist_mbid`, `album`, `album_mbid`, `album_artist`, `track`, `track_mbid`, `uts`
  - Unique constraint on `(uts, artist, album, track)` prevents duplicates
  - All timestamps stored in UTC
  - `album_artist` field for compilation album detection
  - `artist_mbid` and `album_mbid` fields for MusicBrainz integration (can be backfilled via batch_update_artist_mbids.py)
- **`album_art`**: Album artwork and metadata
  - Fields: `artist`, `album`, `album_mbid`, `artist_mbid`, `image_small`, `image_medium`, `image_large`, `image_xlarge`, `last_updated`, `year_col`
  - Primary key on `(artist, album)`
  - Index on `album_mbid` for lookups when available
- **`album_tracks`**: Album tracklists with track numbers, populated on-demand from Last.fm API
- **`notifications`**: Admin notification system for sync issues, skipped inserts, and system events
  - Fields: `id`, `type`, `title`, `message`, `details` (JSON), `created_at`, `dismissed`, `severity`
- **`artist_info`**: Artist information and images
  - Fields: `artist_name` (primary key), `image_url`, `bio`, `listeners`, `playcount`, `last_updated`
- **`musicbrainz_releases`**: MusicBrainz release data cache
  - Fields: `artist_mbid`, `artist_name`, `release_mbid`, `release_title`, `date`, `country`, `type`
- **`data_quality_issues`**: Data quality issue tracking (for monitoring and cleanup)

### Important Patterns

- **Pagination**: All list views use manual offset/limit pagination (50 items per page)
- **Album Art Caching**: `db.ensure_album_art_cached()` downloads album covers once to `app/static/covers/` and returns Flask static URLs
- **Lazy Loading**: Album tracklists are fetched from Last.fm API only when viewing album detail page, then cached in `album_tracks` table
- **Last.fm API**: Requires API key + username in `config.ini`
- **Date Filtering**: All library views support optional date range filtering via `start`/`end` or `from`/`to` query parameters

### Admin Panel

The application includes a comprehensive admin panel at `/admin` (localhost only):

- **Dashboard** (`/admin`): Overview with database stats, log files, and quick actions
- **Database Browser** (`/admin/database`): Browse and edit database tables with pagination
- **Log Viewer** (`/admin/logs`): View application logs with configurable line limits
- **Health Check** (`/admin/health`): System status with database and Last.fm API connectivity checks
- **Notifications** (`/admin/notifications`): View and manage admin notifications for sync issues and system events
- **Sync Trigger** (`/admin/sync`): Manually trigger Last.fm sync
- **Log Cleanup** (`/admin/logs/cleanup`): Clean up old log files

**Access Control**: Admin panel is restricted to localhost (127.0.0.1) and local network (192.168.x.x, 10.x.x.x) only.

**Notifications System**: The app creates notifications for:
- Sync skips (scrobbles that couldn't be inserted)
- Sync errors (API failures, database errors)
- Data discrepancies (missing tracks, mismatched data)
- System warnings (missing album art, incomplete data)

### Data Cleaning Features

The application includes sophisticated data cleaning to handle inconsistencies from Last.fm and Spotify:

- **Spotify Track Name Normalization**: Automatically corrects Spotify-specific track name variations to standard album tracklist names using `spotify_track_mappings.json`. Examples:
  - "A Look into Your Heart" → "A Look Into Your Heart (Different Version)"
  - Handles capitalization, parentheticals, and other formatting differences
  - Apply during sync via `sync_lastfm.py` and manage with `add_spotify_mapping.py` or `rename_and_map_track.py`
- **Album Name Normalization**: Automatically corrects incorrect album names using `album_name_mappings.json`. Examples:
  - "Reconstruction of the Fables" → "Fables of the Reconstruction"
  - "No. 4" → "№4" (proper numero sign)
  - Manage with `add_album_mapping.py`
- **Remastered/Expanded/Deluxe Edition Suffix Stripping**: Automatically removes artificial suffixes like:
  - " - Remastered 2014", " - 2009 Remastered", "(Remastered)", "[2014 Remaster]"
  - " - Expanded Edition", "(Expanded Edition)"
  - " - Deluxe Edition", "(Deluxe Edition)", "[Deluxe]"
  - " - 2007 Stereo Mix", " - Single Version", " - Album Version", " - Remix"
  - " - 25th Anniversary Edition", " - 40th Anniversary"
  - Apply via `clean_remastered_db.py`, `clean_deluxe_edition_db.py`, or `clean_all_editions_db.py`
- **Case-Insensitive Matching**: For track/album lookups to handle capitalization variations
- **Unicode Normalization**: Normalizes text to handle different character encodings (removes accents: é → e, ö → o)
- **Common Variation Handling**: Strips suffixes like " - Single Version", " - Album Version", " - Remix"
- **Fuzzy Matching Function** (`app/db/connections.py:_normalize_for_matching`): Lowercases, removes accents, replaces hyphens with spaces, fixes common typos

Cleaning is applied during sync in `sync_lastfm.py` and can be retroactively applied via various cleaning scripts.

### MusicBrainz Integration

The application integrates with MusicBrainz for enhanced metadata:

- **Artist MBID**: MusicBrainz artist IDs are stored and used for lookups
- **Release Data**: Cached release information from MusicBrainz API
- **Fetch via `fetch_musicbrainz_releases.py`**: Populates `musicbrainz_releases` table
- **Cache Management**: `refresh_musicbrainz_cache.py` updates cached data
- **Batch Artist MBID Updates**: `batch_update_artist_mbids.py` fetches and updates MBIDs for artists missing them
  - Uses MusicBrainz API with automatic Wikidata fallback when MB API is unavailable
  - Supports batch processing, single artist updates, and dry-run mode
  - Includes intelligent scoring to find best matches for artist names

### Compilation Album Handling

The application automatically detects and handles compilation albums:

- **`album_artist` Field**: Distinguishes between Various Artists albums and regular albums
- **Auto-detection During Sync**: `sync_lastfm.py` automatically sets `album_artist` to "Various Artists" for compilations
- **Track Assignment**: `assign_compilation_tracks.py` assigns tracks to albums for compilation albums
- **Batch Operations**: `batch_assign_tracks.py` and `auto_fill_assignments.py` for bulk track assignments

### Input Validation

The application includes comprehensive input validation:

- **Constants** (`app/utils/constants.py`): Defines validation limits and allowed values
- **Validators** (`app/utils/validators.py`): Helper functions for validating path parameters and query strings
- **Error Handling**: `ValidationError` exception class with custom error handler (returns 400 Bad Request)
- **Length Limits**: Maximum lengths for artist, album, and track names (500 chars)
- **Range Validation**: Min/max values for dates, page numbers, pagination limits

### Configuration

The application supports two methods for configuring Last.fm credentials:

**Method 1: Environment Variables (Recommended)**
```bash
# Create a .env file from the example
cp .env.example .env

# Edit .env with your credentials
LASTFM_API_KEY=your_api_key_here
LASTFM_USERNAME=your_username_here
```

**Method 2: config.ini (Backwards Compatibility)**
- **`config.ini`**: Contains `[last.fm]` section with `api_key` and `username`
- Located at `app/services/config.ini`
- Used as fallback when environment variables are not set

**Priority**: Environment variables take precedence over `config.ini` settings.

### Testing

The application includes a testing setup:

```bash
# Run tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=html

# Run tests with verbose output
pytest -v

# Run specific test file
pytest tests/test_specific.py

# Run linting
flake8 app/
```

**Testing Dependencies**:
- `pytest`: Test framework
- `pytest-cov`: Coverage reporting
- `pytest-flask`: Flask-specific test utilities
- `flake8`: Code linting

### Production Deployment

The application can be deployed with gunicorn:

```bash
# Install gunicorn (included in requirements.txt)
pip install gunicorn

# Run with gunicorn
gunicorn -w 4 -b 0.0.0.0:8001 wsgi:app

# Or with more workers
gunicorn -w 8 -b 0.0.0.0:8001 wsgi:app
```

**Production Considerations**:
- Set `FLASK_ENV=production` environment variable
- Use a production WSGI server like gunicorn
- Admin panel access is restricted to localhost/local network
- Log files rotate daily and are automatically cleaned up (30-day retention)

### Logging

The application uses Python's built-in logging system with a centralized configuration:

- **Log Location**: `logs/app_YYYYMMDD.log` (rotates daily)
- **Rotation**: 10MB max per file, 5 backup files kept
- **Log Levels**: DEBUG for files, INFO for console (development)
- **Request Logging**: All HTTP requests are logged with method, path, status code, and response time
- **Error Handlers**: Global 404 and 500 error handlers with logging

**Usage in code**:
```python
from app.logging_config import get_logger

logger = get_logger(__name__)
logger.info("Information message")
logger.error("Error occurred", exc_info=True)
```

**Viewing logs**:
```bash
# View today's log
tail -f logs/app_$(date +%Y%m%d).log

# View all logs
cat logs/app_*.log

# Search for errors
grep ERROR logs/app_*.log
```

### Templates

- **`base_library.html`**: Base template with navigation tabs for library views
- **Admin Templates** (`app/templates/admin/`):
  - `base_admin.html`: Base template for admin pages with sidebar navigation
  - `dashboard.html`: Admin dashboard with overview and quick actions
  - `database.html`: Database browser and editor
  - `logs.html`: Log file viewer
  - `health.html`: Health check page
  - `notifications.html`: Notifications management
  - `access_denied.html`: Access denied page for non-localhost requests
- All library views extend `base_library.html` and set `active_tab` context variable
- **`_tracks_table.html`**: Reusable partial for track tables
- **`_daterange.html`**: Reusable partial for date range filtering
- Custom Jinja filter `datetime_format`: Formats Unix timestamps to readable datetime strings (UTC)
- Templates use static file serving for cached album covers from `app/static/covers/`
- Date range parameters (`from`, `to`, `rangetype`) are preserved across navigation links

## File Structure Summary

```
app/
├── __init__.py              # Flask app factory with blueprint registration
├── db/                      # Database module (split into submodules)
│   ├── __init__.py          # Re-exports all functions for backward compatibility
│   ├── connections.py       # Connection management and utility functions
│   ├── scrobbles.py         # Scrobble-related queries
│   ├── artists.py           # Artist-related queries
│   ├── albums.py            # Album-related queries
│   ├── tracks.py            # Track-related queries
│   └── notifications.py     # Notification system
├── services/                # External integrations and utilities
│   ├── sync_lastfm.py       # Main sync script
│   ├── spotify_track_mappings.json  # Track name mappings
│   ├── album_name_mappings.json     # Album name mappings
│   └── [various cleaning/migration scripts]
├── utils/                   # Helper functions
│   ├── constants.py         # Validation constants
│   ├── validators.py        # Input validation helpers
│   └── range.py             # Date range calculations
├── logging_config.py        # Centralized logging configuration
├── [blueprints]/            # scrobbles/, artists/, albums/, tracks/, trackgaps/, daterange/, admin/
└── templates/               # Jinja2 templates
    ├── base_library.html    # Base template for library views
    └── admin/               # Admin panel templates
```
