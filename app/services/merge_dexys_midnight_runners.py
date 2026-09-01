#!/usr/bin/env python3
"""Canonicalize Dexys Midnight Runners and the album Too-Rye-Ay."""

import argparse
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
ARTIST_ID = 330
ALBUM_ID = 708
CANONICAL_ARTIST = "Dexys Midnight Runners"
VARIANT_ARTIST = "Dexy's Midnight Runners"
CANONICAL_ALBUM = "Too-Rye-Ay"
VARIANT_ALBUM = "Too Rye Ay"
ARTIST_MBID = "ccce2053-7007-4c36-b1e7-f8fcf5023a12"
ALBUM_MBID = "b3865201-9889-3be7-bf42-146bd298cc6f"


def _count(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def merge(dry_run: bool = False) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    artist = conn.execute("SELECT * FROM artist WHERE artist_id=?", (ARTIST_ID,)).fetchone()
    album = conn.execute("SELECT * FROM album WHERE album_id=?", (ALBUM_ID,)).fetchone()
    if artist is None or artist["name"] not in (CANONICAL_ARTIST, VARIANT_ARTIST):
        raise RuntimeError("Artist 330 is not the expected Dexys entity")
    if album is None or album["title"] not in (CANONICAL_ALBUM, VARIANT_ALBUM):
        raise RuntimeError("Album 708 is not the expected Too-Rye-Ay entity")

    affected = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE artist_id=?", (ARTIST_ID,))
    album_affected = _count(conn, "SELECT COUNT(*) FROM scrobble WHERE album_id=?", (ALBUM_ID,))

    # Scrobbles use the shared canonical IDs already; synchronize all text and
    # identifiers so pages grouped by either legacy spelling collapse together.
    conn.execute(
        """
        UPDATE scrobble
           SET artist=?, artist_mbid=?,
               album_artist=CASE WHEN album_artist IN (?, ?) THEN ? ELSE album_artist END
         WHERE artist_id=?
        """,
        (CANONICAL_ARTIST, ARTIST_MBID, CANONICAL_ARTIST, VARIANT_ARTIST,
         CANONICAL_ARTIST, ARTIST_ID),
    )
    conn.execute(
        "UPDATE scrobble SET album=?, album_mbid=? WHERE album_id=?",
        (CANONICAL_ALBUM, ALBUM_MBID, ALBUM_ID),
    )

    conn.execute(
        "UPDATE artist SET name=?, mbid=? WHERE artist_id=?",
        (CANONICAL_ARTIST, ARTIST_MBID, ARTIST_ID),
    )
    conn.execute(
        "UPDATE album SET title=?, mbid=?, artist_id=? WHERE album_id=?",
        (CANONICAL_ALBUM, ALBUM_MBID, ARTIST_ID, ALBUM_ID),
    )

    # Preserve both incoming spellings as aliases. They normalize to the same
    # resolver key, while the entity itself now carries the canonical spelling.
    conn.execute(
        "UPDATE artist_alias SET artist_id=? WHERE artist_id=?",
        (ARTIST_ID, ARTIST_ID),
    )

    # Keep the newer, correctly identified artwork row and discard the row
    # whose MBID/title pointed at the unhyphenated edition.
    conn.execute(
        "DELETE FROM album_art WHERE artist=? AND album=?",
        (CANONICAL_ARTIST, VARIANT_ALBUM),
    )
    conn.execute(
        """
        UPDATE album_art
           SET artist=?, album=?, album_mbid=?, artist_mbid=?, artist_id=?, album_id=?
         WHERE artist=? AND album=?
        """,
        (CANONICAL_ARTIST, CANONICAL_ALBUM, ALBUM_MBID, ARTIST_MBID,
         ARTIST_ID, ALBUM_ID, VARIANT_ARTIST, CANONICAL_ALBUM),
    )

    conn.execute(
        """
        UPDATE album_tracks
           SET artist=?, album=?, album_mbid=?, artist_id=?, album_id=?
         WHERE album_id=?
        """,
        (CANONICAL_ARTIST, CANONICAL_ALBUM, ALBUM_MBID, ARTIST_ID, ALBUM_ID, ALBUM_ID),
    )

    # artist_info has one row for each spelling. Retain the more recently
    # refreshed apostrophe row, then rename it to the canonical key.
    conn.execute("DELETE FROM artist_info WHERE artist_name=?", (CANONICAL_ARTIST,))
    conn.execute(
        "UPDATE artist_info SET artist_name=?, artist_id=? WHERE artist_name=?",
        (CANONICAL_ARTIST, ARTIST_ID, VARIANT_ARTIST),
    )
    conn.execute(
        "UPDATE musicbrainz_releases SET artist_name=? WHERE artist_id=?",
        (CANONICAL_ARTIST, ARTIST_ID),
    )

    result = {
        "artist_scrobbles": affected,
        "album_scrobbles": album_affected,
        "variant_scrobbles": _count(
            conn,
            "SELECT COUNT(*) FROM scrobble WHERE artist=? OR album=?",
            (VARIANT_ARTIST, VARIANT_ALBUM),
        ),
        "canonical_scrobbles": _count(
            conn,
            "SELECT COUNT(*) FROM scrobble WHERE artist=? AND album=?",
            (CANONICAL_ARTIST, CANONICAL_ALBUM),
        ),
    }
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = merge(args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Artist scrobbles canonicalized: {result['artist_scrobbles']}")
    print(f"{prefix}Album scrobbles canonicalized: {result['album_scrobbles']}")
    print(f"{prefix}Canonical artist/album scrobbles: {result['canonical_scrobbles']}")
    print(f"{prefix}Variant scrobbles remaining: {result['variant_scrobbles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
