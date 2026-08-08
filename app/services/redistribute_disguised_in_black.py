#!/usr/bin/env python3
"""
Redistribute The Sisters of Mercy - "Disguised in Black" scrobbles to their
official albums.

"Disguised in Black" is a bootleg: its 16 tracks span the band's whole catalog,
each belonging to a different official release. Verified against the cached
album_tracks tracklists (and the scrobble distribution), each track is routed
to its real album so play counts are no longer stranded on the bootleg:

  * First and Last and Always (05c0940f): A Rock and a Hard Place, Marian,
    No Time to Cry, Possession, Walk Away, Logic, First & Last & Always,
    Nine While Nine Ghostrider, Body & Soul
  * Some Girls Wander by Mistake (9643ead9): Alice, Body Electric, Burn,
    Floorshow, Gimme Shelter
  * Floodland Collection (040ee1a5): Emma
  * First and Last and Always Collection (52d53b4b): Train

Three tracks have no clean official tracklist match (bootleg-only, no other
scrobbles): "First & Last & Always" (the FHLAA title track, abbreviated
"and"->"&"), "Nine While Nine Ghostrider" (a Nine While Nine / Ghostrider
medley), and "Body & Soul". Per user decision these are routed to First and
Last and Always as their closest official home.

Per matched scrobble row:
    album      -> target album
    album_mbid -> target album MBID
    album_id   -> NULL  (re-resolved by seed_entities afterwards)
    track_id   -> NULL  (re-resolved by seed_entities afterwards)
The track name and album_artist ("The Sisters of Mercy") are unchanged.

Usage:
    python -m app.services.redistribute_disguised_in_black --dry-run
    python -m app.services.redistribute_disguised_in_black            # apply for real
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "The Sisters of Mercy"
SOURCE_ALBUM = "Disguised in Black"

# Target album MBIDs (verified against the album_art / scrobble MBIDs).
FHLAA = "05c0940f-9260-4f91-8235-2dec6aab4fef"               # First and Last and Always
FHLAA_NAME = "First and Last and Always"
SGWBM = "9643ead9-b88c-365a-a305-2eaf195c6e2a"               # Some Girls Wander by Mistake
SGWBM_NAME = "Some Girls Wander by Mistake"
FLOODLAND_COLLECTION = "040ee1a5-67ec-49b2-9fd5-9b87a6e350ac"
FLOODLAND_COLLECTION_NAME = "Floodland Collection"
FHLAA_COLLECTION = "52d53c4b-aa81-4201-bb00-35b4f5a9b47a"
FHLAA_COLLECTION_NAME = "First and Last and Always Collection"

# Exact track -> (target album, target MBID). Explicit lookup (not a regex) so
# every transformation is auditable and no surprise track gets moved. Any track
# found on the source album that is NOT in this map is reported and left alone.
TRACK_TO_ALBUM = {
    # --- First and Last and Always (verified against its tracklist) ---
    "A Rock and a Hard Place": (FHLAA_NAME, FHLAA),
    "Marian": (FHLAA_NAME, FHLAA),
    "No Time to Cry": (FHLAA_NAME, FHLAA),
    "Possession": (FHLAA_NAME, FHLAA),
    "Walk Away": (FHLAA_NAME, FHLAA),
    "Logic": (FHLAA_NAME, FHLAA),                 # 6 existing FHLAA scrobbles
    # Bootleg-only, no clean tracklist match -> closest official home (FHLAA)
    "First & Last & Always": (FHLAA_NAME, FHLAA),       # FHLAA title track ("and"->"&")
    "Nine While Nine Ghostrider": (FHLAA_NAME, FHLAA),  # Nine While Nine / Ghostrider medley
    "Body & Soul": (FHLAA_NAME, FHLAA),                 # no match; user-routed to FHLAA
    # --- Some Girls Wander by Mistake (verified against its tracklist) ---
    "Alice": (SGWBM_NAME, SGWBM),
    "Body Electric": (SGWBM_NAME, SGWBM),
    "Burn": (SGWBM_NAME, SGWBM),
    "Floorshow": (SGWBM_NAME, SGWBM),
    "Gimme Shelter": (SGWBM_NAME, SGWBM),
    # --- Compilation homes (only place these tracks chart) ---
    "Emma": (FLOODLAND_COLLECTION_NAME, FLOODLAND_COLLECTION),       # tracklist #15
    "Train": (FHLAA_COLLECTION_NAME, FHLAA_COLLECTION),             # tracklist #13
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


def redistribute(dry_run: bool = True) -> dict:
    conn = get_db_connection()

    # Distinct tracks currently on the source album.
    source_tracks = [
        r["track"]
        for r in conn.execute(
            "SELECT DISTINCT track FROM scrobble WHERE artist = ? AND album = ? ORDER BY track",
            (ARTIST, SOURCE_ALBUM),
        ).fetchall()
    ]

    unmapped = [t for t in source_tracks if t not in TRACK_TO_ALBUM]
    for t in unmapped:
        logger.warning("Unmapped track on %s, leaving untouched: %r", SOURCE_ALBUM, t)

    rows = conn.execute(
        """
        SELECT id, album, track, uts FROM scrobble
        WHERE artist = ? AND album = ?
        ORDER BY track, uts
        """,
        (ARTIST, SOURCE_ALBUM),
    ).fetchall()

    moved = 0
    skipped_integrity = 0
    detail = []

    for scrobble in rows:
        track = scrobble["track"]
        target = TRACK_TO_ALBUM.get(track)
        if target is None:
            continue  # reported above as unmapped
        target_album, target_mbid = target

        if dry_run:
            detail.append((scrobble["id"], track, target_album))
            moved += 1
            continue

        try:
            conn.execute(
                """
                UPDATE scrobble
                SET album = ?, album_mbid = ?, album_id = NULL, track_id = NULL
                WHERE id = ?
                """,
                (target_album, target_mbid, scrobble["id"]),
            )
            moved += 1
            detail.append((scrobble["id"], track, target_album))
        except sqlite3.IntegrityError:
            # Collision on unique (uts, artist, album, track): a scrobble for
            # this track on the target album already exists at this timestamp.
            # Skip and log.
            skipped_integrity += 1
            logger.warning(
                "IntegrityError: skipped scrobble %s (%r) - a scrobble for %r "
                "on %r at uts=%s already exists",
                scrobble["id"], track, track, target_album, scrobble["uts"],
            )

    if not dry_run:
        conn.commit()
    conn.close()

    logger.info(
        "%s: %d scrobble(s) %s (%d integrity skips, %d unmapped tracks).",
        "[DRY RUN]" if dry_run else "DONE",
        moved,
        "to update" if dry_run else "updated",
        skipped_integrity,
        len(unmapped),
    )

    return {
        "dry_run": dry_run,
        "moved": moved,
        "skipped_integrity": skipped_integrity,
        "unmapped_tracks": unmapped,
        "detail": detail,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Route Sisters of Mercy 'Disguised in Black' (bootleg) scrobbles "
        "to their official albums."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = redistribute(dry_run=args.dry_run)
    prefix = "[DRY RUN] " if result["dry_run"] else ""

    print(f"{prefix}Scrobbles {'to update' if args.dry_run else 'updated'}: {result['moved']}")
    print(f"{prefix}Integrity skips: {result['skipped_integrity']}")

    if result["unmapped_tracks"]:
        print(f"{prefix}Unmapped tracks left untouched:")
        for t in result["unmapped_tracks"]:
            print(f"    - {t}")

    print(f"{prefix}Transformations (id: track -> target album):")
    for sid, track, target_album in result["detail"]:
        print(f"    {sid}: {track!r} -> {target_album!r}")

    if not args.dry_run and result["moved"]:
        print(
            "\nRun `python -m app.services.seed_entities` to repopulate the "
            "now-NULL album_id/track_id columns."
        )
    return 0


if __name__ == "__main__":
    main()
