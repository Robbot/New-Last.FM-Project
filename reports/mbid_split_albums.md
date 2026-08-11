# Album MBID-split report

> ✅ **RESOLVED (2026-07-24).** All 55 albums normalized: minority-MBID rows repointed to each album's primary MBID across `scrobble` (228), `album_art` (46), and `album_tracks` (222). Post-fix the catalog has **0 split albums** (3725 albums × 1 `album_mbid` each). Backup: `files/lastfmstats.backup_20260724_163452_mbid_normalize_55.sqlite`. The report below is retained as the historical pre-fix record.

Generated while investigating the *Great Rock 'n' Roll Swindle* MBID split. **55 logical albums** are tagged with more than one distinct `album_mbid` (same `album_artist / album` text, multiple MBIDs) across their scrobbles.

## Headline

- **15 heavily split** (primary MBID < 90% of plays) — these are the meaningful cases.
- **40 minor splits** (primary ≥ 90%) — 1–3 stray tags, cosmetic.
- **42** have `album_art` keyed to a *non-primary* MBID (metadata hint is on the minority MBID).

## Important: the user-facing symptom is already fixed

The track-gaps casing-variant fragmentation (the actual *Swindle* symptom) is fixed **globally** by commit `0259bc8` — `get_track_gaps()` now groups by canonical `track_id`, so name-variant twins merge for every album at once. No per-album work is needed for the gaps view.

What remains for these albums is the raw `scrobble.album_mbid` text column carrying two/three values. This is **cosmetic**: the canonical `album_id` already unifies each album, and all views resolve metadata via `album_id` (not `album_mbid`). Normalizing is optional cleanup for clean metadata hints.

## Heavily split albums (primary < 90%)

| Artist | Album | Plays | Split (plays per MBID) |
|---|---|--:|---|
| Bryan Adams | So Far so Good | 2 | 1 (`1dbe4a20`) / 1 (`19a1e0c7`) |
| Edyta Bartosiewicz | Dziś są moje urodziny | 70 | 39 (`ae44efc2`) / 31 (`39e2bd3c`) |
| David Bowie | Heathen | 24 | 14 (`10ebfa03`) / 10 (`fed49206`) |
| Swans | Swans Are Dead | 42 | 25 (`bea14676`) / 17 (`94ba2829`) |
| The Birthday Party | Hee-Haw | 31 | 19 (`3b3c9f6b`) / 12 (`1e412857`) |
| British Sea Power | Open Season | 39 | 24 (`0092af0d`) / 15 (`44e42ad8`) |
| Nick Mason | Profiles | 3 | 2 (`0c1afaaa`) / 1 (`3b6e3b0a`) |
| Suzanne Vega | Solitude Standing | 3 | 2 (`32236c4d`) / 1 (`45f7a49e`) |
| Genesis | ...and Then There Were Three | 62 | 43 (`75459776`) / 19 (`f599ecff`) |
| British Sea Power | Man of Aran | 18 | 13 (`3b52985a`) / 5 (`c2905efd`) |
| Various Artists | Top Gun - Motion Picture Soundtrack | 42 | 33 (`73eae75b`) / 5 (`40a41777`) / 4 (`ea44a36b`) |
| Madness | Full House - the Very Best of Madness | 35 | 30 (`65874c4d`) / 5 (`e8099bcc`) |
| Alphaville | First Harvest 1984-92 | 18 | 16 (`13803aea`) / 2 (`009c67ef`) |
| Perfect | Symfonicznie - Platinum | 9 | 8 (`b3408a12`) / 1 (`3fe19165`) |
| Robert Gawliński | Największe przeboje | 9 | 8 (`9ba4b674`) / 1 (`0cde9181`) |

## All split albums (sorted by plays)

