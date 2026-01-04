# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Flask-based web application for enhanced Last.fm scrobble statistics. The app syncs listening history from Last.fm into a local SQLite database and provides detailed views for artists, albums, tracks, and scrobbles with pagination and statistics.

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
- **Database Layer (`db.py`)**: All database queries centralized in root-level module. Uses `sqlite3.Row` factory for dict-like access
- **Services (`app/services/`)**: External integrations and utilities:
  - `sync_lastfm.py`: Syncs scrobbles from Last.fm API to SQLite
  - `fetch_tracklist.py`: Fetches album tracklists from Last.fm API
  - `config.py`: Reads Last.fm API credentials from `config.ini`

### Data Flow

1. **Data ingestion**: `sync_lastfm.py` calls Last.fm API → inserts into SQLite (`files/lastfmstats.sqlite`)
2. **Request handling**: Flask route → calls function in `db.py` → returns `sqlite3.Row` objects
3. **Rendering**: Jinja2 templates in `app/templates/` receive data and render HTML

### Database Schema

- **`scrobble`**: Main table with artist, album, track, timestamps (uts = Unix timestamp seconds UTC)
  - Unique constraint on `(uts, artist, album, track)` prevents duplicates
- **`album_art`**: Album cover URLs keyed by `album_mbid` (MusicBrainz ID)
- **`album_tracks`**: Album tracklists with track numbers, populated on-demand from Last.fm API

### Important Patterns

- **Pagination**: All list views use manual offset/limit pagination (50 items per page)
- **Album Art Caching**: `db.ensure_album_art_cached()` downloads album covers once to `app/static/covers/` and returns Flask static URLs
- **Lazy Loading**: Album tracklists are fetched from Last.fm API only when viewing album detail page, then cached in `album_tracks` table
- **Last.fm API**: Requires API key + username in `app/services/config.ini` (or `config.ini` in root)

### Configuration

- **`config.ini`**: Contains `[last.fm]` section with `api_key` and `username`
- **Flask Config**: API key and username loaded into `app.config` at startup

### Templates

- **`base_library.html`**: Base template with navigation tabs
- All library views extend `base_library.html` and set `active_tab` context variable
- `_tracks_table.html`: Reusable partial for track tables
