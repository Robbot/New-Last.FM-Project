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

# Clean remastered/expanded suffixes from existing database records
python -m app.services.clean_remastered_db

# Clean track name case inconsistencies (e.g., "Of Wolf and Man" vs "Of Wolf And Man")
python -m app.services.clean_track_case_db

# Backfill album years from Last.fm API
python -m app.services.backfill_album_years

# Backup database
python -m app.services.backup_db

# Activate virtual environment (if needed)
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

## Architecture

### Application Structure

The Flask app uses a modular Blueprint architecture:

- **Root `app/__init__.py`**: Factory pattern with `create_app()`, registers all blueprints
- **Blueprints**: Each functional area is a separate blueprint:
  - `app/scrobbles/`: Recent scrobbles with pagination
  - `app/artists/`: Artist library and artist detail pages
  - `app/albums/`: Album library and album detail pages
  - `app/tracks/`: Track library and track detail pages
  - `app/trackgaps/`: Unique feature showing tracks sorted by time since last play
  - `app/daterange/`: Date range filtering for all library views
- **Database Layer (`db.py`)**: All database queries centralized in root-level module. Uses `sqlite3.Row` factory for dict-like access
- **Services (`app/services/`)**: External integrations and utilities:
  - `sync_lastfm.py`: Syncs scrobbles from Last.fm API to SQLite with data cleaning
  - `fetch_tracklist.py`: Fetches album tracklists from Last.fm API
  - `clean_remastered_db.py`: One-time migration script to clean remastered suffixes from existing data
  - `clean_track_case_db.py`: Normalizes track name case inconsistencies (e.g., "Of Wolf and Man" vs "Of Wolf And Man")
  - `backfill_album_years.py` / `backfill_album_years_enhanced.py`: Populate album years from Last.fm API
  - `backup_db.py`: Database backup utility
  - `config.py`: Reads Last.fm API credentials from `config.ini`
- **Utils (`app/utils/`)**: Helper functions for range calculations and date handling
- **Static Files (`app/static/`)**: Contains `covers/` subdirectory for cached album artwork

### Data Flow

1. **Data ingestion**: `sync_lastfm.py` calls Last.fm API → inserts into SQLite (`files/lastfmstats.sqlite`)
2. **Request handling**: Flask route → calls function in `db.py` → returns `sqlite3.Row` objects
3. **Rendering**: Jinja2 templates in `app/templates/` receive data and render HTML

### Database Schema

- **`scrobble`**: Main table with artist, album, track, timestamps (uts = Unix timestamp seconds UTC)
  - Fields: `id`, `artist`, `artist_mbid`, `album`, `album_mbid`, `track`, `track_mbid`, `uts`
  - Unique constraint on `(uts, artist, album, track)` prevents duplicates
  - All timestamps stored in UTC
- **`album_art`**: Album artwork and metadata
  - Fields: `artist`, `album`, `album_mbid`, `artist_mbid`, `image_small`, `image_medium`, `image_large`, `image_xlarge`, `last_updated`, `year_col`
  - Primary key on `(artist, album)`
  - Index on `album_mbid` for lookups when available
- **`album_tracks`**: Album tracklists with track numbers, populated on-demand from Last.fm API

### Important Patterns

- **Pagination**: All list views use manual offset/limit pagination (50 items per page)
- **Album Art Caching**: `db.ensure_album_art_cached()` downloads album covers once to `app/static/covers/` and returns Flask static URLs
- **Lazy Loading**: Album tracklists are fetched from Last.fm API only when viewing album detail page, then cached in `album_tracks` table
- **Last.fm API**: Requires API key + username in `config.ini`
- **Date Filtering**: All library views support optional date range filtering via `start`/`end` or `from`/`to` query parameters

### Data Cleaning Features

The application includes sophisticated data cleaning to handle inconsistencies from Last.fm:

- **Remastered/Expanded Edition Suffix Stripping**: Automatically removes artificial suffixes like:
  - " - Remastered 2014", " - 2009 Remastered", "(Remastered)", "[2014 Remaster]"
  - " - Expanded Edition", "(Expanded Edition)"
  - " - 2007 Stereo Mix", " - Single Version", " - Album Version", " - Remix"
- **Case-Insensitive Matching**: For track/album lookups to handle capitalization variations
- **Unicode Normalization**: Normalizes text to handle different character encodings (removes accents: é → e, ö → o)
- **Common Variation Handling**: Strips suffixes like " - Single Version", " - Album Version", " - Remix"
- **Fuzzy Matching Function** (`db.py:_normalize_for_matching`): Lowercases, removes accents, replaces hyphens with spaces, fixes common typos

Cleaning is applied during sync in `sync_lastfm.py` and can be retroactively applied via `clean_remastered_db.py` or `clean_track_case_db.py`.

### Configuration

- **`config.ini`**: Contains `[last.fm]` section with `api_key` and `username`
- **Flask Config**: API key and username loaded into `app.config` at startup

### Templates

- **`base_library.html`**: Base template with navigation tabs
- All library views extend `base_library.html` and set `active_tab` context variable
- `_tracks_table.html`: Reusable partial for track tables
- Custom Jinja filter `datetime_format`: Formats Unix timestamps to readable datetime strings (UTC)
- Templates use static file serving for cached album covers from `app/static/covers/`
- Date range parameters (`from`, `to`, `rangetype`) are preserved across navigation links
