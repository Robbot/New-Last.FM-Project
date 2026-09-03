# Debianarr migration plan

## Purpose and assumptions

This runbook moves the production Last.FM Statistics application from the host
`debianarr` to a replacement Debian/Linux host. It assumes the public URL stays
`https://scrobble.rojek.ie`, the application continues to run under systemd
behind a reverse proxy, and SQLite remains the database for this migration.

The destination host and migration date are deliberately left open. Fill these
in before scheduling the cutover:

| Item | Value |
|---|---|
| Source host | `debianarr` |
| Source application root | `/home/roju/New-Last.FM-Project` (confirm on source) |
| Destination host/IP | **TBD** |
| Destination application root | **TBD**; use the path captured from `WorkingDirectory` for the first move |
| Maintenance window | **TBD** |
| Operator | **TBD** |
| Rollback decision deadline | **TBD** |

This is intentionally a lift-and-shift. Do not combine the host migration with
containerization, a SQLite-to-PostgreSQL conversion, Python upgrades, schema
cleanup, or application refactoring. Those changes make rollback harder and
should follow a successful migration.

## What must move

The Git repository is not a complete production backup. Preserve all of the
following:

| Asset | Expected source | Required? | Notes |
|---|---|---:|---|
| Application code and exact Git commit | application root | Yes | Record the commit and any working-tree changes. |
| Live SQLite database | `files/lastfmstats.sqlite` | Yes | This is the authoritative database path in the current code. It also contains Spotify OAuth tokens. |
| SQLite sidecars | `files/lastfmstats.sqlite-wal`, `files/lastfmstats.sqlite-shm` | Conditional | Never copy these independently while writers are running. Use a SQLite backup or stop all writers first. |
| Album-cover cache | `app/static/covers/` | Yes | Database rows can refer to these local files. They can be rebuilt only slowly and incompletely. |
| Last.fm and Spotify credentials | systemd environment or `app/services/config.ini` | Yes | Transfer through a secure channel; never commit them. |
| Flask secret and proxy settings | systemd environment | Yes | Preserve `SECRET_KEY`; set the correct `SESSION_COOKIE_SECURE` and `TRUSTED_PROXY_HOPS`. |
| Runtime mapping data | `app/services/*_mappings.json` and `track_album_routing.json` | Yes | Some management tools edit files inside the Git working tree. Preserve uncommitted changes. |
| systemd units and timers | `/etc/systemd/system/` or distribution unit paths | Yes | Capture the actual unit definitions; do not rely on the stale examples in `DEPLOYMENT.md`. |
| Cron jobs | user and system crontabs | Yes, if present | Likely includes regular sync/full-sync/playlist jobs. Only one host may run them after cutover. |
| Reverse-proxy and TLS configuration | nginx/Caddy/Apache configuration and certificate mechanism | Yes | Determine whether certificates are copied or re-issued. |
| Application logs | `logs/` and journal | Optional but recommended | Retain for post-cutover comparison and audit. |
| Deployment keys/configuration | source host and GitHub settings | If still used | The workflows described in `DEPLOYMENT.md` were removed from the current branch. |

Do not mistake the tracked zero-byte files `app/services/lastfmstats.sqlite` or
`filesfmstats.sqlite` for production data. The running application resolves its
database to `<application-root>/files/lastfmstats.sqlite`.

## Known gaps that must be resolved before migration

The repository at commit `604b9135be63388869c54fb1c04913cfa3083731`
has several differences from its deployment documentation:

1. `wsgi.py`, which the documentation names as the Gunicorn entry point, is not
   present in the current tree.
2. No systemd unit, timer, reverse-proxy configuration, or GitHub workflow is
   present in the current tree.
3. `DEPLOYMENT.md` describes GitHub workflows that were removed in commit
   `7075ad2`.
4. There is no authoritative migration ledger or ordered migration runner.
5. `.env` is ignored, but the application does not load it itself. Production
   environment variables must be injected by systemd/the process manager, not
   merely placed in an `.env` file.
