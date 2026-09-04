# Track mismatch resolution

The sync validates each incoming scrobble title against the stored tracklist
for the same artist and album. A mismatch notification is a request for review,
not proof that the scrobble title is wrong: the stored tracklist may instead be
incomplete or represent another release edition.

Run the resolver from the application root. It uses
`files/lastfmstats.sqlite` by default.

## 1. List unique active mismatches

```bash
python -m app.services.resolve_track_mismatch list
```

Repeated notifications are grouped and the newest notification ID is shown.

## 2. Choose one resolution

Map a spelling or unwanted suffix variant to a title that already exists in
the album tracklist:

```bash
python -m app.services.resolve_track_mismatch map NOTIFICATION_ID \
  --to "Canonical track title"
```

Repair an incomplete tracklist by adding the incoming title:

```bash
python -m app.services.resolve_track_mismatch add-to-tracklist NOTIFICATION_ID \
  --track-number 7
```

If a missing track belongs before an existing track, explicitly shift that
track and all later numbers:

```bash
python -m app.services.resolve_track_mismatch add-to-tracklist NOTIFICATION_ID \
  --track-number 1 --shift-existing
```

Accept an intentionally distinct version without adding it to the release
tracklist:

```bash
python -m app.services.resolve_track_mismatch keep NOTIFICATION_ID
```

All three commands are dry runs by default. Read the JSON summary and rerun the
same command with `--apply` only after confirming the decision. Take a current
database backup before applying a production resolution.

## Effects

- `map` updates matching scrobble text and `track_id`, records an album-scoped
  rule for future ingestion, and dismisses duplicate notifications.
- `add-to-tracklist` inserts a relationally linked `album_tracks` row and
  dismisses duplicate notifications.
- `keep` records an album-scoped acceptance that suppresses future validation
  warnings while retaining the incoming title.

The resolver rejects missing canonical targets, occupied track numbers unless
`--shift-existing` is explicit, and scrobble identity collisions. It does not
delete old track entities automatically.
