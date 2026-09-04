# Project Improvement Roadmap

The project's strongest asset is its domain knowledge: it already handles many real Last.fm and MusicBrainz inconsistencies. The main opportunity is to turn that accumulated knowledge into a safer, simpler system.

## Highest Priority

### 1. Build One Canonical Correction and Merge Engine

Corrections are currently spread across:

- JSON mapping files
- normalization functions
- many one-off `fix_*.py`, `rename_*.py`, and `redistribute_*.py` scripts
- direct textual columns alongside canonical entity IDs

That fragmentation is the main source of recurring duplicates.

Create a single transactional command such as:

```bash
python -m app.services.catalog merge-artist \
  "The Car Is On Fire" \
  "The Car Is on Fire"
```

It should:

- preview affected records
- back up automatically
- merge entity IDs and textual fields
- resolve uniqueness collisions deterministically
- register the permanent alias
- validate foreign keys and invariants
- record an audit entry
- support `--dry-run`

The merge of `The Car Is On Fire` into `The Car Is on Fire` is a good specification for this tool.

### 2. Finish the Canonical-Entity Transition

The schema currently stores both canonical IDs and repeated text:

```text
scrobble.artist + scrobble.artist_id
album_tracks.artist + album_tracks.artist_id
album_art.artist + album_art.artist_id
```

That permits the text and ID to disagree. Make entity IDs authoritative and obtain names through joins. If denormalized names are retained for performance, update them through one controlled reconciliation process.

Add database invariants that detect:

- text disagreeing with its canonical entity
- aliases pointing at multiple entities after normalization
- orphaned entities and aliases
- scrobbles lacking canonical IDs
- duplicate albums or tracks under one canonical owner
- conflicting MBIDs

### 3. Introduce a Real Migration System

There are many migration and repair scripts with no obvious authoritative ordering or applied-version history.

Use Alembic or a small SQLite-oriented migration runner with:

- ordered, immutable migrations
- an applied-migrations table
- automatic backup before risky migrations
- transactional execution
- startup schema-version checks
- separate schema migrations and data repairs

This would make deployment and recovery more predictable.

## Reliability and Safety

### 4. Secure the Admin Panel Before Expanding It

The admin panel can edit the database, but access is based on private IP ranges and trusts the first `X-Forwarded-For` value. That header can be forged unless it is accepted only from a known reverse proxy.

Add:

- actual authentication
- CSRF protection on every mutation
- trusted-proxy configuration
- secure session cookies
- an audit log for every edit
- confirmation or dry-run views for bulk operations
- removal of arbitrary database execution from the web UI, if supported

This is the most urgent security improvement if the application is internet-accessible.

### 5. Consolidate External API Clients

MusicBrainz, Last.fm, Wikipedia, and Spotify calls are implemented in several modules with differing retry behavior.

Create one client per provider with shared:

- timeouts
- exponential backoff and jitter
- rate-limit handling
- user-agent configuration
- response validation
- caching
- structured error types
- test fixtures

This would reduce intermittent sync failures and make API behavior testable without network access.

### 6. Make Sync Resumable and Observable

The sync process should persist job state rather than rely mainly on logs.

For each run, record:

- start and end time, plus status
- pages and scrobbles processed
- last successful cursor or timestamp
- retries and API failures
- inserted, updated, skipped, and quarantined records
- normalization decisions
- unresolved conflicts

The admin UI could then show progress and safely retry failed work.

## Testing and Code Quality

### 7. Raise Coverage Around Data-Changing Code

At the time of this review, the suite passed all 33 tests, but overall coverage was 33%. Important areas were particularly light:

- albums database layer: 13%
- artists database layer: 20%
- admin routes: 17%
- periodic and provider workflows: mostly lightly tested
- Last.fm sync: 34%

Prioritize tests for invariants and mutations rather than chasing a percentage:

- artist, album, and track merges
- idempotent sync
- alias conflicts
- duplicate timestamps
- missing and conflicting MBIDs
- transaction rollback after partial failure
- migration upgrades from representative old databases
- API timeout, rate-limit, and malformed-response behavior

The test run also emitted several unclosed SQLite connection warnings. Fix those to prevent descriptor leaks in longer-running processes.

### 8. Add CI and Automated Quality Checks

A small GitHub Actions workflow should run:

```bash
pytest
ruff check .
ruff format --check .
```

Also add:

- `pyproject.toml` as the central tool configuration
- type checking for core entity and ingestion code
- pre-commit hooks
- dependency vulnerability checks
- a test that loads every JSON mapping file
- a test that applies every migration to an empty database

### 9. Break Up the Remaining Large Modules

`sync_lastfm.py` is roughly 1,300 lines and mixes API access, cleaning, schema work, reconciliation, and orchestration. Split it into:

```text
providers/lastfm.py
normalization/
ingest/
reconciliation/
jobs/sync_lastfm.py
```

Keep orchestration thin and put transformation rules in pure, easily tested functions.

## Product Improvements

Once the foundation is stable, add:

- a first-class merge and metadata-correction admin workflow
- a data-quality inbox with suggested fixes and previews
- listening heatmaps and monthly or yearly comparisons
- an "on this day" listening-history view
- CSV and JSON export
- saved filters
- sync status and failure notifications

## Recommended Order

1. Secure admin mutations.
2. Build the unified merge and correction engine.
3. Complete canonical entity enforcement.
4. Introduce ordered migrations.
5. Add invariant-focused tests and CI.
6. Consolidate provider clients and sync jobs.
7. Build new analytics features.

This sequence tackles the reason so many repair scripts exist instead of adding more cleanup around the symptoms.