6. `DEPLOYMENT.md` documents a `backup_db --restore` option that the current
   backup script does not implement. Restore is a file operation performed
   while all database users are stopped.

These are pre-flight gates, not reasons to redesign the deployment. Capture the
working production entry point and units from `debianarr`. If an entry-point
file exists only on the live host, add it to source control or configuration
management and test that commit before cutover.

## Phase 1: inventory `debianarr`

Run the following read-only checks on `debianarr` and save the output in a
restricted migration work area. Redact secret values before putting any output
in an issue or repository.

```bash
hostnamectl
cat /etc/os-release
python3 --version
df -h
free -h

cd /home/roju/New-Last.FM-Project
git rev-parse HEAD
git status --short
git remote -v
find . -maxdepth 2 -type f \( -name 'wsgi.py' -o -name '*.env' -o -name 'config.ini' \) -print
du -sh files app/static/covers logs 2>/dev/null

sudo systemctl status lastfm --no-pager
sudo systemctl cat lastfm
sudo systemctl show lastfm -p User -p Group -p WorkingDirectory -p ExecStart -p EnvironmentFiles
sudo systemctl list-timers --all | grep -Ei 'lastfm|scrobble|spotify'
sudo grep -RilE 'lastfm|scrobble|spotify' /etc/systemd/system /etc/cron.d 2>/dev/null
crontab -l
sudo crontab -l

sudo ss -ltnp
sudo nginx -T 2>/dev/null | grep -nEi 'scrobble\.rojek\.ie|8001'
sudo caddy adapt --config /etc/caddy/Caddyfile --pretty 2>/dev/null
sudo apache2ctl -S 2>/dev/null
```

Also record, without printing their values, which of these settings are
defined in the service environment or configuration file:

```text
LASTFM_API_KEY
LASTFM_USERNAME
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
SPOTIFY_PLAYLIST_AUTO_GENERATE
SPOTIFY_PLAYLIST_SCHEDULE
SPOTIFY_PLAYLIST_FORGOTTEN_DAYS
SPOTIFY_PLAYLIST_TOP_TRACKS_DAYS
SPOTIFY_PLAYLIST_DEFAULT_LIMIT
SECRET_KEY
SESSION_COOKIE_SECURE
TRUSTED_PROXY_HOPS
```

Confirm the current Spotify developer-console callback. For the retained public
hostname it should normally be
`https://scrobble.rojek.ie/spotify/callback`, not the localhost default shown in
`.env.example`.

### Establish a data baseline

Run these checks against the live database and save the results:

```bash
cd /home/roju/New-Last.FM-Project
sqlite3 files/lastfmstats.sqlite 'PRAGMA quick_check;'
sqlite3 -header -column files/lastfmstats.sqlite \
  "SELECT COUNT(*) AS scrobbles, MIN(uts) AS first_uts, MAX(uts) AS last_uts FROM scrobble;"
sqlite3 -header -column files/lastfmstats.sqlite \
  "SELECT 'artist' AS object, COUNT(*) AS rows FROM artist
   UNION ALL SELECT 'album', COUNT(*) FROM album
   UNION ALL SELECT 'track', COUNT(*) FROM track
   UNION ALL SELECT 'album_art', COUNT(*) FROM album_art
   UNION ALL SELECT 'album_tracks', COUNT(*) FROM album_tracks;"
find app/static/covers -type f -printf . 2>/dev/null | wc -c
```

`PRAGMA quick_check` must return exactly `ok`. Run `PRAGMA integrity_check` on
the migration backup later.

## Phase 2: prepare and rehearse the destination

1. Match the source architecture and CPU type, or prove all Python/Pillow
   dependencies install on the new architecture.
2. Install the source host's Python major/minor version, `python3-venv`, Git,
   SQLite, the selected reverse proxy, and the utilities used by the captured
   service definition.
3. Create the same service account and application path for the first move.
   Changing paths is possible because most runtime paths are application-root
   relative, but it needlessly complicates unit and permission validation.
4. Clone the repository and check out the exact production commit. Do not copy
   `.venv`; create a new virtual environment and install `requirements.txt`.
