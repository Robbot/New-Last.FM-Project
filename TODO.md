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

---

## High Priority (Quick Wins)

### 1. Add Search Functionality
- [ ] Add search bar for artists, albums, and tracks
- [ ] Implement autocomplete suggestions for search
- [ ] Add search results pagination
- [ ] Integrate search into existing library views

### 2. Export Options
- [ ] Export scrobbles as CSV
- [ ] Export scrobbles as JSON
- [ ] Add date range filtering for exports
- [ ] Export album art metadata

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

### 5. Split `db.py` Into Modules
The 900+ line file could be split into:
- [ ] `db/connections.py` - Connection management
- [ ] `db/scrobbles.py` - Scrobble queries
- [ ] `db/artists.py` - Artist queries
- [ ] `db/albums.py` - Album queries
- [ ] `db/tracks.py` - Track queries

### 6. API Error Handling & Retry Logic
- [ ] Add retry logic with exponential backoff for Last.fm API calls
- [ ] Handle rate limiting gracefully
- [ ] Add timeout configuration for API requests
- [ ] Better error messages for API failures

### 7. Add Health Check Endpoint
- [ ] Add `/health` endpoint for monitoring
- [ ] Check database connectivity
- [ ] Check Last.fm API availability
- [ ] Return application status

---

## Lower Priority (Nice to Have)

### 8. Test Suite
- [ ] Unit tests for data cleaning functions
- [ ] Integration tests for sync logic
- [ ] Route tests for critical endpoints
- [ ] Set up pytest configuration
- [ ] Add CI/CD pipeline (GitHub Actions)

### 9. Advanced Analytics & Visualizations
- [ ] Listening heatmap (hourly/daily patterns)
- [ ] Artist discovery graphs
- [ ] Genre trends over time
- [ ] "On this day" feature showing scrobbles from same date in previous years
- [ ] Monthly/yearly listening statistics

### 10. Async Sync with Progress Updates
- [ ] Run Last.fm sync in background (Celery or similar)
- [ ] Add real-time progress updates via WebSocket
- [ ] Show sync status in UI
- [ ] Allow manual sync trigger from web interface

### 11. Rate Limiting
- [ ] Add rate limiting middleware for API endpoints
- [ ] Implement rate limiting for Last.fm API calls
- [ ] Add per-IP rate limiting for public endpoints

### 12. Wikipedia Enhancement
- [ ] Extract and display album descriptions
- [ ] Add genre information from Wikipedia
- [ ] Show artist biographies
- [ ] Link to relevant Wikipedia articles

### 13. User Accounts (Multi-user Support)
- [ ] Add user authentication system
- [ ] Allow multiple Last.fm accounts
- [ ] Personalized dashboards per user
- [ ] User-specific settings and preferences

### 14. Advanced Filtering
- [ ] Filter by multiple artists/albums at once
- [ ] Save custom filters as presets
- [ ] Advanced search with boolean operators
- [ ] Filter by play count ranges

### 15. Data Visualization Improvements
- [ ] Interactive charts for listening trends
- [ ] Artist/album cloud visualization
- [ ] Timeline view of scrobbles
- [ ] Geographic distribution (if location data available)

### 16. Performance Improvements
- [ ] Implement database query result caching
- [ ] Add pagination metadata (total count, total pages)
- [ ] Optimize static file serving with proper cache headers
- [ ] Consider database connection pooling

### 17. Developer Experience
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
