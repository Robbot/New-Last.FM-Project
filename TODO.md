# TODO.md

This file tracks potential improvements and features for the Last.fm scrobble statistics application.

## Completed ✅

- [x] **Add comprehensive logging infrastructure** - Implemented centralized logging with file rotation, request logging, and error handlers

---

## High Priority (Quick Wins)

### 1. Environment Variables for Sensitive Data
- [ ] Move Last.fm API key from `config.ini` to environment variables
- [ ] Update `app/services/config.py` to read from `os.getenv()`
- [ ] Update documentation with new environment variable setup

### 2. Add Input Validation
- [ ] Validate date range parameters in routes (prevent invalid dates, negative ranges)
- [ ] Add sanitization for user input to prevent potential issues
- [ ] Validate query parameters before database queries

### 3. Database Connection Context Manager
- [ ] Create a context manager in `db.py` for automatic connection cleanup
- [ ] Ensure connections are always closed, even on exceptions
- [ ] Pattern:
  ```python
  @contextmanager
  def get_db():
      conn = get_conn()
      try:
          yield conn
      finally:
          conn.close()
  ```

### 4. Add Search Functionality
- [ ] Add search bar for artists, albums, and tracks
- [ ] Implement autocomplete suggestions for search
- [ ] Add search results pagination
- [ ] Integrate search into existing library views

### 5. Export Options
- [ ] Export scrobbles as CSV
- [ ] Export scrobbles as JSON
- [ ] Add date range filtering for exports
- [ ] Export album art metadata

---

## Medium Priority (Quality of Life)

### 6. Loading States & Error Notifications
- [ ] Show loading spinners during API calls
- [ ] Display toast notifications for sync status
- [ ] Better error messages for failed operations
- [ ] Add client-side JavaScript for UI improvements

### 7. Optimize Database Queries
- [ ] Add compound indexes for common query patterns
- [ ] Use `LIMIT` + `OFFSET` at database level for pagination
- [ ] Cache frequently accessed data (top artists, recent scrobbles)
- [ ] Profile slow queries and optimize them

### 8. Split `db.py` Into Modules
The 900+ line file could be split into:
- [ ] `db/connections.py` - Connection management
- [ ] `db/scrobbles.py` - Scrobble queries
- [ ] `db/artists.py` - Artist queries
- [ ] `db/albums.py` - Album queries
- [ ] `db/tracks.py` - Track queries

### 9. API Error Handling & Retry Logic
- [ ] Add retry logic with exponential backoff for Last.fm API calls
- [ ] Handle rate limiting gracefully
- [ ] Add timeout configuration for API requests
- [ ] Better error messages for API failures

### 10. Add Health Check Endpoint
- [ ] Add `/health` endpoint for monitoring
- [ ] Check database connectivity
- [ ] Check Last.fm API availability
- [ ] Return application status

---

## Lower Priority (Nice to Have)

### 11. Test Suite
- [ ] Unit tests for data cleaning functions
- [ ] Integration tests for sync logic
- [ ] Route tests for critical endpoints
- [ ] Set up pytest configuration
- [ ] Add CI/CD pipeline (GitHub Actions)

### 12. Advanced Analytics & Visualizations
- [ ] Listening heatmap (hourly/daily patterns)
- [ ] Artist discovery graphs
- [ ] Genre trends over time
- [ ] "On this day" feature showing scrobbles from same date in previous years
- [ ] Monthly/yearly listening statistics

### 13. Async Sync with Progress Updates
- [ ] Run Last.fm sync in background (Celery or similar)
- [ ] Add real-time progress updates via WebSocket
- [ ] Show sync status in UI
- [ ] Allow manual sync trigger from web interface

### 14. Rate Limiting
- [ ] Add rate limiting middleware for API endpoints
- [ ] Implement rate limiting for Last.fm API calls
- [ ] Add per-IP rate limiting for public endpoints

### 15. Wikipedia Enhancement
- [ ] Extract and display album descriptions
- [ ] Add genre information from Wikipedia
- [ ] Show artist biographies
- [ ] Link to relevant Wikipedia articles

### 16. User Accounts (Multi-user Support)
- [ ] Add user authentication system
- [ ] Allow multiple Last.fm accounts
- [ ] Personalized dashboards per user
- [ ] User-specific settings and preferences

### 17. Advanced Filtering
- [ ] Filter by multiple artists/albums at once
- [ ] Save custom filters as presets
- [ ] Advanced search with boolean operators
- [ ] Filter by play count ranges

### 18. Data Visualization Improvements
- [ ] Interactive charts for listening trends
- [ ] Artist/album cloud visualization
- [ ] Timeline view of scrobbles
- [ ] Geographic distribution (if location data available)

### 19. Performance Improvements
- [ ] Implement database query result caching
- [ ] Add pagination metadata (total count, total pages)
- [ ] Optimize static file serving with proper cache headers
- [ ] Consider database connection pooling

### 20. Developer Experience
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