5. Reconcile any legitimate live working-tree changes, especially JSON mapping
   files and an untracked WSGI entry point. Put durable application changes in
   Git before the final migration; keep credentials out of Git.
6. Recreate the source service/timer definitions and reverse-proxy configuration
   from the inventory. Store secrets in a root-readable systemd environment
   file (mode `0600`) or an equivalent secret store.
7. Preserve the existing `SECRET_KEY`. Set `SESSION_COOKIE_SECURE=1` for the
   HTTPS site. Set `TRUSTED_PROXY_HOPS` to the exact number of proxies; it is
   normally `1` for one local reverse proxy and `0` for direct Gunicorn access.
8. Ensure the service user owns the runtime directories `files/`,
   `files/backups/`, `logs/`, and `app/static/covers/`.

Create an online rehearsal snapshot using SQLite's backup mechanism, or use
`python -m app.services.backup_db` and select the resulting timestamped file.
Do not use a plain `cp` of a live WAL database.

```bash
mkdir -p /path/to/restricted-migration-snapshot
sqlite3 files/lastfmstats.sqlite \
  ".backup '/path/to/restricted-migration-snapshot/lastfmstats.sqlite'"
sqlite3 /path/to/restricted-migration-snapshot/lastfmstats.sqlite 'PRAGMA integrity_check;'
sha256sum /path/to/restricted-migration-snapshot/lastfmstats.sqlite
```

Transfer the rehearsal database and cover cache to the destination over SSH,
with encryption in transit. Treat the database as a secret because it contains
Spotify access and refresh tokens. Restrict the destination database and secret
files to the service account.

Start the destination on a temporary loopback-only port or without public DNS.
The exact Gunicorn command must come from the captured production `ExecStart`;
do not invent it from `DEPLOYMENT.md`. Validate:

```bash
python -m pytest
sqlite3 files/lastfmstats.sqlite 'PRAGMA integrity_check;'
curl -fsS -L http://127.0.0.1:8001/ >/dev/null
curl -fsS http://127.0.0.1:8001/admin/health/check
```

Then compare the baseline counts, first/last scrobble timestamps, cover count,
schema objects, artist/album/track pages, album images, and a read-only Spotify
status page. Do not enable sync timers or scheduled Spotify playlist generation
during rehearsal. The rehearsal database is disposable and must not become a
second production writer.

## Phase 3: cutover

At least 24–48 hours beforehand, reduce the DNS TTL for
`scrobble.rojek.ie` to 300 seconds if DNS is the cutover mechanism. Confirm a
recent off-host backup before starting.

Expected application downtime is approximately 10–30 minutes, dominated by the
final database/cache transfer and validation. Use the following order:

1. Announce the maintenance window and record the start time.
2. Disable all Last.fm sync, full-sync, Spotify playlist, and backup timers/cron
   jobs on `debianarr`.
3. Wait for any already-running jobs to finish. Verify with `ps` and the journal.
4. Stop the web service on `debianarr`. This prevents admin writes, Spotify token
   refreshes, and lazy cache writes.
5. Verify that no process has the database open for writing (`lsof`/`fuser`) and
   checkpoint the WAL.
6. Create a uniquely named final backup, verify it, and record its SHA-256 hash.
7. Transfer the final database, covers, live mapping files, and selected logs.
8. Install the database at `files/lastfmstats.sqlite`; do not install `-wal` or
   `-shm` files. Apply service-user ownership and restrictive permissions.
9. Run `PRAGMA integrity_check`, compare the saved baseline (allowing only the
   scrobbles received between baseline and shutdown), and start the destination
   web service with timers still disabled.
10. Test the destination directly by IP/SSH tunnel and with the production Host
    header. Check `/`, representative detail pages, cover images, admin access,
    and `/admin/health/check`.
11. Change the reverse-proxy upstream, floating IP, router forwarding, or DNS to
    the destination. Confirm the TLS certificate and full public request path.
