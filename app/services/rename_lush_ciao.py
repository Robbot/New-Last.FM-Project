#!/usr/bin/env python3
"""
One-shot data fix: consolidate the Lush compilations 'Ciao! Best Of' and 'Ciao!'
into a single canonical album 'Ciao! Best of Lush' (MBID ad0afd06-...).

Touches scrobble, album_art, album_tracks and the album/album_alias entity
tables in one transaction with foreign keys on, so it either fully applies or
rolls back. Idempotent-ish: re-running on already-consolidated data is a no-op
(the WHERE clauses match nothing).

    python -m app.services.rename_lush_ciao            # apply
    python -m app.services.rename_lush_ciao --dry-run  # preview counts only
"""

import argparse
import sqlite3
from pathlib import Path

from app.db.connections import _normalize_for_matching

DB_PATH = Path.cwd() / "files" / "lastfmstats.sqlite"
ARTIST = "Lush"
SOURCE_ALBUMS = ("Ciao! Best Of", "Ciao!")
TARGET_ALBUM = "Ciao! Best of Lush"
TARGET_MBID = "ad0afd06-0a55-4a7d-97d0-8af43d32fdce"
# album_id 712 is the dominant entity ('Ciao! Best Of', 206 scrobbles); reuse it.
KEEP_ALBUM_ID = 712
# album_id 3428 ('Ciao!') becomes an orphan after consolidation.
ORPHAN_ALBUM_ID = 3428


