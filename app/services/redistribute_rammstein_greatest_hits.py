#!/usr/bin/env python3
"""Remove Rammstein's bogus "Greatest Hits" album and route its scrobbles.

Usage:
    python -m app.services.redistribute_rammstein_greatest_hits --dry-run
    python -m app.services.redistribute_rammstein_greatest_hits
"""

import argparse
import sqlite3
from pathlib import Path


DB_PATH = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
ARTIST = "Rammstein"
SOURCE = "Greatest Hits of Rammstein"
SOURCE_ALBUM_ID = 3442

HERZELEID = ("Herzeleid", 363, "0b7e4117-fe48-3fa4-a507-b9404d642044")
SEHNSUCHT = ("Sehnsucht", 362, "1600f0f3-28c5-45ec-8600-32bf37d57eef")
RARITATEN = ("RARITÄTEN (1994 - 2012)", 359, "89092647-f97c-4b23-b564-d5b3433b4706")

# Source title: (target album tuple, canonical track title, canonical track_id)
ROUTES = {
    "Alter Mann": (SEHNSUCHT, "Alter Mann", 1257),
    "Asche Zu Asche": (HERZELEID, "Asche zu Asche", 1259),
    "Bück Dich": (SEHNSUCHT, "Bück Dich", 1290),
    "Der Meister": (HERZELEID, "Der Meister", 4558),
    "Du Hast": (SEHNSUCHT, "Du hast", 1286),
    "Du Reichst so Gut": (HERZELEID, "Du Riechst so Gut", 1269),
    "Engel": (SEHNSUCHT, "Engel", 1254),
    "Herzeleid": (HERZELEID, "Herzeleid", 4557),
    "Klavier": (SEHNSUCHT, "Klavier", 1261),
    "Laichzeit": (HERZELEID, "Laichzeit", 4560),
    "Rammstein": (HERZELEID, "Rammstein", 1255),
    "Seeman": (HERZELEID, "Seemann", 1260),
    "Sehsucht": (SEHNSUCHT, "Sehnsucht", 1256),
    "Stripped": (RARITATEN, "Stripped", 1272),
    "Tier": (SEHNSUCHT, "Tier", 1288),
    "Weisses Fleisch": (HERZELEID, "Weisses Fleisch", 4559),
    "Wollt Ihr Das Bett in Flammen Sehen": (
        HERZELEID, "Wollt Ihr das Bett in Flammen sehen", 1258
    ),
}

# These typo-only entities become unreferenced after the redistribution.
TYPO_TRACK_FOLDS = {29239: 1269, 25562: 1260, 25561: 1256}


def _count(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def redistribute(dry_run: bool = False) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    source_rows = conn.execute(
        "SELECT id, track FROM scrobble WHERE artist=? AND album=? ORDER BY id",
        (ARTIST, SOURCE),
    ).fetchall()
    unknown = sorted({row["track"] for row in source_rows} - ROUTES.keys())
    if unknown:
        raise RuntimeError(f"Unmapped source tracks: {unknown}")

    source_entity = conn.execute(
        "SELECT title FROM album WHERE album_id=?", (SOURCE_ALBUM_ID,)
    ).fetchone()
    if source_rows and (source_entity is None or source_entity["title"] != SOURCE):
        raise RuntimeError("Source album entity does not match the expected id/title")

    moved = {HERZELEID[0]: 0, SEHNSUCHT[0]: 0, RARITATEN[0]: 0}
    for row in source_rows:
        (album, album_id, album_mbid), track, track_id = ROUTES[row["track"]]
        tracklist = conn.execute(
            "SELECT track_mbid FROM album_tracks WHERE album_id=? AND track_id=?",
            (album_id, track_id),
        ).fetchone()
        if tracklist is None:
            raise RuntimeError(f"Canonical tracklist missing {album!r} / track_id {track_id}")
        conn.execute(
            """
            UPDATE scrobble
               SET album=?, album_mbid=?, album_id=?,
                   track=?, track_mbid=?, track_id=?
             WHERE id=?
            """,
            (album, album_mbid, album_id, track, tracklist["track_mbid"], track_id, row["id"]),
        )
        moved[album] += 1

    # Keep useful typo aliases, but point them to the canonical entities.
    for old_track_id, canonical_track_id in TYPO_TRACK_FOLDS.items():
        conn.execute(
            "UPDATE track_alias SET track_id=? WHERE track_id=?",
            (canonical_track_id, old_track_id),
        )
        refs = sum(
            _count(conn, f"SELECT COUNT(*) FROM {table} WHERE track_id=?", (old_track_id,))
            for table in ("scrobble", "album_tracks", "track_alias")
        )
        if refs == 0:
            conn.execute("DELETE FROM track WHERE track_id=?", (old_track_id,))

    conn.execute("DELETE FROM album_tracks WHERE album_id=?", (SOURCE_ALBUM_ID,))
    conn.execute("DELETE FROM album_art WHERE album_id=?", (SOURCE_ALBUM_ID,))
    conn.execute("DELETE FROM album_alias WHERE album_id=?", (SOURCE_ALBUM_ID,))

    refs = sum(
        _count(conn, f"SELECT COUNT(*) FROM {table} WHERE album_id=?", (SOURCE_ALBUM_ID,))
        for table in ("scrobble", "album_tracks", "album_art", "album_alias", "track")
    )
    if refs:
        raise RuntimeError(f"Source album still has {refs} reference(s)")
    conn.execute("DELETE FROM album WHERE album_id=?", (SOURCE_ALBUM_ID,))

    result = {
        "moved": moved,
        "total": len(source_rows),
        "source_scrobbles": _count(
            conn, "SELECT COUNT(*) FROM scrobble WHERE artist=? AND album=?", (ARTIST, SOURCE)
        ),
        "source_entity": _count(conn, "SELECT COUNT(*) FROM album WHERE album_id=?", (SOURCE_ALBUM_ID,)),
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
    result = redistribute(args.dry_run)
    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Moved {result['total']} scrobbles: {result['moved']}")
    print(f"{prefix}Source scrobbles remaining: {result['source_scrobbles']}")
    print(f"{prefix}Source album entities remaining: {result['source_entity']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
