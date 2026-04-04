# TODO.md

This file tracks potential improvements and features for the Last.fm scrobble statistics application.

## Completed ✅

- [x] **Add comprehensive logging infrastructure** - Implemented centralized logging with file rotation, request logging, and error handlers
- [x] **Environment Variables for Sensitive Data** - Implemented support for `.env` file with fallback to `config.ini`
- [x] **Track name case normalization** - Python-based normalization for case inconsistencies (e.g., "Of Wolf and Man" vs "Of Wolf And Man")
- [x] **Small words capitalization normalization** - Normalizes small words like "and", "of", "the" in track names
- [x] **Artist position/ranking** - Added ranking display to artist detail pages
- [x] **Listening History improvements** - Display bars even for empty years
- [x] **Remastered/Expanded edition cleaning** - Removes artificial suffixes from album names
- [x] **Comprehensive README documentation** - Added detailed installation, usage, and project structure documentation
- [x] **Add Input Validation** - Implemented centralized input validation to prevent invalid inputs, improve error handling, and enhance security
- [x] **Database Connection Context Manager** - Created `db_connection()` context manager in `db.py` for automatic connection cleanup with proper exception handling
- [x] **Add Search Functionality** - Implemented search bars for artists, albums, and tracks with case-insensitive partial matching, date range integration, and parameter preservation across pagination
- [x] **Split `db.py` Into Modules** - Refactored 900+ line file into `db/connections.py`, `db/scrobbles.py`, `db/artists.py`, `db/albums.py`, and `db/tracks.py` for better organization and maintainability
- [x] **Admin Panel** - Created `/admin` blueprint with localhost-only access control including dashboard, logs viewer, and database browser
- [x] **Health Check Endpoint** - Added `/admin/health` endpoint with database connectivity, Last.fm API availability, and application status monitoring
- [x] **Log Cleanup** - Implemented manual and automatic log cleanup (30-day retention) with configurable retention days
- [x] **Database Edit Interface** - Added manual edit capabilities for database records with row-level editing, modal interface, and bulk operations support
- [x] **Reverse Log Display Order** - Log viewer now shows newest entries first for easier monitoring
- [x] **MusicBrainz Integration** - Added MusicBrainz links to artist, album, and track detail pages via MBID fields
- [x] **Source Column for Scrobble Tracking** - Added `source` column to distinguish Last.fm API scrobbles from manual imports

---

## Future Ideas

These are feature ideas for future consideration. No active work planned.

### Data Import/Export
- Export scrobbles as CSV/JSON with date range filtering
- Export album art metadata

### User Experience
- Loading spinners during API calls
- Toast notifications for sync status
- Better error messages for failed operations
- Client-side JavaScript UI improvements

### Performance
- Add compound indexes for common query patterns
- Cache frequently accessed data (top artists, recent scrobbles)
- Profile and optimize slow queries
- Database query result caching
- Optimize static file serving with cache headers

### Admin & Operations
- Audit trail for manual database edits
- Bulk edit capabilities (merge artists, fix album names)
- Scheduled database discrepancy checking (compare local DB vs Last.fm API)
- Auto-fix common discrepancies

### API & Integrations
- Spotify API integration (OAuth, liked songs, playlists)
- Jellyfin/Plex integration for local media players
- Retry logic with exponential backoff for Last.fm API calls
- Rate limiting middleware

### Analytics & Visualization
- Listening heatmap (hourly/daily patterns)
- Artist discovery graphs
- Genre trends over time
- "On this day" feature
- Monthly/yearly statistics
- Interactive charts for listening trends
- Artist/album cloud visualization

### Advanced Features
- Async background sync with progress updates (Celery/WebSocket)
- Multi-user support with authentication
- Advanced filtering with boolean operators
- Save custom filters as presets
- Rate limiting per IP

### Content Enhancement
- Wikipedia descriptions for albums/artists
- Genre information from Wikipedia

### Developer Experience
- Test suite (unit, integration, route tests)
- CI/CD pipeline (GitHub Actions)
- Pre-commit hooks for code formatting
- Linting (ruff, pylint)
- Docker configuration for local setup

### Security
- CSRF protection for forms
- Content security policy headers
- Clickjacking protection
- Secure cookie settings

### Code Quality
- Type hints throughout codebase
- Remove code duplication
- Environment-specific configurations (dev, prod)

---

## Notes

- When implementing features, prefer adding tests first or alongside the implementation
- Run `python -m app.services.sync_lastfm` after database schema changes to verify compatibility
- Check logs in `logs/app_YYYYMMDD.log` for debugging issues
- All database changes should be backwards compatible or include migration scripts
