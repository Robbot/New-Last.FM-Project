#!/usr/bin/env python3
"""
Normalize tracks 7 & 12 of the Big Cyc album "Miłość, muzyka, mordobicie".

Symptom: on the album page, tracks 7 ("Villago ...") and 12 ("Buntownik ...
aerozolu") show 0 plays even though they were scrobbled.

Root cause: play counts join scrobble.track_id = album_tracks.track_id (scoped by
album_id). The Last.fm album tracklist names ("Villago, Villago" /
"Buntownik w aerozolu") differ from how the tracks were actually scrobbled
("Villago villago" / "Buntownik z aerozolu"). When the tracklist rows were first
fetched, each variant name resolved to its OWN canonical track entity, so the
two tracklist rows point at empty orphan entities (0 scrobbles) while the
scrobbles resolved to different entities. Different track_id -> 0 plays.

Authoritative check: the MusicBrainz release 42bfb8d0 lists the recordings as
"Villago villago" (9a9236fd...) and "Buntownik z aerozolu" (45f9298f...) — these
match the scrobbled names AND their track_mbids exactly. So the SCROBBLES are
correct; the tracklist is the wrong side. Per the chosen fix, the tracklist rows
(and their orphan entities) are folded onto the scrobble-correct entities with
MusicBrainz titles. Scrobble row text is left untouched.

In one transaction:
  1. Repoint each orphan album_tracks row onto its canonical target entity, copy
     the orphan's alias norm_title onto the target, then drop the orphan alias.
  2. Set the canonical (MusicBrainz) title on the surviving target entity and its
     tracklist row, plus backfill the recording MBID on the tracklist row.
  3. Delete the now-unreferenced orphan track entities.
  4. Set the album entity's MBID (NULL while scrobbles/art/tracklist carry it).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_big_cyc_mordobicie_tracklist --dry-run
    python -m app.services.fix_big_cyc_mordobicie_tracklist
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Big Cyc"
ARTIST_ID = 146
ALBUM = "Miłość, muzyka, mordobicie"
ALBUM_ID = 105
ALBUM_MBID = "42bfb8d0-6a78-4003-9f71-7e1811d2ad03"

# orphan track_id -> canonical target track_id (the entity the scrobbles sit on)
MERGES = {
    36331: 47918,   # "Villago, Villago" tracklist row -> "Villago villago"
    36336: 47919,   # "Buntownik w aerozolu" tracklist row -> "Buntownik z aerozolu"
}

# canonical (MusicBrainz) title + recording MBID per surviving target track_id
CANON = {
    47918: ("Villago villago", "9a9236fd-bc77-477a-a2c8-1ddb1bc82a32"),
    47919: ("Buntownik z aerozolu", "45f9298f-1b84-43db-b158-09a7bb347d25"),
}

EXPECTED_TOTAL_PLAYS = 19


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
    orphans = list(MERGES.keys())
    orphans_sql = ",".join("?" for _ in orphans)

    print("=" * 72)
    print(f"Big Cyc '{ALBUM}' track normalization  ({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scrobbles_on_orphans = _count(
        conn, f"SELECT COUNT(*) FROM scrobble WHERE track_id IN ({orphans_sql})", orphans,
    )
    orphan_entities = _count(
        conn, f"SELECT COUNT(*) FROM track WHERE track_id IN ({orphans_sql})", orphans,
    )
    tracklist_on_orphans = _count(
        conn, f"SELECT COUNT(*) FROM album_tracks WHERE album_id=? AND track_id IN ({orphans_sql})",
        [ALBUM_ID, *orphans],
    )
    title_or_mbid_dirty = sum(
        1 for tid, (title, mbid) in CANON.items()
        if (conn.execute("SELECT title FROM track WHERE track_id=?", (tid,)).fetchone() or [None])[0] != title
        or _count(
            conn,
            "SELECT COUNT(*) FROM album_tracks WHERE album_id=? AND track_id=? "
            "AND (track != ? OR track_mbid IS NULL OR track_mbid != ?)",
            (ALBUM_ID, tid, title, mbid),
        )
    )
    album_mbid_missing = _count(
        conn, "SELECT COUNT(*) FROM album WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (ALBUM_ID, ALBUM_MBID),
    )
    print(f"[pre] scrobbles sitting on orphan track entities: {scrobbles_on_orphans}")
    print(f"[pre] orphan track entities to delete: {orphan_entities}")
    print(f"[pre] tracklist rows pointing at orphans: {tracklist_on_orphans}")
    print(f"[pre] targets with non-canonical title/tracklist/mbid: {title_or_mbid_dirty}")
    print(f"[pre] album entity mbid missing/wrong: {album_mbid_missing}")

    if (scrobbles_on_orphans == 0 and orphan_entities == 0 and tracklist_on_orphans == 0
            and title_or_mbid_dirty == 0 and album_mbid_missing == 0):
        print("[pre] Nothing to do — already normalized (idempotent no-op).")
        return 0

    # --- Step 1: merge each orphan into its target --------------------------
    print("\n[1/4] Merging orphan track entities into canonical targets")
    total_moved = 0
    total_repointed = 0
    for orphan, target in MERGES.items():
        moved = conn.execute(
            "UPDATE scrobble SET track_id=? WHERE track_id=?", (target, orphan),
        ).rowcount
        repointed = conn.execute(
            "UPDATE album_tracks SET track_id=? WHERE album_id=? AND track_id=?",
            (target, ALBUM_ID, orphan),
        ).rowcount
        # Move orphan's aliases onto target. Read -> delete -> re-insert: the
        # orphan's own alias row shares PK (artist_id, norm_title) with the copy,
        # so it must be deleted before the INSERT OR IGNORE or the copy is skipped.
        orphan_aliases = conn.execute(
            "SELECT artist_id, norm_title FROM track_alias WHERE track_id=?", (orphan,),
        ).fetchall()
        dropped = conn.execute(
            "DELETE FROM track_alias WHERE track_id=?", (orphan,),
        ).rowcount
        copied = 0
        for a in orphan_aliases:
            copied += conn.execute(
                "INSERT OR IGNORE INTO track_alias (artist_id, norm_title, track_id) VALUES (?,?,?)",
                (a["artist_id"], a["norm_title"], target),
            ).rowcount
        print(f"      {orphan} -> {target}: scrobbles moved={moved}, "
              f"tracklist repointed={repointed}, aliases copied={copied}/dropped={dropped}")
        total_moved += moved
        total_repointed += repointed
    print(f"      totals: scrobbles moved={total_moved}, tracklist rows repointed={total_repointed}")

    # --- Step 2: canonical title + recording MBID on targets + tracklist -----
    print("\n[2/4] Setting canonical titles + recording MBIDs")
    for tid, (title, mbid) in CANON.items():
        ct = conn.execute(
            "UPDATE track SET title=? WHERE track_id=? AND title != ?", (title, tid, title),
        ).rowcount
        at = conn.execute(
            "UPDATE album_tracks SET track=?, track_mbid=? "
            "WHERE album_id=? AND track_id=? AND (track != ? OR track_mbid IS NULL OR track_mbid != ?)",
            (title, mbid, ALBUM_ID, tid, title, mbid),
        ).rowcount
        print(f"      track_id {tid} -> {title!r} (mbid {mbid}): "
              f"track.title set={ct}, tracklist updated={at}")

    # --- Step 3: delete orphan track entities -------------------------------
    print("\n[3/4] Deleting orphan track entities")
    for orphan in orphans:
        refs = (_count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (orphan,))
                + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (orphan,))
                + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (orphan,)))
        if refs == 0:
            conn.execute("DELETE FROM track WHERE track_id=?", (orphan,))
            print(f"      deleted track entity {orphan}")
        else:
            print(f"      !! kept {orphan}: still {refs} reference(s)")

    # --- Step 4: set album entity MBID --------------------------------------
    print("\n[4/4] Setting album entity MBID")
    cur = conn.execute(
        "UPDATE album SET mbid=? WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (ALBUM_MBID, ALBUM_ID, ALBUM_MBID),
    )
    print(f"      album {ALBUM_ID} mbid -> {ALBUM_MBID}: {cur.rowcount} row(s)")

    # --- commit or rollback -------------------------------------------------
    if dry_run:
        print("\n[DRY RUN] No changes committed. Rolling back.")
        conn.rollback()
    else:
        conn.commit()
        print("\n[APPLY] Changes committed.")

    # --- post-state: same join the album page uses --------------------------
    print("\n--- post-state (album page join: album_tracks <-> scrobble on track_id+album_id) ---")
    rows = conn.execute(
        """
        SELECT at.track_number, at.track AS track_name, at.track_id, at.track_mbid,
               COUNT(s.id) AS plays
        FROM album_tracks at
        LEFT JOIN scrobble s ON s.track_id = at.track_id AND s.album_id = at.album_id
        WHERE at.album_id = ?
        GROUP BY at.track_id, at.track_number, at.track
        ORDER BY at.track_number
        """,
        (ALBUM_ID,),
    ).fetchall()
    total = 0
    for r in rows:
        total += r["plays"]
        flag = "  <-- 0 plays" if r["plays"] == 0 else ""
        print(f"  #{r['track_number']:>2}  {r['plays']:>2} plays  tid={r['track_id']:>6}  {r['track_name']!r}{flag}")
    print(f"  total plays: {total} (expect {EXPECTED_TOTAL_PLAYS})")
    print(f"  orphan track entities remaining: "
          f"{_count(conn, f'SELECT COUNT(*) FROM track WHERE track_id IN ({orphans_sql})', orphans)} (expect 0)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Big Cyc 'Miłość, muzyka, mordobicie' tracks 7 & 12 to MB titles"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