12. Observe public requests and errors for at least 15 minutes.
13. Enable exactly one regular sync schedule on the destination, run one sync,
    and confirm the last scrobble timestamp advances without duplicates or
    `database is locked` errors.
14. Enable the remaining timers one at a time. Enable Spotify playlist
    generation last, because it makes externally visible changes.
15. Leave the old host stopped but intact through the rollback window. Do not
    delete its database, service configuration, or credentials yet.

For the final database operation, the essential source-side sequence is:

```bash
sudo systemctl stop LASTFM_SYNC_TIMERS_FOUND_IN_INVENTORY
sudo systemctl stop lastfm
cd /home/roju/New-Last.FM-Project
sqlite3 files/lastfmstats.sqlite 'PRAGMA wal_checkpoint(TRUNCATE);'
sqlite3 files/lastfmstats.sqlite \
  ".backup '/path/to/restricted-migration-snapshot/lastfmstats-final.sqlite'"
sqlite3 /path/to/restricted-migration-snapshot/lastfmstats-final.sqlite \
  'PRAGMA integrity_check;'
sha256sum /path/to/restricted-migration-snapshot/lastfmstats-final.sqlite
```

Replace the timer placeholder with the explicit unit names found during
inventory. If scheduling is cron-based, comment out those exact entries and
save the original crontab. Never use a wildcard stop command.

## Acceptance criteria

Cutover is complete only when all of these are true:

- The public URL serves a valid certificate and the expected application.
- The destination runs the exact approved Git commit with a clean or fully
  explained working tree.
- `PRAGMA integrity_check` returns `ok` on the installed database.
- Scrobble/entity/cache counts match the final source baseline.
- The newest scrobble timestamp advances after one controlled sync.
- Representative artist, album, track, compilation, date-range, and track-gap
  pages work and album covers load.
- Admin access restrictions work through the real proxy, and a public client
  cannot reach privileged admin mutations.
- Spotify authentication remains valid, or a planned reauthorization succeeds;
  the redirect URI uses the production HTTPS URL.
- Only the destination runs scheduled sync/playlist jobs.
- No sustained 5xx responses, lock errors, permission errors, or proxy-address
  errors appear in the application log or journal during the observation
  period.
- A destination backup has been created, verified, and copied off-host.

## Rollback

Rollback should be a conscious decision based on failed acceptance criteria,
not an attempt to run both installations concurrently.

### Before the destination has accepted writes

1. Disable destination timers and stop its web service.
2. Restore the proxy/IP/DNS route to `debianarr`.
3. Start the old web service and then its schedules.
4. Verify the public URL and scrobble sync.

### After the destination has accepted writes

Do not simply restart the old database: that loses target-side admin edits,
Spotify token refreshes, and possibly sync state.

1. Disable destination schedules and stop the destination web service.
2. Create and verify a backup of the destination database.
3. With `debianarr` still stopped, archive its old database and install the
   destination backup as `files/lastfmstats.sqlite` with the correct ownership.
4. If mapping/cache files changed on the destination, copy those back as well.
5. Run `PRAGMA integrity_check` on `debianarr`.
6. Restore traffic, start the old web service, then enable one sync schedule.
7. Verify the newest scrobble and Spotify state.

Last.fm history can usually reconcile missed listens, but it is not a substitute
for copying back the destination database: Spotify and admin-side changes are
not guaranteed to be reconstructable.

## Post-migration follow-up

After the rollback window expires:

1. Restore the normal DNS TTL.
2. Revoke obsolete host/deployment SSH keys and remove old credentials only
   after the destination backup is proven.
3. Archive the final Debianarr inventory and encrypted database backup according
   to the retention policy.
4. Update `README.md` and `DEPLOYMENT.md` with the actual host, path, entry point,
   services, schedules, proxy topology, backup/restore procedure, and ownership.
5. Track the WSGI entry point, systemd units, timer units, and sanitized proxy
   example in source control or configuration management.
6. Add an external health check and off-host, regularly restored backup.
7. Only then plan deployment modernization, ordered database migrations, or a
   container/database change as separate work.
