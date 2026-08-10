#!/usr/bin/env python3
"""
Redistribute Sex Pistols - "Flogging a Dead Horse" scrobbles to their native
albums: "Never Mind the Bollocks, Here's the Sex Pistols" and
"The Great Rock 'n' Roll Swindle".

"Flogging a Dead Horse" (1979) is a compilation whose tracks each originated on
one of the two studio-era albums. Routing each scrobble to its native album by
TRACK NAME un-strands the plays from the compilation.

Routing (verified against the cached album_tracks tracklists + scrobble
track_ids; user-confirmed disposition of the B-sides):

  -> Never Mind the Bollocks, Here's the Sex Pistols (006759fd):
       God Save the Queen, Holidays in the Sun, Pretty Vacant        [track_id match]
       No Fun, Satellite, Did You No Wrong, Do You No Wrong, Buddies [B-sides of the
       Anarchy / Holidays / Pretty Vacant singles -> closest native home, per user]

  -> The Great Rock 'n' Roll Swindle (21a1a227):
       (I'm Not Your) Stepping Stone, I Wanna Be Me, Anarchy in the UK,
       C'mon Everybody, My Way, Silly Thing, Something Else          [track_id match]
       (I'm Not Your) Steppin' Stone, Great Rock 'n' Roll Swindle,
       No One Is Innocent (The Biggest Blow)                          [name-variants]

Unlike redistribute_disguised_in_black.py (which NULLs album_id/track_id and
re-runs seed_entities), this script PRESERVES track_id and resolves album_id via
the Resolver. Reason: "Anarchy in the UK" exists as TWO track entities —
Bollocks' "Anarchy in the U.K." (7173) and Swindle's "Anarchy in the UK"
(21847). A reseed would re-resolve by name and could mis-merge the two; the
scrobble's existing track_id already encodes the correct entity, so we keep it
and only fix the album association (text + album_mbid + album_id together, per
the move-scrobble contract — update all three or the move is invisible).

The source album "Flogging a Dead Horse" is left as a 0-scrobble album (entity,
art and tracklist intact), matching how redistribute_disguised_in_black.py left
its bootleg. Folding/deleting the empty album is a separate step.

Any track on the source album that is NOT in TRACK_TO_ALBUM is reported and left
untouched.

Usage:
    python -m app.services.redistribute_flogging_a_dead_horse --dry-run
    python -m app.services.redistribute_flogging_a_dead_horse            # apply for real
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger
from app.db.entities import Resolver

logger = get_logger(__name__)

ARTIST = "Sex Pistols"
ARTIST_MBID = "e5db18cb-4b1f-496d-a308-548b611090d3"
SOURCE_ALBUM = "Flogging a Dead Horse"

BOLLOCKS = "Never Mind the Bollocks, Here's the Sex Pistols"
BOLLOCKS_MBID = "006759fd-4956-4f52-9c7c-ea373454ea95"

SWINDLE = "The Great Rock 'n' Roll Swindle"
SWINDLE_MBID = "21a1a227-b765-496e-a2f2-faaa1d9481de"

# Exact track text -> (target album, target MBID). Explicit lookup so every
# transformation is auditable; any track not in this map is reported + skipped.
TRACK_TO_ALBUM = {
    # --- Never Mind the Bollocks (track_id match) ---
    "God Save the Queen": (BOLLOCKS, BOLLOCKS_MBID),
    "Holidays in the Sun": (BOLLOCKS, BOLLOCKS_MBID),
    "Pretty Vacant": (BOLLOCKS, BOLLOCKS_MBID),
    # --- Bollocks-era B-sides (user-routed to closest native home) ---
    "No Fun": (BOLLOCKS, BOLLOCKS_MBID),
    "Satellite": (BOLLOCKS, BOLLOCKS_MBID),
    "Did You No Wrong": (BOLLOCKS, BOLLOCKS_MBID),
    "Do You No Wrong": (BOLLOCKS, BOLLOCKS_MBID),      # typo variant of "Did You No Wrong"
    "Buddies": (BOLLOCKS, BOLLOCKS_MBID),
    # --- The Great Rock 'n' Roll Swindle (track_id match) ---
    "(I'm Not Your) Stepping Stone": (SWINDLE, SWINDLE_MBID),
    "I Wanna Be Me": (SWINDLE, SWINDLE_MBID),
    "Anarchy in the UK": (SWINDLE, SWINDLE_MBID),
    "C'mon Everybody": (SWINDLE, SWINDLE_MBID),
    "My Way": (SWINDLE, SWINDLE_MBID),
    "Silly Thing": (SWINDLE, SWINDLE_MBID),
    "Something Else": (SWINDLE, SWINDLE_MBID),
    # --- Swindle name-variants ---
    "(I'm Not Your) Steppin' Stone": (SWINDLE, SWINDLE_MBID),   # Stepping Stone w/ apostrophe
    "Great Rock 'n' Roll Swindle": (SWINDLE, SWINDLE_MBID),     # title track, missing "The"
    "No One Is Innocent (The Biggest Blow)": (SWINDLE, SWINDLE_MBID),  # parenthetical variant
}


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path.exists():
        return str(db_path)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def redistribute(dry_run: bool = True) -> dict:
    conn = get_db_connection()

    # Resolve canonical album_ids for the two targets via the Resolver (matches
    # what the album page reads). Entities already exist, so no creation occurs.
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id(ARTIST, ARTIST_MBID)
    album_id_of = {
        BOLLOCKS: resolver.resolve_album_id(artist_id, BOLLOCKS, BOLLOCKS_MBID, ARTIST),
        SWINDLE: resolver.resolve_album_id(artist_id, SWINDLE, SWINDLE_MBID, ARTIST),
    }
    logger.info("resolved album_ids: Bollocks=%s Swindle=%s",
                album_id_of[BOLLOCKS], album_id_of[SWINDLE])

    # Distinct tracks currently on the source album.
    source_tracks = [
        r["track"]
        for r in conn.execute(
            "SELECT DISTINCT track FROM scrobble WHERE artist=? AND album=? ORDER BY track",
            (ARTIST, SOURCE_ALBUM),
        ).fetchall()
    ]
    unmapped = [t for t in source_tracks if t not in TRACK_TO_ALBUM]
    for t in unmapped:
        logger.warning("Unmapped track on %s, leaving untouched: %r", SOURCE_ALBUM, t)

    rows = conn.execute(
        """
        SELECT id, album, track, uts FROM scrobble
        WHERE artist=? AND album=?
        ORDER BY track, uts
        """,
        (ARTIST, SOURCE_ALBUM),
    ).fetchall()

    moved = 0
    skipped_integrity = 0
    per_album = {BOLLOCKS: 0, SWINDLE: 0}
    detail = []

    for scrobble in rows:
        track = scrobble["track"]
        target = TRACK_TO_ALBUM.get(track)
        if target is None:
            continue  # reported above as unmapped
        target_album, target_mbid = target
        target_album_id = album_id_of[target_album]

        if dry_run:
            detail.append((scrobble["id"], track, target_album))
            moved += 1
            per_album[target_album] += 1
            continue

        try:
            # Preserve track_id (correct entity already); fix album text +
            # album_mbid + album_id together so the move is visible everywhere.
            conn.execute(
                """
                UPDATE scrobble
                SET album=?, album_mbid=?, album_id=?
                WHERE id=?
                """,
                (target_album, target_mbid, target_album_id, scrobble["id"]),
            )
            moved += 1
            per_album[target_album] += 1
            detail.append((scrobble["id"], track, target_album))
        except sqlite3.IntegrityError:
            # Collision on UNIQUE(uts, artist, album, track): a scrobble for
            # this track on the target album already exists at this timestamp.
            skipped_integrity += 1
            logger.warning(
                "IntegrityError: skipped scrobble %s (%r) - already a %r scrobble "
                "at uts=%s", scrobble["id"], track, target_album, scrobble["uts"],
            )

    if not dry_run:
        conn.commit()
    else:
        # Resolver may have staged alias/entity inserts in dry-run; discard them.
        conn.rollback()
    conn.close()

    logger.info(
        "%s: %d scrobble(s) %s (%d integrity skips, %d unmapped tracks).",
        "[DRY RUN]" if dry_run else "DONE",
        moved, "to update" if dry_run else "updated",
        skipped_integrity, len(unmapped),
    )

    return {
        "dry_run": dry_run,
        "moved": moved,
        "per_album": per_album,
        "skipped_integrity": skipped_integrity,
        "unmapped_tracks": unmapped,
        "detail": detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Route Sex Pistols 'Flogging a Dead Horse' scrobbles to their native albums."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = redistribute(dry_run=args.dry_run)
    prefix = "[DRY RUN] " if result["dry_run"] else ""

    print(f"{prefix}Scrobbles {'to update' if args.dry_run else 'updated'}: {result['moved']}")
    print(f"{prefix}  -> Never Mind the Bollocks: {result['per_album'][BOLLOCKS]}")
    print(f"{prefix}  -> The Great Rock 'n' Roll Swindle: {result['per_album'][SWINDLE]}")
    print(f"{prefix}Integrity skips: {result['skipped_integrity']}")

    if result["unmapped_tracks"]:
        print(f"{prefix}Unmapped tracks left untouched:")
        for t in result["unmapped_tracks"]:
            print(f"    - {t}")

    print(f"{prefix}Transformations (id: track -> target album):")
    for sid, track, target_album in result["detail"]:
        print(f"    {sid}: {track!r} -> {target_album}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
