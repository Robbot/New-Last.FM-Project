#!/usr/bin/env python3
"""
Sort out the Pornography (The Cure) gridlock. Idempotent; --dry-run to preview.

End state:
  - Canonical `Pornography` (album_id 292): album_tracks = the 8 core tracks only.
  - `Pornography (Deluxe Edition)` (album_id 5281): album_tracks = 22 tracks
    (8 core + 14 variants at positions 9-22), keyed to the track entities that
    actually carry the variant scrobbles, so plays link to tracklist rows.
  - Variant scrobbles (currently filed on `Pornography`) are re-routed to Deluxe.
  - The one split variant entity (Figurehead studio demo) is merged.
  - Orphan duplicate track entities left by the old bracket/paren tracklists are dropped.

CAVEAT: the Deluxe tracklist is rebuilt directly here. The normal lazy-fetch path
(still buggy — see project-deluxe-tracklist-collapse memory) will re-collapse it to
~17 rows if the Deluxe album page re-fetches the tracklist. The fetch path needs a
disc-1-first dedupe fix; tracked as a separate follow-up.
"""

import argparse
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
ARTIST = "The Cure"
CANON = "Pornography"
DELUXE = "Pornography (Deluxe Edition)"

# pos -> track_id. Verified against current scrobble data: these are the entities
# that carry the plays (core plays for CORE, variant plays for BONUS).
CORE = [
    (1, 6309), (2, 5724), (3, 1579), (4, 3125),
    (5, 3121), (6, 3119), (7, 3122), (8, 1007),
]
BONUS = [
    (9, 3596), (10, 3597), (11, 3598), (12, 1593),
    (13, 3599), (14, 3600), (15, 8794), (16, 5747),
    (17, 5748), (18, 5749), (19, 5750), (20, 5751),
    (21, 5752), (22, 7522),
]
BONUS_IDS = [tid for _, tid in BONUS]

# Figurehead studio demo is split across two entities: keep the one with the plays.
FIGUREHEAD_KEEP = 1593   # "The Figurehead - Rhino Studio Demo / December 1981" (6 plays)
FIGUREHEAD_MERGE = 44037  # "The Figurehead (studio demo)" (1 play, on Deluxe)

# Duplicate variant entities created by the old bracket/paren tracklist pulls.
# 44037 is merged above; the rest become orphans after the rebuild.
ORPHAN_CANDIDATES = [
    44034, 44035, 44036, 44038, 44039, 44040, 44041, 44042,
    44043, 44044, 44045, 44046, 47785, 47786, 47787, 47788, 47789, 47790,
]


def log(msg):
    print(msg)


def fetch_ids(conn):
    artist_id = conn.execute("SELECT artist_id FROM artist WHERE name=?", (ARTIST,)).fetchone()[0]
    canon_id = conn.execute(
        "SELECT album_id FROM album WHERE artist_id=? AND title=?", (artist_id, CANON)
    ).fetchone()[0]
    deluxe_id = conn.execute(
        "SELECT album_id FROM album WHERE artist_id=? AND title=?", (artist_id, DELUXE)
    ).fetchone()[0]
    deluxe_mbid = conn.execute("SELECT mbid FROM album WHERE album_id=?", (deluxe_id,)).fetchone()[0]
    return artist_id, canon_id, deluxe_id, deluxe_mbid