| # | Artist | Album | MBIDs | Plays | Primary | art | trk |
|--:|---|---|--:|--:|---|:--:|:--:|
| 1 | Hey | Fire | 2 | 435 | 432/435 (99%) | ✓ | ✓ |
| 2 | Hey | CDN | 2 | 427 | 426/427 (100%) | ✓ | ✓ |
| 3 | Various Artists | 22 Polish Punk Classics | 2 | 336 | 317/336 (94%) | · | · |
| 4 | Pearl Jam | rearviewmirror (greatest hits 1991-2003) | 2 | 327 | 326/327 (100%) | ✓ | ✓ |
| 5 | Pink Floyd | Echoes - the Best of Pink Floyd | 3 | 309 | 307/309 (99%) | ✓ | ✓ |
| 6 | Ultravox | The Collection | 2 | 278 | 277/278 (100%) | ✓ | ✓ |
| 7 | Soundgarden | Superunknown | 2 | 215 | 210/215 (98%) | ✓ | ✓ |
| 8 | Deep Purple | Deepest Purple: the Very Best of Deep Purple | 2 | 184 | 182/184 (99%) | ✓ | ✓ |
| 9 | David Bowie | Best of Bowie | 2 | 179 | 178/179 (99%) | ✓ | ✓ |
| 10 | Phil Collins | The Singles | 2 | 170 | 167/170 (98%) | ✓ | ✓ |
| 11 | The Cure | Boys Don't Cry | 2 | 151 | 150/151 (99%) | ✓ | ✓ |
| 12 | David Bowie | Let's Dance | 2 | 134 | 130/134 (97%) | ✓ | ✓ |
| 13 | David Bowie | The Rise and Fall of Ziggy Stardust and the Spiders from Mars | 2 | 123 | 120/123 (98%) | ✓ | ✓ |
| 14 | Myslovitz | Z rozmyślań przy śniadaniu | 2 | 121 | 109/121 (90%) | ✓ | ✓ |
| 15 | Hey | [Sic!] | 2 | 108 | 105/108 (97%) | ✓ | ✓ |
| 16 | Pixies | Surfer Rosa | 2 | 102 | 101/102 (99%) | ✓ | ✓ |
| 17 | Budka Suflera | Za ostatni grosz | 2 | 101 | 100/101 (99%) | ✓ | ✓ |
| 18 | Hey | Miłość! Uwaga! Ratunku! Pomocy! | 2 | 88 | 86/88 (98%) | ✓ | ✓ |
| 19 | a-ha | Headlines and Deadlines: the Hits of a‐ha | 2 | 88 | 87/88 (99%) | ✓ | · |
| 20 | Edyta Bartosiewicz | Dziś są moje urodziny | 2 | 70 | 39/70 (56%) | ✓ | ✓ |
| 21 | British Sea Power | Do You Like Rock Music | 2 | 64 | 59/64 (92%) | · | ✓ |
| 22 | Genesis | ...and Then There Were Three | 2 | 62 | 43/62 (69%) | ✓ | ✓ |
| 23 | Dezerter | Prawo do bycia Idiotą | 2 | 61 | 59/61 (97%) | ✓ | ✓ |
| 24 | The Clash | The Singles | 2 | 58 | 56/58 (97%) | ✓ | ✓ |
| 25 | Hey | Karma | 2 | 55 | 54/55 (98%) | ✓ | ✓ |
| 26 | U2 | The Best of 1980 - 1990 | 3 | 53 | 51/53 (96%) | ✓ | ✓ |
| 27 | Hey | Hey | 2 | 51 | 50/51 (98%) | ✓ | ✓ |
| 28 | T. Rex | Tanx | 2 | 49 | 48/49 (98%) | ✓ | ✓ |
| 29 | Living Colour | Time's Up | 2 | 44 | 43/44 (98%) | ✓ | ✓ |
| 30 | Pantera | Official Live: 101 Proof | 2 | 42 | 39/42 (93%) | ✓ | ✓ |
| 31 | Swans | Swans Are Dead | 2 | 42 | 25/42 (60%) | ✓ | ✓ |
| 32 | The Beatles | 1 | 2 | 42 | 41/42 (98%) | ✓ | ✓ |
| 33 | Various Artists | Top Gun - Motion Picture Soundtrack | 3 | 42 | 33/42 (79%) | · | · |
| 34 | British Sea Power | Open Season | 2 | 39 | 24/39 (62%) | ✓ | ✓ |
| 35 | Hey | Do Rycerzy, do Szlachty, doo Mieszczan | 2 | 39 | 38/39 (97%) | ✓ | ✓ |
| 36 | Duran Duran | Decade | 2 | 38 | 37/38 (97%) | ✓ | ✓ |
| 37 | Kylie Minogue | Kylie Minogue | 2 | 37 | 36/37 (97%) | ✓ | ✓ |
| 38 | Lenny Kravitz | Best Ballads | 2 | 36 | 35/36 (97%) | ✓ | ✓ |
| 39 | Madness | Full House - the Very Best of Madness | 2 | 35 | 30/35 (86%) | ✓ | ✓ |
| 40 | Various Artists | Kuschel Rock3 | 2 | 34 | 31/34 (91%) | ✓ | · |
| 41 | The Birthday Party | Hee-Haw | 2 | 31 | 19/31 (61%) | ✓ | ✓ |
| 42 | Sex Pistols | Flogging a Dead Horse | 2 | 25 | 24/25 (96%) | ✓ | ✓ |
| 43 | David Bowie | Heathen | 2 | 24 | 14/24 (58%) | ✓ | ✓ |
| 44 | The Beatles | Revolver | 2 | 24 | 23/24 (96%) | ✓ | ✓ |
| 45 | Eagles | The Very Best of the Eagles | 2 | 21 | 20/21 (95%) | ✓ | ✓ |
| 46 | Alphaville | First Harvest 1984-92 | 2 | 18 | 16/18 (89%) | ✓ | ✓ |
| 47 | British Sea Power | Man of Aran | 2 | 18 | 13/18 (72%) | ✓ | ✓ |
| 48 | Bruce Springsteen | Greatest Hits | 2 | 17 | 16/17 (94%) | ✓ | ✓ |
| 49 | Pixies | Bossanova | 2 | 16 | 15/16 (94%) | ✓ | ✓ |
| 50 | Budka Suflera | Greatest Hits II | 2 | 14 | 13/14 (93%) | ✓ | ✓ |
| 51 | Perfect | Symfonicznie - Platinum | 2 | 9 | 8/9 (89%) | ✓ | ✓ |
| 52 | Robert Gawliński | Największe przeboje | 2 | 9 | 8/9 (89%) | ✓ | ✓ |
| 53 | Nick Mason | Profiles | 2 | 3 | 2/3 (67%) | ✓ | ✓ |
| 54 | Suzanne Vega | Solitude Standing | 2 | 3 | 2/3 (67%) | ✓ | ✓ |
| 55 | Bryan Adams | So Far so Good | 2 | 2 | 1/2 (50%) | ✓ | ✓ |

## To normalize one (optional)
Repoint minority-MBID scrobbles to the primary, scoped by album name (a single MBID string can span multiple albums — see the *Swindle* + *Flogging a Dead Horse* case). Back up first:

```sql
UPDATE scrobble   SET album_mbid='<PRIMARY>' WHERE album_mbid='<MINORITY>' AND album='<album>';
UPDATE album_art  SET album_mbid='<PRIMARY>' WHERE album_mbid='<MINORITY>' AND album='<album>';
```
