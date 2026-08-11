#!/usr/bin/env python3
"""
Fix album_tracks rows that carry a bare remaster-year suffix.

Last.fm tags remastered tracks as "<title> - YYYY" — a bare year with no
"Remastered" word (e.g. "Meccanik Dancing (Oh We Go!) - 2001"). The sync-time
cleaner (clean_remastered_suffix / _REMASTER_PATTERNS) only strips a year when
it's followed by "Remastered"/"Remaster", and the matching normalizer
(_normalize_track_name_for_matching) only strips a bare year when it has a
trailing space (r' - \\d{4} '). So a bare " - YYYY" at end-of-string slips
through into album_tracks.

Consequence: the suffixed name resolves to a PHANTOM track entity distinct
from the clean-name entity the scrobbles use. The album-detail page joins
plays by track_id (s.track_id = at.track_id), so every track on an affected
album shows 0 plays.

This script, per affected row:
  1. Strips the trailing " - <4-digit year>" suffix (restoring the real title).
  2. Re-resolves track_id via the Resolver to the canonical clean-name entity
     (the one scrobbles already use), so play counts match.
  3. With --clean-orphans, deletes the now-unreferenced phantom track entities
     and their aliases.

Dry-run by default; pass --apply to write. Backs up the DB before applying.

Usage:
  # Preview everything that would change:
  python -m app.services.fix_album_track_year_suffix
  # Scope to one album:
  python -m app.services.fix_album_track_year_suffix --artist XTC --album "Go 2"
  # Apply for real (with phantom-entity cleanup):
  python -m app.services.fix_album_track_year_suffix --apply --clean-orphans \
      --artist XTC --album "Go 2"
"""

import argparse
import re
import sys

from app.db.connections import get_db_connection
from app.db.entities import Resolver, lookup_track_id
from app.services.backup_db import checkpoint_wal, create_backup, DB_PATH, BACKUP_DIR

# Trailing bare remaster-year suffix, e.g. " - 2001" at end of title.
_SUFFIX_RE = re.compile(r"\s+-\s*(19|20)\d{2}\s*$")


def find_candidates(conn, artist=None, album=None):
    """Return album_tracks rows whose `track` ends in a bare ' - YYYY' suffix.

    SQLite has no REGEXP builtin, so pre-filter with LIKE ('% - ____' narrows to
    names ending in space-hyphen-space-4-chars) then confirm with the regex.
    """
    where = ["track LIKE '% - ____'"]
    params = []
    if artist:
        where.append("artist = ?")
        params.append(artist)
    if album:
        where.append("album = ?")
        params.append(album)
    sql = (
        "SELECT artist, album, track, track_number, artist_id, album_id, track_id, track_mbid "
        "FROM album_tracks WHERE " + " AND ".join(where) +
        " ORDER BY artist, album, track_number"
    )
    rows = conn.execute(sql, params).fetchall()
    return [r for r in rows if _SUFFIX_RE.search(r["track"])]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--artist", help="Restrict to this artist")
    parser.add_argument("--album", help="Restrict to this album")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write changes (default: dry-run)")
    parser.add_argument("--clean-orphans", action="store_true",
                        help="After applying, delete now-unreferenced phantom track entities")
    args = parser.parse_args(argv)

    conn = get_db_connection()
    rows = find_candidates(conn, args.artist, args.album)

    if not rows:
        print("No album_tracks rows with a bare ' - <year>' suffix found"
              + (f" for {args.artist} / {args.album}." if args.artist or args.album else "."))
        conn.close()
        return 0

    resolver = Resolver(conn)

    # Plan: list of (row, clean_name, new_track_id, old_track_id)
    plan = []
    skipped = []
    for r in rows:
        clean_name = _SUFFIX_RE.sub("", r["track"]).strip()
        if not clean_name:
            skipped.append((r, "empty after stripping suffix"))
            continue
        # Guard: a clean-name row already exists for this (artist, album, track)?
        exists = conn.execute(
            "SELECT 1 FROM album_tracks WHERE artist=? AND album=? AND track=?",
            (r["artist"], r["album"], clean_name),
        ).fetchone()
        if exists:
            skipped.append((r, f"clean row already exists: {clean_name!r}"))
            continue
        # Read-only lookup so dry-run never writes. None => entity doesn't exist
        # yet; --apply will create it (via Resolver) at write time.
        new_id = lookup_track_id(conn, r["artist"], clean_name)
        plan.append((r, clean_name, new_id))

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n=== {mode} — {len(plan)} row(s) to fix, {len(skipped)} skipped ===\n")
    for r, clean_name, new_id in plan:
        new_id_str = str(new_id) if new_id is not None else "(new — created on --apply)"
        unchanged = new_id is not None and new_id == r["track_id"]
        flag = "  (track_id unchanged)" if unchanged else ""
        print(f'  {r["artist"]} / {r["album"]}  #{r["track_number"]}')
        print(f'    - {r["track"]!r}  (track_id {r["track_id"]})')
        print(f'    + {clean_name!r}  (track_id {new_id_str}){flag}')
    for r, reason in skipped:
        print(f'  SKIP {r["track"]!r}: {reason}')

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to write changes.")
        conn.close()
        return 0

    # --- Apply ---
    print("\nBacking up database...")
    checkpoint_wal(DB_PATH)
    backup_path = create_backup(DB_PATH, BACKUP_DIR)
    print(f"  backed up to {backup_path}")

    abandoned_ids = set()
    try:
        cur = conn.cursor()
        for r, clean_name, _looked_up in plan:
            # Resolve (creating the canonical entity if it doesn't exist yet)
            # inside the committed transaction.
            new_id = resolver.resolve_track_id(r["artist_id"], clean_name, r["track_mbid"])
            cur.execute(
                "UPDATE album_tracks SET track=?, track_id=? "
                "WHERE artist=? AND album=? AND track=?",
                (clean_name, new_id, r["artist"], r["album"], r["track"]),
            )
            if r["track_id"] != new_id and r["track_id"] is not None:
                abandoned_ids.add(r["track_id"])
        conn.commit()
        print(f"\nUpdated {len(plan)} row(s).")
    except Exception as e:
        conn.rollback()
        print(f"ERROR applying changes, rolled back: {e}", file=sys.stderr)
        conn.close()
        return 1

    # --- Optional orphan cleanup ---
    if args.clean_orphans and abandoned_ids:
        print(f"\nCleaning {len(abandoned_ids)} orphaned phantom track entity(ies)...")
        removed = 0
        for tid in abandoned_ids:
            # Only delete if nothing references the entity anymore.
            still_in_album_tracks = conn.execute(
                "SELECT 1 FROM album_tracks WHERE track_id=? LIMIT 1", (tid,)
            ).fetchone()
            in_scrobble = conn.execute(
                "SELECT 1 FROM scrobble WHERE track_id=? LIMIT 1", (tid,)
            ).fetchone()
            if still_in_album_tracks or in_scrobble:
                print(f"  kept track_id {tid} (still referenced)")
                continue
            conn.execute("DELETE FROM track_alias WHERE track_id=?", (tid,))
            conn.execute("DELETE FROM track WHERE track_id=?", (tid,))
            removed += 1
        conn.commit()
        print(f"  deleted {removed} orphaned track entity row(s) + aliases.")

    conn.close()
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