def title_of(conn, track_id):
    row = conn.execute("SELECT title FROM track WHERE track_id=?", (track_id,)).fetchone()
    return row[0] if row else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    artist_id, canon_id, deluxe_id, deluxe_mbid = fetch_ids(conn)
    log(f"artist_id={artist_id}  canon album_id={canon_id}  deluxe album_id={deluxe_id}  deluxe_mbid={deluxe_mbid}")
    log(f"mode: {'DRY RUN' if args.dry_run else 'APPLY'}")
    log("")

    try:
        # --- Step 1: merge Figurehead studio-demo entity (44037 -> 1593) ---
        n_scrob = conn.execute(
            "UPDATE scrobble SET track_id=? WHERE track_id=?", (FIGUREHEAD_KEEP, FIGUREHEAD_MERGE)
        ).rowcount
        n_at = conn.execute(
            "UPDATE album_tracks SET track_id=? WHERE track_id=?", (FIGUREHEAD_KEEP, FIGUREHEAD_MERGE)
        ).rowcount
        # Repoint the alias (paren name) onto the kept entity; different norm_title, no PK clash.
        n_alias = conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?", (FIGUREHEAD_KEEP, FIGUREHEAD_MERGE)
        ).rowcount
        n_ent = conn.execute("DELETE FROM track WHERE track_id=?", (FIGUREHEAD_MERGE,)).rowcount
        log(f"[1] Merge Figurehead demo {FIGUREHEAD_MERGE}->{FIGUREHEAD_KEEP}: "
            f"scrobble={n_scrob} album_tracks={n_at} alias={n_alias} entity_deleted={n_ent}")

        # --- Step 2: trim canonical Pornography album_tracks to the 8 core tracks ---
        n_trim = conn.execute(
            "DELETE FROM album_tracks WHERE album_id=? AND track_number>=9", (canon_id,)
        ).rowcount
        log(f"[2] Trim canonical album_tracks to 8 tracks: deleted {n_trim} bonus rows")

        # --- Step 3: rebuild Deluxe album_tracks to 22 rows ---
        n_del = conn.execute("DELETE FROM album_tracks WHERE album_id=?", (deluxe_id,)).rowcount
        rows = []
        for pos, tid in CORE + BONUS:
            rows.append((
                ARTIST, DELUXE, title_of(conn, tid), pos, None, deluxe_mbid,
                artist_id, deluxe_id, tid,
            ))
        if not args.dry_run:
            conn.executemany(
                """INSERT OR REPLACE INTO album_tracks
                   (artist, album, track, track_number, track_mbid, album_mbid,
                    artist_id, album_id, track_id)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                rows,
            )
        log(f"[3] Rebuild Deluxe album_tracks: cleared {n_del} old rows, inserted {len(rows)} (8 core + 14 variants)")

        # --- Step 4: move variant scrobbles filed on `Pornography` -> Deluxe ---
        placeholders = ",".join("?" * len(BONUS_IDS))
        n_move = conn.execute(
            f"""UPDATE scrobble
                SET album=?, album_mbid=?, album_id=?
                WHERE artist=? AND album=? AND track_id IN ({placeholders})""",
            (DELUXE, deluxe_mbid, deluxe_id, ARTIST, CANON, *BONUS_IDS),
        ).rowcount
        log(f"[4] Move variant scrobbles Pornography->Deluxe: {n_move} rows")

        # --- Step 5: delete orphan duplicate variant entities (verify zero refs first) ---
        deleted_entities = 0
        deleted_aliases = 0
        skipped = []
        for tid in ORPHAN_CANDIDATES:
            sc = conn.execute("SELECT COUNT(*) FROM scrobble WHERE track_id=?", (tid,)).fetchone()[0]
            at = conn.execute("SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (tid,)).fetchone()[0]
            if sc == 0 and at == 0:
                da = conn.execute("DELETE FROM track_alias WHERE track_id=?", (tid,)).rowcount
                de = conn.execute("DELETE FROM track WHERE track_id=?", (tid,)).rowcount
                deleted_aliases += da
                deleted_entities += de
            else:
                skipped.append((tid, sc, at))
        log(f"[5] Orphan cleanup: deleted {deleted_entities} entities / {deleted_aliases} aliases"
            + (f"; SKIPPED (still referenced): {skipped}" if skipped else ""))

        if args.dry_run:
            conn.rollback()
            log("\n(dry run — rolled back)")
        else:
            conn.commit()
            log("\n(committed)")
    except Exception as e:
        conn.rollback()
        log(f"ABORTED (rolled back): {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
