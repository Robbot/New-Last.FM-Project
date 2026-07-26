#!/usr/bin/env python3
"""
Consolidate Cool Kids of Death "English Version" + "Cool Kids of Death (eng ver)"
into the canonical MusicBrainz release "Cool Kids Of Death (International Version)".

These three album names are the same release, currently split across the scrobble
table. This script merges them in one transaction:

  1. Rename the 9 wrong (Spotify/csv title-case) track titles on the 12
     csv_import scrobbles to the canonical Last.fm tracklist names, repointing
     the 4 that have separate canonical track entities.
  2. Move all 44 source scrobbles to the canonical album text + album_mbid +
     album_id + album_artist (all four together, or the move is partly
     invisible).
  3. Re-key the album_tracks tracklist (11 rows) to the canonical album.
  4. Rename the album_art cover row (1 row) to the canonical album.
  5. Repurpose canonical album entity 2925 ("English Version") as the canonical
     album, add the source-name aliases, and delete the merged "eng ver" entity
     3475 once nothing references it.
  6. Light-touch: rename album text in spotify_track_cache if any rows exist.

Scoped strictly by artist + source album NAME (never by album_mbid alone — one
MBID string can legitimately span multiple albums). Idempotent: re-running is a
no-op because the WHERE clauses no longer match.

The Polish self-titled "Cool Kids of Death" (MBID ca2ebaf2…) is never touched.

Usage:
    python -m app.services.fix_ckod_international_version --dry-run
    python -m app.services.fix_ckod_international_version
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

# --- Canonical target -------------------------------------------------------
ARTIST = "Cool Kids of Death"
NEW_ALBUM = "Cool Kids Of Death (International Version)"
NEW_MBID = "aa120f80-e4b4-4c88-9605-5b41652261ca"
NEW_ALBUM_ID = 2925          # repurpose the existing "English Version" entity
CKOD_ARTIST_ID = 268
SRCS = ["English Version", "Cool Kids of Death (eng ver)"]
CSV_ALBUM = "Cool Kids of Death (eng ver)"   # source of the wrong-title scrobbles
MERGE_ALBUM_ID = 3475        # the "eng ver" canonical entity to delete after merge

# --- Track-title corrections (wrong Spotify/csv title -> canonical) ---------
# value = (canonical track text, canonical track_id)
TRACK_FIXES = {
    "Stones and Bottled Filled with Petrol": ("Stones and bottles filled with petrol", 16301),
    "Twenty and Than Some":                   ("Twenty and Than Same",                   16304),
    "It's Not Worse":                         ("It's not worth",                         16307),
    "Disorder":                               ("Disorder (with Procesor Plus)",          16309),
    "Dead Disco":                             ("Dead disco",                             16310),
    "Generation Nothing":                     ("Generation nothing",                     16303),
    "It Never Happens to Us":                 ("It never happens to us",                 16305),
    "Look Out":                               ("Look out",                               16308),
    "The Salvation Army":                     ("The salvation army",                     16302),
    # "Cool Kids of Death" (id 6632) and "Illegal" (id 16306) are already
    # canonical — no correction needed.
}


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if not db_path.exists():
        raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")
    return str(db_path)


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _count(conn, sql, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, dry_run: bool) -> int:
    print("=" * 72)
    print(f"CKOD International Version consolidation  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state snapshot --------------------------------------------------
    src_scrobble = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE artist=? AND album IN (?,?)",
        (ARTIST, SRCS[0], SRCS[1]),
    )
    print(f"[pre] source scrobbles to move: {src_scrobble}")
    csv_rows = conn.execute(
        "SELECT DISTINCT track FROM scrobble WHERE artist=? AND album=?",
        (ARTIST, CSV_ALBUM),
    ).fetchall()
    print(f"[pre] distinct tracks on '{CSV_ALBUM}': {len(csv_rows)}")

    if src_scrobble == 0:
        print("[pre] No source scrobbles found — already consolidated (idempotent no-op).")
        return 0

    # --- Step 1: track-title + track_id correction (before album rename) ----
    print("\n[1/6] Correcting wrong track titles on csv scrobbles")
    track_fixed = 0
    for wrong, (canonical, canonical_id) in TRACK_FIXES.items():
        cur = conn.execute(
            "UPDATE scrobble SET track=?, track_id=? "
            "WHERE artist=? AND album=? AND track=?",
            (canonical, canonical_id, ARTIST, CSV_ALBUM, wrong),
        )
        if cur.rowcount:
            print(f"      {wrong!r} -> {canonical!r} (track_id -> {canonical_id}): {cur.rowcount} row(s)")
            track_fixed += cur.rowcount
    print(f"      total track rows corrected: {track_fixed}")

    # --- Step 2: move scrobbles to canonical album --------------------------
    print("\n[2/6] Moving source scrobbles to canonical album")
    cur = conn.execute(
        "UPDATE scrobble "
        "SET album=?, album_mbid=?, album_id=?, album_artist=? "
        "WHERE artist=? AND album IN (?,?)",
        (NEW_ALBUM, NEW_MBID, NEW_ALBUM_ID, ARTIST, ARTIST, SRCS[0], SRCS[1]),
    )
    moved = cur.rowcount
    print(f"      moved {moved} scrobble(s) -> {NEW_ALBUM!r} (mbid {NEW_MBID}, album_id {NEW_ALBUM_ID})")

    # --- Step 3: album_tracks tracklist -------------------------------------
    print("\n[3/6] Re-keying album_tracks tracklist")
    cur = conn.execute(
        "UPDATE album_tracks "
        "SET album=?, album_mbid=?, album_id=? "
        "WHERE artist=? AND album=?",
        (NEW_ALBUM, NEW_MBID, NEW_ALBUM_ID, ARTIST, "English Version"),
    )
    print(f"      album_tracks rows updated: {cur.rowcount}")

    # --- Step 4: album_art cover -------------------------------------------
    print("\n[4/6] Renaming album_art cover row")
    cur = conn.execute(
        "UPDATE album_art SET album=?, album_mbid=? WHERE artist=? AND album=?",
        (NEW_ALBUM, NEW_MBID, ARTIST, "English Version"),
    )
    print(f"      album_art rows updated: {cur.rowcount}")

    # --- Step 5: canonical entity tables ------------------------------------
    print("\n[5/6] Canonical album entity + aliases")
    conn.execute(
        "UPDATE album SET title=?, mbid=? WHERE album_id=?",
        (NEW_ALBUM, NEW_MBID, NEW_ALBUM_ID),
    )
    print(f"      album entity {NEW_ALBUM_ID} -> title={NEW_ALBUM!r}, mbid={NEW_MBID}")

    # aliases (norm_title) for the owner -> canonical id, idempotent
    for alias in ("english version",
                  "cool kids of death international version",
                  "cool kids of death eng ver"):
        conn.execute(
            "INSERT OR IGNORE INTO album_alias (artist_id, norm_title, album_id) VALUES (?,?,?)",
            (CKOD_ARTIST_ID, alias, NEW_ALBUM_ID),
        )
    print(f"      aliases for artist_id={CKOD_ARTIST_ID} -> album_id={NEW_ALBUM_ID} ensured")

    # delete the merged "eng ver" entity 3475 once nothing references it
    refs = sum(
        _count(conn, f"SELECT COUNT(*) FROM {t} WHERE album_id=?", (MERGE_ALBUM_ID,))
        for t in ("scrobble", "album_tracks", "album_art")
    )
    if refs == 0:
        conn.execute("DELETE FROM album_alias WHERE album_id=?", (MERGE_ALBUM_ID,))
        conn.execute("DELETE FROM album WHERE album_id=?", (MERGE_ALBUM_ID,))
        print(f"      deleted merged album entity {MERGE_ALBUM_ID} + its alias (0 refs)")
    else:
        print(f"      !! kept album entity {MERGE_ALBUM_ID}: still {refs} reference(s)")

    # --- Step 6: light-touch caches ----------------------------------------
    print("\n[6/6] Light-touch cache rename (spotify_track_cache)")
    cur = conn.execute(
        "UPDATE spotify_track_cache SET album=? WHERE artist=? AND album IN (?,?)",
        (NEW_ALBUM, ARTIST, SRCS[0], SRCS[1]),
    )
    print(f"      spotify_track_cache rows updated: {cur.rowcount}")
    print("      (musicbrainz_releases left untouched — regenerable cache; "
          "note its row carries a conflicting synthetic mbid)")

    # --- commit or rollback --------------------------------------------------
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")

    # --- post-state (reads see committed or rolled-back state) --------------
    print("\n--- post-state ---")
    print(f"  scrobbles under old names : {_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE artist=? AND album IN (?,?)', (ARTIST, SRCS[0], SRCS[1]))} (expect 0)")
    new = conn.execute(
        "SELECT album_mbid, album_id, COUNT(*) FROM scrobble WHERE artist=? AND album=? GROUP BY album_mbid, album_id",
        (ARTIST, NEW_ALBUM),
    ).fetchone()
    print(f"  scrobbles under new name  : {dict(new) if new else 'NONE'} (expect 44, mbid {NEW_MBID}, id {NEW_ALBUM_ID})")
    distinct = _count(
        conn,
        "SELECT COUNT(DISTINCT track) FROM scrobble WHERE artist=? AND album=?",
        (ARTIST, NEW_ALBUM),
    )
    print(f"  distinct tracks on new    : {distinct} (expect 11)")
    pl = _count(
        conn,
        "SELECT COUNT(*) FROM scrobble WHERE artist=? AND album=?",
        (ARTIST, "Cool Kids of Death"),
    )
    print(f"  Polish self-titled intact: {pl} scrobbles (unchanged)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consolidate Cool Kids of Death English Version -> International Version"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
