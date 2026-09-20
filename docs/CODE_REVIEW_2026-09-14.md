# Code Review — 2026-09-14

Findings from an empirical review of the working tree at commit `4a6b632` (plus
uncommitted changes). Nothing in this document has been fixed; it is a record of
conclusions only.

This complements `PROJECT_IMPROVEMENT_ROADMAP.md` rather than replacing it. Parts
of that roadmap have since landed — `SECRET_KEY`, `ProxyFix` with configurable
trusted hops, session cookie hardening, and admin CSRF (a global `fetch` wrapper
in `templates/admin/base_admin.html:65` injects the token on every same-origin
mutation) are all implemented. The review below therefore concentrates on
concrete defects and on putting measurements behind the roadmap's structural
claims.

---

## Bugs worth fixing

### 1. The admin DB editor silently wipes `mbid` on the canonical entity tables

Highest priority: latent data corruption in the newest and most important tables.

The server selects editable columns with `not col.endswith('_mbid')`
(`app/admin/routes.py:395`), then writes every one of them using
`request.form.get(col, '')` (`app/admin/routes.py:400`). The client marks a field
read-only with `col.includes('mbid')` (`app/templates/admin/database.html:199`)
and submits only non-readonly fields (`app/templates/admin/database.html:221`).

The two rules agree on `artist_mbid` / `album_mbid` / `track_mbid`. They disagree
on one case: the `artist`, `album`, and `track` entity tables each have a column
named exactly `mbid`.

- Client: `'mbid'.includes('mbid')` is true → rendered read-only → **not submitted**
- Server: `'mbid'.endswith('_mbid')` is false → treated as editable → **written as `''`**

So editing any row in `artist`, `album`, or `track` through the admin database
browser blanks that row's MBID.

Not yet triggered — `SELECT COUNT(*) FROM {artist,album,track} WHERE mbid=''`
returns 0 for all three. Worth noting that `''` would also be invisible to the
`mbid IS NULL` predicates the backfill scripts rely on, so the damage would not
surface as "missing MBID."

Fix in two parts, both worthwhile:

- Send the column policy from the server to the template instead of
  reimplementing it in JavaScript.
- Update only columns actually present in the request (`if col in request.form`),
  so an omitted field is never interpreted as "set to empty."

### 2. Every library view loads the entire result set to render 50 rows

All six list routes compute `total_rows = len(rows)` and then slice
`rows[offset:limit]` in Python:

| route | lines |
|---|---|
| `app/scrobbles/routes.py` | 23, 32 |
| `app/tracks/routes.py` | 22, 30 |
| `app/albums/routes.py` | 29, 37 |
| `app/artists/routes.py` | 126, 135 |
| `app/trackgaps/routes.py` | 20, 28 |
| `app/compilations/routes.py` | 29, 37 |

None of `get_latest_scrobbles`, `get_top_tracks`, `get_top_albums`, or
`get_track_gaps` accept a limit or offset. Measured against the live database:

| view | rows materialized | time | rows shown |
|---|---|---|---|
| `/library/scrobbles` | 200,964 | 343 ms | 50 |
| `/library/tracks` | 29,708 | 285 ms | 50 |
| `/library/trackgaps` | 32,762 | 260 ms | 50 |
| `/library/albums` | 4,081 | 150 ms | 50 |

Survivable today, but the scrobbles view grows linearly with listening history
indefinitely. Push `LIMIT`/`OFFSET` plus a separate `COUNT(*)` into those four
functions.

CLAUDE.md describes this as "manual offset/limit pagination," which is not what
the code does; that line needs correcting regardless of whether the queries change.

### 3. The connection context manager is built but essentially unused

`db_connection()` exists at `app/db/connections.py:48` and TODO.md marks it
complete, but there is exactly **one** `with db_connection()` in the application
against **63** raw `get_db_connection()` calls inside `app/db/`, only 11 of which
sit in a `try/finally`:

| module | opens | `finally:` |
|---|---|---|
| `albums.py` | 19 | 4 |
| `artists.py` | 15 | 5 |
| `notifications.py` | 9 | **0** |
| `playlist_queries.py` | 9 | **0** |
| `tracks.py` | 6 | 1 |
| `scrobbles.py` | 3 | **0** |
| `connections.py` | 2 | 1 |

Roughly 50 call sites leak their connection if a query raises. This is the source
of the unclosed-SQLite-connection warnings noted in the roadmap. Mechanical to
fix, and the tool already exists.

### 4. The test suite does not run on a clean checkout

`create_app()` calls `get_api_key()` eagerly (`app/__init__.py:90`), which raises
`FileNotFoundError` (`app/services/config.py:30`) when neither the environment
variables nor `config.ini` are present. Because `tests/conftest.py:24` builds the
app in the `app` fixture, setup fails for every test that needs it:

