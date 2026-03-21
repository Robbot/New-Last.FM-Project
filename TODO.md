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

---

## High Priority (Quick Wins)

### 1. Export Options
- [ ] Export scrobbles as CSV
- [ ] Export scrobbles as JSON
- [ ] Add date range filtering for exports
- [ ] Export album art metadata

### 2. Import Historical Scrobbles from Excel
- [ ] Add `source` column to `scrobble` table to track entry origin (Last.fm API vs manual import)
- [ ] Mark existing entries as `source='lastfm'` via migration script
- [ ] Create import script for Excel files (2009-2015 era data)
- [ ] Use `INSERT OR IGNORE` to skip duplicates during import
- [ ] Mark imported entries as `source='manual'` to prevent sync conflicts
- [ ] Update sync script to only update/delete entries where `source='lastfm'`
- [ ] Add import preview showing rows to be added vs skipped
- [ ] Handle timestamp conversion from various Excel date formats

---

## Medium Priority (Quality of Life)

### 3. Loading States & Error Notifications
- [ ] Show loading spinners during API calls
- [ ] Display toast notifications for sync status
- [ ] Better error messages for failed operations
- [ ] Add client-side JavaScript for UI improvements

### 4. Optimize Database Queries
- [ ] Add compound indexes for common query patterns
- [ ] Use `LIMIT` + `OFFSET` at database level for pagination
- [ ] Cache frequently accessed data (top artists, recent scrobbles)
- [ ] Profile slow queries and optimize them

### 5. Database Discrepancy Checking
- [ ] Create scheduled script to compare local DB vs Last.fm API
- [ ] Generate discrepancy reports (missing scrobbles, metadata mismatches)
- [ ] Add configurable check intervals (daily, weekly)
- [ ] Store discrepancy reports in database or log files
- [ ] Optional: Auto-fix common discrepancies
- [ ] Web interface to view discrepancy reports

### 6. API Error Handling & Retry Logic
- [ ] Add retry logic with exponential backoff for Last.fm API calls
- [ ] Handle rate limiting gracefully
- [ ] Add timeout configuration for API requests
- [ ] Better error messages for API failures

### 7. Admin Panel Enhancements
- [x] Admin panel with localhost-only access control
- [x] Database browser and editor interface
- [x] Health check endpoint with system monitoring
- [x] Log viewer with cleanup functionality
- [ ] **Audit trail for all manual edits** ← Still pending
- [ ] Bulk edit capabilities (merge artists, fix album names)
- [ ] Delete individual scrobbles with confirmation

---

## Lower Priority (Nice to Have)

### 8. Spotify API Integration
- [ ] OAuth 2.0 authentication flow for Spotify
- [ ] Import liked songs/favorites from Spotify
- [ ] Export database selections to Spotify playlists
- [ ] Sync scrobbles with Spotify listening history
- [ ] Import top artists/tracks from Spotify
- [ ] Jellyfin/Plex integration for local media players
- [ ] Export playlists to Jellyfin/Plex

### 9. Test Suite
- [ ] Unit tests for data cleaning functions
- [ ] Integration tests for sync logic
- [ ] Route tests for critical endpoints
- [ ] Set up pytest configuration
- [ ] Add CI/CD pipeline (GitHub Actions)

### 10. Advanced Analytics & Visualizations
- [ ] Listening heatmap (hourly/daily patterns)
- [ ] Artist discovery graphs
- [ ] Genre trends over time
- [ ] "On this day" feature showing scrobbles from same date in previous years
- [ ] Monthly/yearly listening statistics

### 11. Async Sync with Progress Updates
- [ ] Run Last.fm sync in background (Celery or similar)
- [ ] Add real-time progress updates via WebSocket
- [ ] Show sync status in UI
- [ ] Allow manual sync trigger from web interface

### 12. Rate Limiting
- [ ] Add rate limiting middleware for API endpoints
- [ ] Implement rate limiting for Last.fm API calls
- [ ] Add per-IP rate limiting for public endpoints

### 13. Wikipedia Enhancement
- [ ] Extract and display album descriptions
- [ ] Add genre information from Wikipedia
- [ ] Show artist biographies
- [ ] Link to relevant Wikipedia articles

### 14. User Accounts (Multi-user Support)
- [ ] Add user authentication system
- [ ] Allow multiple Last.fm accounts
- [ ] Personalized dashboards per user
- [ ] User-specific settings and preferences

### 15. Advanced Filtering
- [ ] Filter by multiple artists/albums at once
- [ ] Save custom filters as presets
- [ ] Advanced search with boolean operators
- [ ] Filter by play count ranges

### 16. Data Visualization Improvements
- [ ] Interactive charts for listening trends
- [ ] Artist/album cloud visualization
- [ ] Timeline view of scrobbles
- [ ] Geographic distribution (if location data available)

### 17. Performance Improvements
- [ ] Implement database query result caching
- [ ] Add pagination metadata (total count, total pages)
- [ ] Optimize static file serving with proper cache headers
- [ ] Consider database connection pooling

### 18. Developer Experience
- [ ] Add pre-commit hooks for code formatting
- [ ] Set up linting (ruff, pylint, or similar)
- [ ] Add code formatting configuration (black, etc.)
- [ ] Create development documentation
- [ ] Add Docker configuration for easy local setup

---

## Refactoring Opportunities

### Code Quality
- [ ] Remove code duplication in date range processing
- [ ] Consolidate pagination patterns across blueprints
- [ ] Extract common database operations into reusable functions
- [ ] Add type hints throughout the codebase

### Configuration Management
- [ ] Remove duplicated `config.ini` files
- [ ] Add environment-specific configurations (dev, prod)
- [ ] Validate configuration values at startup
- [ ] Add configuration schema documentation

---

## Security Improvements

- [ ] Add CSRF protection for forms
- [ ] Implement content security policy headers
- [ ] Add clickjacking protection
- [ ] Secure cookie settings
- [ ] Add request rate limiting per IP
- [ ] Sanitize user-generated content

---

## Bug Tracking

### Known Issues
- *None currently documented*

### Potential Issues to Investigate
- [ ] Track version grouping (e.g., "Love Will Tear Us Apart" vs "Love Will Tear Us Apart 2 - Pennine Version")
- [ ] Unicode normalization edge cases
- [ ] Timezone handling for international users

---

## Notes

- When implementing features, prefer adding tests first or alongside the implementation
- Run `python -m app.services.sync_lastfm` after database schema changes to verify compatibility
- Check logs in `logs/app_YYYYMMDD.log` for debugging issues
- All database changes should be backwards compatible or include migration scripts
