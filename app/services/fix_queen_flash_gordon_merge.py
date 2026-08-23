#!/usr/bin/env python3
"""Merge Queen's soundtrack-title variant into canonical ``Flash Gordon``."""

import argparse
import sqlite3
from pathlib import Path


ARTIST = "Queen"
SRC_ALBUM = "Flash Gordon (Original Soundtrack)"
DST_ALBUM = "Flash Gordon"
DST_ALBUM_ID = 694
DST_MBID = "04d0af62-3385-4407-8c88-f1e336d66daf"


def run(dry_run: bool = False) -> int:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        src_ids = [r[0] for r in conn.execute(
            "SELECT album_id FROM album WHERE artist_id=(SELECT artist_id FROM artist WHERE name=?) "
            "AND title=? AND album_id != ?",
            (ARTIST, SRC_ALBUM, DST_ALBUM_ID),
        )]
        collisions = conn.execute(
            "SELECT COUNT(*) FROM scrobble s WHERE s.artist=? AND s.album=? "
            "AND EXISTS (SELECT 1 FROM scrobble d WHERE d.artist=? AND d.album=? "
            "AND d.uts=s.uts AND d.track=s.track)",
            (ARTIST, SRC_ALBUM, ARTIST, DST_ALBUM),
        ).fetchone()[0]
        if collisions:
            raise RuntimeError(f"Aborting: {collisions} scrobble key collision(s)")

        moved = conn.execute(
            "UPDATE scrobble SET album=?, album_mbid=?, album_id=? "
            "WHERE artist=? AND (album=? OR album_id IN (%s))"
            % (",".join("?" * len(src_ids)) or "NULL"),
            (DST_ALBUM, DST_MBID, DST_ALBUM_ID, ARTIST, SRC_ALBUM, *src_ids),
        ).rowcount

        # The two tracklists use the same track IDs. Keep the canonical rows and
        # repoint the underlying track entities before removing the duplicate list.
        for src_id in src_ids:
            conn.execute("UPDATE track SET album_id=? WHERE album_id=?", (DST_ALBUM_ID, src_id))
            conn.execute("UPDATE album_alias SET album_id=? WHERE album_id=?", (DST_ALBUM_ID, src_id))
        deleted_tracks = conn.execute(
            "DELETE FROM album_tracks WHERE artist=? AND album=?",
            (ARTIST, SRC_ALBUM),
        ).rowcount
        deleted_art = conn.execute(
            "DELETE FROM album_art WHERE artist=? AND album=?",
            (ARTIST, SRC_ALBUM),
        ).rowcount

        conn.execute("UPDATE album SET title=?, mbid=? WHERE album_id=?",
                     (DST_ALBUM, DST_MBID, DST_ALBUM_ID))
        conn.execute("UPDATE album_art SET album_mbid=?, album_id=? WHERE artist=? AND album=?",
                     (DST_MBID, DST_ALBUM_ID, ARTIST, DST_ALBUM))
        conn.execute("UPDATE album_tracks SET album_mbid=?, album_id=? WHERE artist=? AND album=?",
                     (DST_MBID, DST_ALBUM_ID, ARTIST, DST_ALBUM))
        for src_id in src_ids:
            conn.execute("DELETE FROM album WHERE album_id=?", (src_id,))

        print(f"scrobbles moved: {moved}")
        print(f"duplicate tracklist rows removed: {deleted_tracks}")
        print(f"duplicate artwork rows removed: {deleted_art}")
        print(f"canonical album: {DST_ALBUM!r}, id={DST_ALBUM_ID}, mbid={DST_MBID}")
        if dry_run:
            conn.rollback()
            print("dry run: rolled back")
        else:
            conn.commit()
            print("changes committed")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    raise SystemExit(run(parser.parse_args().dry_run))
