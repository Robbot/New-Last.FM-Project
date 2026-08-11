#!/usr/bin/env python3
"""
Redistribute Cool Kids of Death - "Afterparty 2" scrobbles to their originals.

"Afterparty 2" is a remix album: every track is the original song name with a
trailing remixer annotation in parentheses, e.g.

    "Afterparty (Transition Remix by Egoist)"
    "Bal sobowtórów (Angelo Paradiso Remix)"
    "Mezczyzni bez amunicji (Kamp!)"

This script strips that remixer annotation and routes each scrobble to the
parent studio album "Afterparty" (mbid 67e09614-2ee2-4608-b326-01211d0895e4),
so play counts are no longer split across the remix album.

Two tracks ("Uwazaj", "Smierc turystom") have no original anywhere in the data;
per user decision they are routed to "Afterparty" as well (Afterparty 2 is its
remix companion).

What it does, per matched scrobble row:
    track      -> base name (remixer parenthetical stripped)
    album      -> "Afterparty"
    album_mbid -> the Afterparty MBID
    album_id   -> NULL  (re-resolved by seed_entities afterwards)
    track_id   -> NULL  (re-resolved by seed_entities afterwards)

Usage:
    python -m app.services.redistribute_afterparty2 --dry-run
    python -m app.services.redistribute_afterparty2            # apply for real
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Cool Kids of Death"
SOURCE_ALBUM = "Afterparty 2"
TARGET_ALBUM = "Afterparty"
FALLBACK_TARGET_MBID = "67e09614-2ee2-4608-b326-01211d0895e4"

# Exact full-name -> base-name mapping. Stripping is done by explicit lookup
# (not a regex) so every transformation is auditable and no surprise track gets
# mangled. Any track found on the source album that is NOT in this map is
# reported and left untouched.
TRACK_REMIX_TO_BASE = {
    "Nagle zapomniec wszystko (Flwnkz)": "Nagle zapomniec wszystko",
    "Bal sobowtórów (Kosakot 2007 Remix - Sorry Ghettoblaster)": "Bal sobowtórów",
    "TV Panika (Goodboy Khris Aka Nygga Dick - Dick 4 Dick)": "TV Panika",
    "Ruin gruz (Methadone Rmx)": "Ruin gruz",
    "Nagle zapomniec wszystko (Mediengruppe Telekommander)": "Nagle zapomniec wszystko",
    "Nagle zapomniec wszystko (Antosh)": "Nagle zapomniec wszystko",
    "Mezczyzni bez amunicji (Videoturisten)": "Mezczyzni bez amunicji",
    "Mezczyzni bez amunicji (Kamp!)": "Mezczyzni bez amunicji",
    "Mamo, mój komputer jest zepsuty (Deuce - Psychocukier)": "Mamo, mój komputer jest zepsuty",
    "Lezec (Sid Caesar & Aka Dada Hipster)": "Lezec",
    "Bal sobowtórów (Angelo Paradiso Remix)": "Bal sobowtórów",
    "Afterparty (Transition Remix by Egoist)": "Afterparty",
    "Afterparty (Cinass)": "Afterparty",
    "Uwazaj (Drivealone Mix)": "Uwazaj",
    "Smierc turystom (CKOD & Supra1)": "Smierc turystom",
}


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path.exists():
        return str(db_path)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_db_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def resolve_target_mbid(conn) -> str:
    """MBID for the target album, preferring album_art then existing scrobbles."""
    row = conn.execute(
        "SELECT album_mbid FROM album_art WHERE artist = ? AND album = ? LIMIT 1",
        (ARTIST, TARGET_ALBUM),
    ).fetchone()
    if row and row["album_mbid"]:
        return row["album_mbid"]
    row = conn.execute(
        """
        SELECT album_mbid FROM scrobble
        WHERE artist = ? AND album = ? AND album_mbid IS NOT NULL AND album_mbid != ''
        LIMIT 1
        """,
        (ARTIST, TARGET_ALBUM),
    ).fetchone()
    if row and row["album_mbid"]:
        return row["album_mbid"]
    return FALLBACK_TARGET_MBID


def redistribute(dry_run: bool = True) -> dict:
    conn = get_db_connection()
    target_mbid = resolve_target_mbid(conn)

    # Distinct tracks currently on the source album.
    source_tracks = [
        r["track"]
        for r in conn.execute(
            "SELECT DISTINCT track FROM scrobble WHERE artist = ? AND album = ? ORDER BY track",
            (ARTIST, SOURCE_ALBUM),
        ).fetchall()
    ]

    unmapped = [t for t in source_tracks if t not in TRACK_REMIX_TO_BASE]
    for t in unmapped:
        logger.warning("Unmapped track on %s, leaving untouched: %r", SOURCE_ALBUM, t)

    moved = 0
    skipped_integrity = 0
    detail = []

    rows = conn.execute(
        """
        SELECT id, track, uts FROM scrobble
        WHERE artist = ? AND album = ?
        ORDER BY track, uts
        """,
        (ARTIST, SOURCE_ALBUM),
    ).fetchall()

    for scrobble in rows:
        full = scrobble["track"]
        base = TRACK_REMIX_TO_BASE.get(full)
        if base is None:
            continue  # reported above as unmapped
        if dry_run:
            detail.append((scrobble["id"], full, base))
            moved += 1
            continue
        try:
            conn.execute(
                """
                UPDATE scrobble
                SET track = ?, album = ?, album_mbid = ?, album_id = NULL, track_id = NULL
                WHERE id = ?
                """,
                (base, TARGET_ALBUM, target_mbid, scrobble["id"]),
            )
            moved += 1
            detail.append((scrobble["id"], full, base))
        except sqlite3.IntegrityError:
            # Collision on unique (uts, artist, album, track): an original
            # scrobble already exists at this timestamp. Skip and log.
            skipped_integrity += 1
            logger.warning(
                "IntegrityError: skipped scrobble %s (%r) - a scrobble for "
                "%r on %r at uts=%s already exists",
                scrobble["id"], full, base, TARGET_ALBUM, scrobble["uts"],
            )

    if not dry_run:
        conn.commit()
    conn.close()

    logger.info(
        "%s: %d scrobble(s) %s (%d integrity skips, %d unmapped tracks). "
        "Target album=%r mbid=%s",
        "[DRY RUN]" if dry_run else "DONE",
        moved,
        "to update" if dry_run else "updated",
        skipped_integrity,
        len(unmapped),
        TARGET_ALBUM,
        target_mbid,
    )

    return {
        "dry_run": dry_run,
        "moved": moved,
        "skipped_integrity": skipped_integrity,
        "unmapped_tracks": unmapped,
        "target_album": TARGET_ALBUM,
        "target_mbid": target_mbid,
        "detail": detail,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Strip remixer annotations from Cool Kids of Death "
        "'Afterparty 2' tracks and route scrobbles to album 'Afterparty'."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = redistribute(dry_run=args.dry_run)

    prefix = "[DRY RUN] " if result["dry_run"] else ""
    print(f"{prefix}Target: {result['target_album']} (mbid {result['target_mbid']})")
    print(f"{prefix}Scrobbles {'to update' if args.dry_run else 'updated'}: {result['moved']}")
    print(f"{prefix}Integrity skips: {result['skipped_integrity']}")

    if result["unmapped_tracks"]:
        print(f"{prefix}Unmapped tracks left untouched:")
        for t in result["unmapped_tracks"]:
            print(f"    - {t}")

    print(f"{prefix}Transformations (id: remix -> base):")
    for sid, full, base in result["detail"]:
        print(f"    {sid}: {full!r} -> {base!r}")

    if not args.dry_run and result["moved"]:
        print(
            "\nRun `python -m app.services.seed_entities` to repopulate the "
            "now-NULL album_id/track_id columns."
        )
    return 0


if __name__ == "__main__":
    main()