def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    conn = get_conn()
    placeholders = ",".join("?" for _ in SOURCE_ALBUMS)

    def count(table, where, params=()):
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]

    before = {
        "scrobble_rows": count("scrobble", f"artist=? AND album IN ({placeholders})",
                               (ARTIST, *SOURCE_ALBUMS)),
        "album_art_rows": count("album_art", f"artist=? AND album IN ({placeholders})",
                                (ARTIST, *SOURCE_ALBUMS)),
        "album_tracks_rows": count("album_tracks", f"artist=? AND album IN ({placeholders})",
                                   (ARTIST, *SOURCE_ALBUMS)),
    }
    print("== BEFORE ==")
    print(f"  matching scrobble rows : {before['scrobble_rows']}")
    print(f"  matching album_art rows: {before['album_art_rows']}")
    print(f"  matching album_tracks  : {before['album_tracks_rows']}")

    if args.dry_run:
        print("\n[DRY RUN] no changes written.")
        return

    try:
        with conn:
            # 1) scrobble: rename album + set MBID + canonical album_id
            conn.execute(
                f"""UPDATE scrobble
                       SET album = ?, album_mbid = ?, album_id = ?
                     WHERE artist = ? AND album IN ({placeholders})""",
                (TARGET_ALBUM, TARGET_MBID, KEEP_ALBUM_ID, ARTIST, *SOURCE_ALBUMS),
            )

            # 2) album_art: drop the inferior 'Ciao!' row, repurpose the
            #    'Ciao! Best Of' row (has year + image) as the target.
            conn.execute(
                "DELETE FROM album_art WHERE artist = ? AND album = ?",
                (ARTIST, "Ciao!"),
            )
            conn.execute(
                """UPDATE album_art
                      SET album = ?, album_mbid = ?, album_id = ?
                    WHERE artist = ? AND album = 'Ciao! Best Of'""",
                (TARGET_ALBUM, TARGET_MBID, KEEP_ALBUM_ID, ARTIST),
            )

            # 3) album_tracks: drop the near-duplicate 'Ciao!' tracklist,
            #    repurpose the 'Ciao! Best Of' tracklist.
            conn.execute(
                "DELETE FROM album_tracks WHERE artist = ? AND album = ?",
                (ARTIST, "Ciao!"),
            )
            conn.execute(
                """UPDATE album_tracks
                      SET album = ?, album_mbid = ?, album_id = ?
                    WHERE artist = ? AND album = 'Ciao! Best Of'""",
                (TARGET_ALBUM, TARGET_MBID, KEEP_ALBUM_ID, ARTIST),
            )

            # 4) canonical album entity: reuse id 712, set canonical title/MBID,
            #    register the new normalized title as an alias.
            conn.execute(
                "UPDATE album SET title = ?, mbid = ? WHERE album_id = ?",
                (TARGET_ALBUM, TARGET_MBID, KEEP_ALBUM_ID),
            )
            conn.execute(
                """INSERT OR IGNORE INTO album_alias (artist_id, norm_title, album_id)
                   VALUES (?, ?, ?)""",
                (_lookup_lush_artist_id(conn), _normalize_for_matching(TARGET_ALBUM), KEEP_ALBUM_ID),
            )

            # 5) remove the now-orphaned 'Ciao!' album entity, guarded by a
            #    reference check so we never orphan a live FK target.
            refs = conn.execute(
                """SELECT
                     (SELECT COUNT(*) FROM scrobble     WHERE album_id = ?) AS s,
                     (SELECT COUNT(*) FROM album_art    WHERE album_id = ?) AS a,
                     (SELECT COUNT(*) FROM album_tracks WHERE album_id = ?) AS t""",
                (ORPHAN_ALBUM_ID, ORPHAN_ALBUM_ID, ORPHAN_ALBUM_ID),
            ).fetchone()
            total_refs = refs["s"] + refs["a"] + refs["t"]
            if total_refs == 0:
                conn.execute("DELETE FROM album_alias WHERE album_id = ?", (ORPHAN_ALBUM_ID,))
                conn.execute("DELETE FROM album WHERE album_id = ?", (ORPHAN_ALBUM_ID,))
                print(f"\nRemoved orphan album entity {ORPHAN_ALBUM_ID}.")
            else:
                print(f"\nWARNING: orphan album {ORPHAN_ALBUM_ID} still referenced "
                      f"(scrobble={refs['s']}, album_art={refs['a']}, "
                      f"album_tracks={refs['t']}); left in place.")
    finally:
        conn.close()

    conn = get_conn()
    after = {
        "scrobble": count("scrobble", "artist=? AND album=? AND album_mbid=? AND album_id=?",
                          (ARTIST, TARGET_ALBUM, TARGET_MBID, KEEP_ALBUM_ID)),
        "leftover_scrobble": count("scrobble", f"artist=? AND album IN ({placeholders})",
                                   (ARTIST, *SOURCE_ALBUMS)),
        "album_art": count("album_art", "artist=? AND album=?", (ARTIST, TARGET_ALBUM)),
        "leftover_album_art": count("album_art", f"artist=? AND album IN ({placeholders})",
                                    (ARTIST, *SOURCE_ALBUMS)),
        "album_tracks": count("album_tracks", "artist=? AND album=?", (ARTIST, TARGET_ALBUM)),
        "leftover_album_tracks": count("album_tracks", f"artist=? AND album IN ({placeholders})",
                                       (ARTIST, *SOURCE_ALBUMS)),
    }
    conn.close()
    print("\n== AFTER ==")
    print(f"  scrobble -> '{TARGET_ALBUM}'           : {after['scrobble']}")
    print(f"  scrobble leftover source albums        : {after['leftover_scrobble']}")
    print(f"  album_art -> '{TARGET_ALBUM}'          : {after['album_art']}")
    print(f"  album_art leftover source albums       : {after['leftover_album_art']}")
    print(f"  album_tracks -> '{TARGET_ALBUM}'       : {after['album_tracks']}")
    print(f"  album_tracks leftover source albums    : {after['leftover_album_tracks']}")


def _lookup_lush_artist_id(conn):
    row = conn.execute(
        "SELECT artist_id FROM artist_alias WHERE alias_name = ?", (ARTIST,)
    ).fetchone()
    if not row:
        raise RuntimeError("Could not resolve artist_id for 'Lush'")
    return row[0]


if __name__ == "__main__":
    main()
