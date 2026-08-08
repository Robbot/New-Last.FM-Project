#!/usr/bin/env python3
"""
Fold the Foreigner box-set "The Complete Atlantic Studio Albums 1977" into its
canonical title "The Complete Atlantic Studio Albums 1977 - 1991". Re-runnable.

Symptom: one release is split across two canonical album entities.
"The Complete Atlantic Studio Albums 1977" (album_id 4085, MBID NULL, 16
scrobbles) is the truncated Spotify/Last.fm tag for the box set
"The Complete Atlantic Studio Albums 1977 - 1991" (album_id 1827, MBID
595d4eee, 228 scrobbles). They are one release, so the 16 truncated scrobbles
belong on the canonical album.

Root cause (recurrence): during sync the album name passes through clean_title()
-> clean_remastered_suffix() BEFORE the album-name mapping is applied. The
bare-year pattern " -\\s+\\d{4}\\s*$" strips " - 1991" from the canonical title,
so even a correctly-tagged scrobble collapses to "The Complete Atlantic Studio
Albums 1977" (the 16 strays likely arrived as that short tag with no MBID). A
matching album_name_mappings.json entry now restores the year range at ingest
(the "Best 1991" -> "Best 1991 - 2004" precedent). This script is the one-time
cleanup of the strays already in the database.

The tracks already share canonical entities: every short-tag scrobble track_id
also appears on canonical album scrobbles AND in the canonical album_tracks
(79 rows), so this is a pure album-side fold — NO track-entity merging needed.

In one transaction:
  1. scrobble (16 rows): album text -> canonical, album_mbid -> 595d4eee,
     album_id -> 1827, album_artist -> "Foreigner".
     (track text/track_id/track_mbid unchanged — already correct)
  2. album_alias: repoint the variant alias (norm
     "the complete atlantic studio albums 1977") 4085 -> 1827 (idempotent),
     so any future short-tag scrobble resolves to canonical.
  3. album_art: delete the orphan src row (artist+album match).
  4. album entity: set canonical 1827's mbid (NULL today); delete orphan 4085.
     (No album_tracks to delete — src had none; canonical's 79 rows cover them.)

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_foreigner_atlantic_boxset --dry-run
    python -m app.services.fix_foreigner_atlantic_boxset
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Foreigner"
ARTIST_ID = 442

SRC_ALBUM = "The Complete Atlantic Studio Albums 1977"
SRC_ALBUM_ID = 4085
SRC_MBID = None  # the truncated scrobbles carry no MBID

DST_ALBUM = "The Complete Atlantic Studio Albums 1977 - 1991"
DST_ALBUM_ID = 1827
DST_MBID = "595d4eee-d949-4d5e-bef8-8aeffdb7ca28"

# Joinable play count grows over time as the user listens, and 2 pre-existing
# canonical scrobbles ("Tramontane - Instrumental", track_id 10062) don't join
# the tracklist variant ("Tramontane (Instrumental)", track_id 31129) — a
# separate track-entity split, out of scope here. So the total is not asserted;
# move correctness is proven by the moved-count and the "0 stragglers" guards.
EXPECTED_TOTAL_PLAYS = None


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
    # match truncated scrobbles by album_id OR album text (not album_id alone, in
    # case a stray resolved to a different entity before the alias is repointed)
    src_scr_sql = "artist=? AND (album_id=? OR album=?)"
    src_scr_params = (ARTIST, SRC_ALBUM_ID, SRC_ALBUM)

    print("=" * 72)
    print(f"Foreigner box-set fold: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, f"SELECT COUNT(*) FROM scrobble WHERE {src_scr_sql}", src_scr_params)
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE artist=? AND album=?",
                     (ARTIST, SRC_ALBUM))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    dst_mbid_missing = _count(
        conn, "SELECT COUNT(*) FROM album WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_ALBUM_ID, DST_MBID),
    )
    # PK collision check on the rename (src vs existing dst scrobbles)
    collisions = _count(
        conn,
        """
        SELECT COUNT(*) FROM scrobble r
        WHERE r.artist=? AND r.album=?
          AND EXISTS (SELECT 1 FROM scrobble p
                      WHERE p.artist=? AND p.album=? AND p.uts=r.uts AND p.track=r.track)
        """,
        (ARTIST, SRC_ALBUM, ARTIST, DST_ALBUM),
    )
    print(f"[pre] scrobbles under truncated name/id: {scr_src}")
    print(f"[pre] aliases pointing at orphan entity {SRC_ALBUM_ID}: {alias_src}")
    print(f"[pre] src tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] src album_art rows: {art_src}")
    print(f"[pre] orphan album entity {SRC_ALBUM_ID} present: {entity_src}")
    print(f"[pre] dst album mbid missing/wrong: {dst_mbid_missing}")
    print(f"[pre] scrobble PK collisions on rename: {collisions}")

    if collisions:
        print(f"\n[ABORT] {collisions} scrobble PK collision(s) — rename would violate "
              f"UNIQUE(uts,artist,album,track). Investigate before proceeding.")
        conn.rollback()
        return 1

    if (scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
            and entity_src == 0 and dst_mbid_missing == 0):
        print("[pre] Nothing to do — already folded (idempotent no-op).")
        return 0

    # --- Step 1: move scrobbles onto canonical album ------------------------
    print("\n[1/4] Moving truncated scrobbles onto canonical album")
    moved = conn.execute(
        f"UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        f"WHERE {src_scr_sql}",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, *src_scr_params),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: repoint album alias (idempotent) --------------------------
    print("\n[2/4] Repointing album alias -> canonical")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 3: delete orphaned src album_art row -------------------------
    print("\n[3/4] Deleting orphaned src album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")
    # (No src album_tracks rows exist to delete — canonical's 79 cover the songs.)

    # --- Step 4: canonical mbid + delete orphan album entity if present ----
    print("\n[4/4] Setting canonical mbid + dropping orphan album entity")
    set_mbid = conn.execute(
        "UPDATE album SET mbid=? WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_MBID, DST_ALBUM_ID, DST_MBID),
    ).rowcount
    print(f"      canonical album {DST_ALBUM_ID} mbid -> {DST_MBID}: {set_mbid} row(s)")
    if entity_src:
        remaining_refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
                          + _count(conn, "SELECT COUNT(*) FROM track WHERE album_id=?", (SRC_ALBUM_ID,)))
        if remaining_refs == 0:
            del_ent = conn.execute("DELETE FROM album WHERE album_id=?", (SRC_ALBUM_ID,)).rowcount
            print(f"      deleted orphan album entity {SRC_ALBUM_ID}: {del_ent} row(s)")
        else:
            print(f"      !! kept album entity {SRC_ALBUM_ID}: still {remaining_refs} reference(s)")

    # --- post-state: same join the album page uses --------------------------
    # Printed while the transaction is still open so the numbers reflect the
    # would-be result in BOTH dry-run and apply modes (dry-run rolls back after).
    print("\n--- post-state (album page join: album_tracks <-> scrobble on track_id+album_id) ---")
    rows = conn.execute(
        """
        SELECT at.track_number, at.track AS track_name, at.track_id,
               COUNT(s.id) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble s ON s.track_id = at.track_id AND s.album_id = at.album_id
        WHERE at.album_id = ?
        GROUP BY at.track_id, at.track_number, at.track
        ORDER BY at.track_number
        """,
        (DST_ALBUM_ID,),
    ).fetchall()
    total = 0
    for r in rows:
        total += r["plays"]
        flag = "  <-- 0 plays" if r["plays"] == 0 else ""
        print(f"  #{r['track_number']:>2}  {r['plays']:>2} plays  tid={r['track_id']:>6}  {r['track_name']!r}{flag}")
    expect_note = f" (expect {EXPECTED_TOTAL_PLAYS})" if EXPECTED_TOTAL_PLAYS is not None else ""
    print(f"  total plays: {total}{expect_note}")
    print(f"  src album entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM album WHERE album_id=?', (SRC_ALBUM_ID,))} (expect 0)")
    print(f"  scrobbles still under src name: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album=?', (SRC_ALBUM,))} (expect 0)")

    # --- commit or rollback (after post-state so dry-run verifies the result) -
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fold Foreigner 'The Complete Atlantic Studio Albums 1977' -> '...1977 - 1991'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
