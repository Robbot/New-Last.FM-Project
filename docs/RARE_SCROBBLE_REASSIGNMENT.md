# Rare scrobble reassignment

Use `app.services.reassign_rare_scrobble` when a small number of incorrectly
identified scrobbles need to become tracks that already exist in the library.
The procedure deliberately targets the immutable scrobble ID, not the old
artist or title, so similarly named plays are not changed accidentally.

## Procedure

1. Locate the exact scrobble and record its `id`, timestamp, and current
   identity fields.
2. Confirm that the destination artist, album, and track already exist in
   `artist`, `album`, and `album_tracks`.
3. Confirm that the destination resolves to exactly one row and supplies an
   artist MBID, album MBID, track MBID, and all three entity IDs.
4. Check that changing the artist and track will not collide with another
   scrobble at the same timestamp.
5. Back up the database:

   ```bash
   .venv/bin/python -m app.services.backup_db
   ```

6. Preview the complete field replacement. Dry run is the default:

   ```bash
   .venv/bin/python -m app.services.reassign_rare_scrobble \
     --scrobble-id SCROBBLE_ID \
     --artist "Canonical artist" \
     --album "Canonical album" \
     --track "Canonical track"
   ```

7. Review the printed before/destination values, then repeat with `--apply`:

   ```bash
   .venv/bin/python -m app.services.reassign_rare_scrobble \
     --scrobble-id SCROBBLE_ID \
     --artist "Canonical artist" \
     --album "Canonical album" \
     --track "Canonical track" \
     --apply
   ```

8. Verify the stored row, album play count, absence of the old identity, and
   `PRAGMA integrity_check`.

The reassignment does not automatically delete the old artist, album, track,
or aliases. They may still describe legitimate music even when this particular
play was misidentified. Review zero-reference entities separately and remove
them only when the user explicitly wants that cleanup.

The command copies `artist`, `artist_mbid`, `album_artist`, `album`,
`album_mbid`, `track`, `track_mbid`, `artist_id`, `album_id`, and `track_id`
from the existing canonical records. It aborts if the destination is missing
or ambiguous, any required MBID is unavailable, or the reassignment would
violate scrobble uniqueness.
