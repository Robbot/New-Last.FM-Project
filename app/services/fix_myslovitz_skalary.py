#!/usr/bin/env python3
"""
Normalize track titles for the Myslovitz album "Skalary Mieczyki Neonki".

Symptom: several tracks on the album track listing show 0 (or too few) plays,
and track names are inconsistent (cz.1 vs Cz.2 vs Cz 3, "Sean Penn Song" vs
"Sean Penn Song!", "Nr 9" vs "Nr. 9", "Marie Minn Restaurant" vs the typo
"Marie Minn Restourant").

Root cause: play counts join scrobble.track_id = album_tracks.track_id (scoped by
album_id). Six tracks were split across multiple canonical track entities — the
album_tracks rows point at empty entities (0 scrobbles) created when the tracklist
was first fetched, while the scrobbles resolved to OTHER entities. Different
track_id -> 0 or under-counted plays. Plus name variants (case, punctuation,
spacing, typos) never got merged.

This script consolidates each track onto ONE canonical entity and sets a single
canonical title (DB-album style: title case, no commas, "Cz. N"), in one
transaction:

  1. For each orphan entity, merge it into its canonical target:
       - move its scrobbles (scrobble.track_id -> target)
       - repoint the album_tracks tracklist row that referenced it (-> target)
       - copy its alias norm_titles onto the target, then drop the orphan alias
  2. Set the canonical title on every surviving target entity AND its tracklist row.
  3. Delete the now-unreferenced orphan track entities.
  4. Set the album entity's MBID (it was NULL while scrobbles/art/tracklist carry it).

Canonical titles follow the album's existing DB naming (title case, no commas),
NOT MusicBrainz's lowercase/commas/"część" form — chosen for consistency with how
the album "Skalary Mieczyki Neonki" itself is stored. Scrobble row text is left
untouched (aggregation is by track_id; the tracklist + canonical track.title are
what the album page displays).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.fix_myslovitz_skalary --dry-run
    python -m app.services.fix_myslovitz_skalary
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Myslovitz"
ARTIST_ID = 887
ALBUM = "Skalary Mieczyki Neonki"
ALBUM_ID = 560
ALBUM_MBID = "3bce1ab7-17e9-481b-9b76-f3261c66cb23"

# canonical title per surviving target track_id  (DB-album style)
CANON_TITLES = {
    20330: "Skalary Mieczyki Neonki Cz. 1",
    20331: "Theme from Road Movie",
    20332: "Man on the Machine",
    20333: "Życie to surfing",
    20334: "Isn't Anything",
    20335: "Beastie Fish",
    20336: "W sieci",
    20337: "Skalary Mieczyki Neonki Cz. 2",
    20338: "Nr 9",
    2273:  "Czerwony Notes Błękitny Prochowiec",
    28203: "Death of the Cocaine Dancer",
    28204: "Sean Penn Song!",
    25221: "Skalary Mieczyki Neonki Cz. 3",
    31182: "Marie Minn Restaurant",
}

# orphan track_id -> canonical target track_id
MERGES = {
    31178: 20330,   # "cz.1" tracklist row      -> Cz. 1
    31179: 20337,   # "Cz.2" tracklist row      -> Cz. 2
    28201: 20337,   # "Cz 2"  scrobble variant  -> Cz. 2
    28202: 20338,   # "Nr 9"  tracklist row     -> "Nr. 9" entity
    31180: 28204,   # "Sean Penn Song!" tracklist row -> "Sean Penn Song" entity
    31181: 25221,   # "Cz.3" tracklist row      -> Cz. 3
    47893: 25221,   # "cz. 3" scrobble variant  -> Cz. 3
    28205: 31182,   # "Marie Minn Restourant" typo -> Marie Minn Restaurant
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


def _run(conn: sqlite3.Connection, dirty_run: bool) -> int:
    dry_run = dirty_run
    orphans = list(MERGES.keys())
    orphans_sql = ",".join("?" for _ in orphans)

    print("=" * 72)
    print(f"Myslovitz '{ALBUM}' track normalization  ({'DRY RUN' if dry_run else 'APPLY'})")
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
    # count targets whose title differs from canonical
    title_mismatches = sum(
        1 for tid, title in CANON_TITLES.items()
        if (conn.execute("SELECT title FROM track WHERE track_id=?", (tid,)).fetchone() or [None])[0] != title
    )
    album_mbid_missing = _count(
        conn, "SELECT COUNT(*) FROM album WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (ALBUM_ID, ALBUM_MBID),
    )
    print(f"[pre] scrobbles sitting on orphan track entities: {scrobbles_on_orphans}")
    print(f"[pre] orphan track entities to delete: {orphan_entities}")
    print(f"[pre] tracklist rows pointing at orphans: {tracklist_on_orphans}")
    print(f"[pre] target titles not yet canonical: {title_mismatches}")
    print(f"[pre] album entity mbid missing/wrong: {album_mbid_missing}")

    if (scrobbles_on_orphans == 0 and orphan_entities == 0 and tracklist_on_orphans == 0
            and title_mismatches == 0 and album_mbid_missing == 0):
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

    # --- Step 2: canonical titles on targets + tracklist rows ---------------
    print("\n[2/4] Setting canonical titles")
    for tid, title in CANON_TITLES.items():
        ct = conn.execute(
            "UPDATE track SET title=? WHERE track_id=? AND title != ?", (title, tid, title),
        ).rowcount
        at = conn.execute(
            "UPDATE album_tracks SET track=? WHERE album_id=? AND track_id=? AND track != ?",
            (title, ALBUM_ID, tid, title),
        ).rowcount
        if ct or at:
            print(f"      track_id {tid} -> {title!r}: track.title set={ct}, tracklist text set={at}")

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
        SELECT at.track_number, at.track AS track_name, at.track_id,
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
    print(f"  total plays: {total} (expect 33)")
    print(f"  orphan track entities remaining: "
          f"{_count(conn, f'SELECT COUNT(*) FROM track WHERE track_id IN ({orphans_sql})', orphans)} (expect 0)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Normalize Myslovitz 'Skalary Mieczyki Neonki' track titles + entities"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
