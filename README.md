# Last.FM Statistics Project

A Flask-based web application for enhanced Last.fm scrobble statistics. Sync your listening history from Last.fm into a local SQLite database and explore detailed views for artists, albums, tracks, and scrobbles with pagination, statistics, and unique features like track gap analysis.

## Features

- **Complete Listening History**: Sync and view all your Last.fm scrobbles locally
- **Library Views**: Browse artists, albums, and tracks with pagination
- **Detail Pages**: Deep dive into specific artists, albums, or tracks
- **Track Gaps**: Discover tracks you haven't played in the longest time
- **Date Range Filtering**: Filter your library by specific time periods
- **Album Artwork**: Automatic caching of album covers from Last.fm
- **Statistics**: Comprehensive statistics and visualizations
- **Data Cleaning**: Handles common Last.fm inconsistencies automatically

## Live Demo

The application is running at: https://scrobble.rojek.ie

## Requirements

- Python 3.8+
- Flask
- Last.fm API key
- Last.fm account with scrobble history

## Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd New-Last.FM-Project
   ```

2. **Create virtual environment**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Last.fm credentials**

   **Option 1: Environment Variables (Recommended)**
   ```bash
   cp .env.example .env
   # Edit .env and add your credentials:
   # LASTFM_API_KEY=your_api_key_here
   # LASTFM_USERNAME=your_username_here
   ```

   **Option 2: config.ini**
   ```bash
   # Edit app/services/config.ini with your Last.fm API key and username
   ```

## Usage

### Running the Application

```bash
python wsgi.py
```

The application will be available at http://0.0.0.0:8001

### Syncing Your Last.fm Data

After starting the app for the first time, sync your scrobble history:

```bash
python -m app.services.sync_lastfm
```

This will fetch all your scrobbles from Last.fm and store them in the local SQLite database.

### Database Management

**Backup the database:**
```bash
python -m app.services.backup_db
```

**Clean remastered/expanded suffixes:**
```bash
python -m app.services.clean_remastered_db
```

**Fix track name case inconsistencies:**
```bash
python -m app.services.clean_track_case_db
```

**Backfill album years from Last.fm:**
```bash
python -m app.services.backfill_album_years
```

## Project Structure

```
New-Last.FM-Project/
├── app/
│   ├── __init__.py           # Flask app factory
│   ├── logging_config.py     # Centralized logging configuration
│   ├── scrobbles/            # Recent scrobbles blueprint
│   ├── artists/              # Artist library and detail pages
│   ├── albums/               # Album library and detail pages
│   ├── tracks/               # Track library and detail pages
│   ├── trackgaps/            # Track gap analysis feature
│   ├── daterange/            # Date range filtering
│   ├── services/             # External integrations
│   │   ├── sync_lastfm.py    # Last.fm sync service
│   │   ├── fetch_tracklist.py # Album tracklist fetching
│   │   ├── clean_remastered_db.py # Data cleaning
│   │   ├── clean_track_case_db.py # Track case normalization
│   │   ├── backfill_album_years.py # Album year backfill
│   │   ├── backup_db.py      # Database backup
│   │   └── config.py         # Configuration management
│   ├── utils/                # Helper functions
│   ├── static/               # Static files
│   │   └── covers/           # Cached album artwork
│   └── templates/            # Jinja2 templates
├── db.py                     # Database query layer
├── wsgi.py                   # Application entry point
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variables template
├── files/                    # Runtime data directory
│   └── lastfmstats.sqlite    # SQLite database
└── logs/                     # Application logs
```

## Data Cleaning Features

The application includes sophisticated data cleaning to handle Last.fm inconsistencies:

- **Remastered/Expanded Edition Stripping**: Removes artificial suffixes like " - Remastered 2014", "(Expanded Edition)"
- **Case-Insensitive Matching**: Handles capitalization variations
- **Unicode Normalization**: Normalizes different character encodings (é → e, ö → o)
- **Common Variation Handling**: Strips suffixes like " - Single Version", " - Remix"
- **Fuzzy Matching**: Handles common typos and variations

## Logging

Logs are stored in `logs/app_YYYYMMDD.log` with daily rotation. To view logs:

```bash
# View today's log
tail -f logs/app_$(date +%Y%m%d).log

# Search for errors
grep ERROR logs/app_*.log
```

## Future Enhancements

- User authentication for personalized stats
- Integration with MediaMonkey and Plex scrobble data
- More graphs and visualizations
- Spotify playlist creation
- Export functionality

## License

This project is open source and available under the MIT License.
