#!/usr/bin/env python3
"""
Merge the Big Cyc album "Bombowe Hity" into the canonical best-of
"Bombowe hity czyli the best of 1988-2004".

Symptom: the same compilation is split across two canonical album entities.
"Bombowe Hity" (album_id 3965, MB release f23ad58e, 23 scrobbles) is just the
short Spotify tag for the best-of "Bombowe hity czyli the best of 1988-2004"
(album_id 100, MB release 791d16d4, 19 scrobbles). They are one release from
the listener's point of view, so the "Bombowe Hity" scrobbles belong on the
canonical album.

Tracks do NOT pre-share here, unlike a plain edition-suffix merge. The track
normalizer (``_normalize_track_name_for_matching``) lowercases but does NOT
strip accents, so the diacritic tracklist names fetched from Last.fm/MusicBrainz
("Nienawidzę Szefa" -> track_id 317) and the ASCII Spotify scrobbles
("Nienawidze Szefa" -> track_id 29537) resolved to DIFFERENT track entities.
A text-only album merge would land those tracks on the wrong track_id and they
would read as 0 plays on the canonical album page (album page joins
``album_tracks.track_id = scrobble.track_id`` scoped by ``album_id``). So the
10 ASCII-only track entities are folded into their diacritic twins as part of
this merge. (The ASCII entities are scrobble-only — no tracklist rows, and all
of their scrobbles live on "Bombowe Hity" — so the fold is unambiguous.)

In one transaction, fold 3965 -> 100 + fold 10 ascii track entities:
  1. scrobble (23 rows): album text -> canonical, album_mbid -> 791d16d4,
     album_id -> 100, album_artist -> "Big Cyc".
  2. track entities: for each ascii track_id, move its scrobbles onto the
     diacritic twin, repoint its alias norm_title onto the twin (read->delete->
     insert, since the ascii norm and diacritic norm share no PK slot but the
     ascii alias must be dropped before its norm_title is re-inserted), then
     delete the now-empty ascii entity.
  3. album_alias: repoint the variant alias (norm "bombowe hity") 3965 -> 100,
     so future "Bombowe Hity" scrobbles resolve to canonical even if a sync
     misses the album-name mapping.
  4. album_tracks: delete the 8 orphaned src tracklist rows (album_id 3965).
     The canonical tracklist (album_id 100) already covers the same songs.
  5. album_art: delete the src row (album "Bombowe Hity"). The canonical row
     already carries cover images + year 2004.
  6. album entity: set canonical 100's mbid (NULL today); delete orphan 3965.

A matching album-name mapping is added to album_name_mappings.json so sync
rewrites the "Bombowe Hity" tag at ingestion (recurrence prevention at source).

Idempotent: every WHERE clause no longer matches after the first run.

Usage:
    python -m app.services.move_bombowe_hity --dry-run
    python -m app.services.move_bombowe_hity
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Big Cyc"
ARTIST_ID = 146

SRC_ALBUM = "Bombowe Hity"
SRC_ALBUM_ID = 3965
SRC_MBID = "f23ad58e-eacf-4d53-97a8-372bbedb38fb"

DST_ALBUM = "Bombowe hity czyli the best of 1988-2004"
DST_ALBUM_ID = 100
DST_MBID = "791d16d4-425b-4ec3-8fe1-14ed2c240a55"

# ascii track_id -> diacritic twin track_id (the entity the canonical tracklist
# + other-album scrobbles already sit on). The diacritic entity is the survivor.
TRACK_MERGES = {
    29537: 317,   # "Nienawidze Szefa"  -> "Nienawidzę Szefa"
    29531: 307,   # "Sloneczny Patrol"  -> "Słoneczny Patrol"
    29528: 302,   # "Zloty Warkocz"     -> "Złoty Warkocz"
    29529: 304,   # "Kazdy Facet To"    -> "Każdy facet to świnia"  (abbreviated scrobble)
    29534: 312,   # "Jak Slodko Zostac Swirem"      -> "Jak Słodko Zostać Świrem"
    29532: 310,   # "Krecimy Pornola"   -> "KRĘCIMY PORNOLA"
    29533: 311,   # "Piosenka Goralska" -> "Piosenka Góralska"
    29234: 308,   # "Rudy Sie Zeni"     -> "Rudy się żeni"
    29535: 314,   # "Wielka Milosc Do Babci Klozetowej" -> "Wielka miłość do babci klozetowej"
    29536: 316,   # "Kapitan Zbik"      -> "Kapitan Żbik"
}

EXPECTED_TOTAL_PLAYS = 42  # 19 existing canonical + 23 moved


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


def _track_refs(conn, track_id: int) -> int:
    """Total references to a track entity from scrobble/album_tracks/track_alias."""
    return (
        _count(conn, "SELECT COUNT(*) FROM scrobble WHERE track_id=?", (track_id,))
        + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE track_id=?", (track_id,))
        + _count(conn, "SELECT COUNT(*) FROM track_alias WHERE track_id=?", (track_id,))
    )


def run(dry_run: bool) -> int:
    conn = get_db_connection()
    try:
        return _run(conn, dry_run)
    finally:
        conn.close()


def _run(conn: sqlite3.Connection, dry_run: bool) -> int:
    ascii_ids = list(TRACK_MERGES.keys())

    print("=" * 72)
    print(f"Big Cyc album merge: '{SRC_ALBUM}' -> '{DST_ALBUM}'  "
          f"({'DRY RUN' if dry_run else 'APPLY'})")
    print("=" * 72)

    # --- pre-state ----------------------------------------------------------
    scr_src = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (SRC_ALBUM_ID,))
    alias_src = _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
    tracks_src = _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
    art_src = _count(conn, "SELECT COUNT(*) FROM album_art WHERE album_mbid=?", (SRC_MBID,))
    entity_src = _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SRC_ALBUM_ID,))
    dst_mbid_missing = _count(
        conn, "SELECT COUNT(*) FROM album WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_ALBUM_ID, DST_MBID),
    )
    track_albumid_src = _count(conn, "SELECT COUNT(*) FROM track WHERE album_id=?", (SRC_ALBUM_ID,))
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
    ascii_scrobbles = _count(
        conn,
        f"SELECT COUNT(*) FROM scrobble WHERE track_id IN ({','.join('?'*len(ascii_ids))})",
        ascii_ids,
    )
    ascii_tracklist_refs = _count(
        conn,
        f"SELECT COUNT(*) FROM album_tracks WHERE track_id IN ({','.join('?'*len(ascii_ids))})",
        ascii_ids,
    )

    print(f"[pre] scrobbles on src album_id {SRC_ALBUM_ID}: {scr_src}")
    print(f"[pre] aliases pointing at src: {alias_src}")
    print(f"[pre] src tracklist rows (album_id {SRC_ALBUM_ID}): {tracks_src}")
    print(f"[pre] src album_art rows (mbid {SRC_MBID[:8]}): {art_src}")
    print(f"[pre] src album entity exists: {entity_src}")
    print(f"[pre] dst album mbid missing/wrong: {dst_mbid_missing}")
    print(f"[pre] FK blockers (track.album_id=src): {track_albumid_src}")
    print(f"[pre] scrobble PK collisions on rename: {collisions}")
    print(f"[pre] ascii track entities to fold: {len(ascii_ids)} "
          f"(scrobbles on them: {ascii_scrobbles}, tracklist refs: {ascii_tracklist_refs})")

    if collisions:
        print(f"\n[ABORT] {collisions} scrobble PK collision(s) — rename would violate "
              f"UNIQUE(uts,artist,album,track). Investigate before proceeding.")
        conn.rollback()
        return 1
    # Sanity: the ascii entities must be scrobble-only (no tracklist refs) for an
    # unambiguous fold; a non-zero count here means the diacritic twin is not the
    # sole tracklist owner and the fold needs rethinking.
    if ascii_tracklist_refs:
        print(f"\n[ABORT] ascii track entities have {ascii_tracklist_refs} tracklist ref(s); "
              f"expected 0 (scrobble-only). Investigate before proceeding.")
        conn.rollback()
        return 1

    nothing_to_do = (
        scr_src == 0 and alias_src == 0 and tracks_src == 0 and art_src == 0
        and entity_src == 0 and dst_mbid_missing == 0
        and ascii_scrobbles == 0
        and all(_count(conn, "SELECT COUNT(*) FROM track WHERE track_id=?", (a,)) == 0 for a in ascii_ids)
    )
    if nothing_to_do:
        print("[pre] Nothing to do — already merged (idempotent no-op).")
        return 0

    # --- Step 1: move scrobbles onto canonical album ------------------------
    print("\n[1/6] Moving scrobbles onto canonical album")
    moved = conn.execute(
        "UPDATE scrobble SET album=?, album_mbid=?, album_id=?, album_artist=? "
        "WHERE album_id=?",
        (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, SRC_ALBUM_ID),
    ).rowcount
    print(f"      scrobbles moved: {moved}")

    # --- Step 2: fold ascii track entities into diacritic twins -------------
    print("\n[2/6] Folding ascii track entities into diacritic twins")
    for ascii_id, diacritic_id in TRACK_MERGES.items():
        smoved = conn.execute(
            "UPDATE scrobble SET track_id=? WHERE track_id=?",
            (diacritic_id, ascii_id),
        ).rowcount
        # Move the ascii alias norm_title(s) onto the diacritic entity. The ascii
        # norm (e.g. "nienawidze szefa") differs from the diacritic norm
        # ("nienawidzę szefa"), so the alias must be carried over or a future
        # ASCII-tagged scrobble would re-split. read -> delete -> insert: the
        # ascii alias row shares no PK with the copy, but deleting first keeps the
        # INSERT OR IGNORE honest if the twin somehow already owns that norm.
        ascii_aliases = conn.execute(
            "SELECT artist_id, norm_title FROM track_alias WHERE track_id=?", (ascii_id,)
        ).fetchall()
        conn.execute("DELETE FROM track_alias WHERE track_id=?", (ascii_id,))
        copied = 0
        for a in ascii_aliases:
            copied += conn.execute(
                "INSERT OR IGNORE INTO track_alias (artist_id, norm_title, track_id) "
                "VALUES (?,?,?)",
                (a["artist_id"], a["norm_title"], diacritic_id),
            ).rowcount
        print(f"      {ascii_id} -> {diacritic_id}: scrobbles={smoved}, aliases copied={copied}")

    # --- Step 3: repoint album alias ----------------------------------------
    print("\n[3/6] Repointing album alias -> canonical")
    repointed = conn.execute(
        "UPDATE album_alias SET album_id=? WHERE album_id=?",
        (DST_ALBUM_ID, SRC_ALBUM_ID),
    ).rowcount
    print(f"      aliases repointed: {repointed}")

    # --- Step 4: delete orphaned src tracklist rows -------------------------
    print("\n[4/6] Deleting orphaned src tracklist rows")
    del_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,),
    ).rowcount
    print(f"      tracklist rows deleted: {del_tracks}")

    # --- Step 5: delete orphaned src album_art row --------------------------
    print("\n[5/6] Deleting orphaned src album_art row")
    del_art = conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?", (ARTIST, SRC_ALBUM),
    ).rowcount
    print(f"      album_art rows deleted: {del_art}")

    # --- Step 6: ascii track entities + canonical mbid + src album entity ---
    print("\n[6/6] Deleting empty ascii track entities; setting canonical mbid; "
          "deleting src album entity")
    for ascii_id in ascii_ids:
        if _track_refs(conn, ascii_id) == 0:
            d = conn.execute("DELETE FROM track WHERE track_id=?", (ascii_id,)).rowcount
            print(f"      deleted ascii track entity {ascii_id}: {d} row(s)")
        else:
            print(f"      !! kept ascii track entity {ascii_id}: still "
                  f"{_track_refs(conn, ascii_id)} reference(s)")
    set_mbid = conn.execute(
        "UPDATE album SET mbid=? WHERE album_id=? AND (mbid IS NULL OR mbid != ?)",
        (DST_MBID, DST_ALBUM_ID, DST_MBID),
    ).rowcount
    print(f"      canonical album {DST_ALBUM_ID} mbid -> {DST_MBID}: {set_mbid} row(s)")
    remaining_refs = (
        _count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (SRC_ALBUM_ID,))
        + _count(conn, "SELECT COUNT(*) FROM album_tracks WHERE album_id=?", (SRC_ALBUM_ID,))
        + _count(conn, "SELECT COUNT(*) FROM album_alias WHERE album_id=?", (SRC_ALBUM_ID,))
        + _count(conn, "SELECT COUNT(*) FROM track WHERE album_id=?", (SRC_ALBUM_ID,))
    )
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
    print(f"  total plays: {total} (expect {EXPECTED_TOTAL_PLAYS})")
    print(f"  src album entity remaining: "
          f"{_count(conn, 'SELECT COUNT(*) FROM album WHERE album_id=?', (SRC_ALBUM_ID,))} (expect 0)")
    print(f"  scrobbles still under src name: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album=?', (SRC_ALBUM,))} (expect 0)")
    print(f"  scrobbles still under src mbid: "
          f"{_count(conn, 'SELECT COUNT(*) FROM scrobble WHERE album_mbid=?', (SRC_MBID,))} (expect 0)")

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
        description="Merge Big Cyc 'Bombowe Hity' into 'Bombowe hity czyli the best of 1988-2004'"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return run(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