- clean environment: **44 of 63 tests ERROR**
- with `LASTFM_API_KEY=dummy LASTFM_USERNAME=dummy`: **63 pass**, coverage **41%**

The suite currently passes only because the developer shell carries credentials.
Resolve credentials lazily at first API use, or skip the lookup under `TESTING`,
so neither tests nor CI depend on ambient secrets.

### 5. The documented entrypoint does not exist

`README.md:73` and CLAUDE.md both instruct `python wsgi.py`, and CLAUDE.md's
gunicorn example references `wsgi:app`. But `wsgi.py` is gitignored at
`.gitignore:2` and is absent from the repository. A fresh clone cannot start the
application as documented.

Either commit a credential-free `wsgi.py` or change the docs to
`flask --app app run`.

### 6. Smaller items

- `admin_sync` shells out to `'python'` from `PATH` with no `cwd`
  (`app/admin/routes.py:431`). Under systemd/gunicorn this is likely not the venv
  interpreter, and `-m app.services.sync_lastfm` depends on the server process's
  working directory. Use `sys.executable` and pin `cwd`.
- CLAUDE.md documents `notifications.dismissed`; the actual column is
  `dismissed_at`.
- Two bare `except:` clauses at `app/services/fetch_artist_mbid.py:126` and `:465`.
- Three rows have `scrobble.album_mbid = ''` rather than `NULL` — the same
  empty-string-vs-NULL inconsistency described in finding 1.

---

## Structural findings, with measurements

The roadmap's first priority — a single canonical merge and correction engine —
is correct, and the data shows the need is growing rather than shrinking.

**One-off repair scripts are accelerating.** `app/services/` holds 122 modules,
**48** of which are single-target one-off repairs
(`fix_budka_suflera_pozegnanie_cyganeria.py`,
`redistribute_rammstein_greatest_hits.py`, `rename_lush_ciao.py`, and so on).
Added per month:

| month | one-off scripts added |
|---|---|
| 2026-03 | 2 |
| 2026-04 | 2 |
| 2026-05 | 5 |
| 2026-07 | 2 |
| 2026-08 | **28** |
| 2026-09 | 5 |

August 2026 alone produced more than the preceding five months combined.

**Normalization logic is heavily duplicated.** There are **43**
`normalize_*` / `clean_*` function definitions across the codebase, and **20+
modules independently implement remaster/edition suffix stripping** — including
four separate normalizers split between `app/db/connections.py` and
`app/services/sync_lastfm.py` that share no code.

The untracked `app/services/album_title_rules.py` is exactly the right shape: a
small module of pure title rules importable by both ingestion and the canonical
entity writers. Generalizing that into an `app/normalization/` package and making
it the single home for all 43 functions — together with a parameterized
`catalog merge` command — is what flattens the one-off curve.

**The data-quality inbox is past human scale.** 8,509 open `track_mismatch`
notifications out of 8,926 total. One-at-a-time resolution cannot keep up; the UI
needs grouping and bulk apply, or the queue is effectively write-only.

**Tooling gaps.** No `pyproject.toml`, `setup.cfg`, or `.flake8`, so flake8 runs
at the 79-column default and reports **2,947 issues — 2,672 of them E501**. That
noise buries the real signal: 69 `F401` unused imports, 27 `F841` unused locals,
2 bare excepts. Setting `line-length = 100` (or moving to ruff) makes the list
actionable in a single pass. There is also no CI, no pre-commit config, and no
Dockerfile.

---

## What is working well

Worth preserving deliberately as the refactors above proceed:

- `PRAGMA foreign_keys = ON` and `busy_timeout = 15000` on every connection, with
  the reasoning documented inline at `app/db/connections.py:32-40`.
- The conservative identity policy in the entity rework — refusing to auto-merge
  on MBID because collaboration mis-tags are indistinguishable from spelling
  variants. A subtle call, and the right one.
- `--dry-run` plus automatic backup applied consistently across the destructive
  maintenance scripts.
- Comments that explain *why* rather than *what*.

The hard-won part of this project is the domain knowledge already encoded in it.
The work ahead is packaging that knowledge, not rediscovering it.

---

## Suggested order

1. Fix the `mbid` blanking bug (finding 1) — latent corruption in the entity tables.
2. Make `create_app()` credential-lazy (4) and provide `wsgi.py` (5) — unblocks
   CI and fresh clones.
3. Add `pyproject.toml` with a sane line length, plus a GitHub Actions job running
   `pytest` and `ruff` — cheap, and locks in steps 1–2.
4. Sweep `app/db/` onto `db_connection()` (3) — mechanical, removes ~50 leak sites.
5. Push `LIMIT`/`OFFSET` into the four list queries (2).
6. Then the roadmap's item 1: `app/normalization/` plus a parameterized
   `catalog merge` command.

Steps 1–5 are small and mutually independent. Step 6 is the real project.
