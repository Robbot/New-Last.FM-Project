#!/usr/bin/env python3
"""
Redistribute Kate Bush "This Woman's Work 1"/"2" scrobbles to proper albums.

"This Woman's Work 1" and "This Woman's Work 2" are non-authoritative grab-bag
album tags (carrying no MBID). Their tracks fall into two groups:

  * Studio-album tracks that were mis-routed here -> moved to their real album,
    verified against the cached album_tracks tracklists.
  * B-sides/rarities that never appeared on a studio album -> consolidated onto
    the 1990 box set "This Woman's Work: Anthology 1978-1990", the release that
    actually collects them.

The track "Ken" (no known Kate Bush recording of that name) was held back from
the map for manual review and has since been moved to the 1990 box set by hand
(via move_scrobble_to_album).

Per matched scrobble row:
    album      -> target album
    album_mbid -> target album MBID
    album_id   -> NULL  (re-resolved by seed_entities afterwards)
    track_id   -> NULL  (re-resolved by seed_entities afterwards)
The track name and album_artist ("Kate Bush") are unchanged.

Usage:
    python -m app.services.redistribute_tww_kate_bush --dry-run
    python -m app.services.redistribute_tww_kate_bush            # apply for real
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Kate Bush"
SOURCE_ALBUMS = ("This Woman's Work 1", "This Woman's Work 2")

# Target album MBIDs, verified against the album_art and musicbrainz_releases
# cache.
KICK_INSIDE = "0b1221cf-002d-475a-a050-748976579ca5"      # The Kick Inside (1978)
HOUNDS_OF_LOVE = "08b76ba2-3253-436e-a734-a1d071b3bae6"   # Hounds of Love (1985)
SENSUAL_WORLD = "2e7f2e63-d069-4e82-ba63-3e606a987c3e"    # The Sensual World (1989)
TWW_ANTHOLOGY = "171c9dc9-8874-32fc-b333-60f58e437e16"    # 1990 box set
TWW_ANTHOLOGY_NAME = "This Woman's Work: Anthology 1978–1990"

# B-sides/rarities -> the 1990 box set (no studio-album home).
B_SIDES = [
    "Warm and Soothing",
    "Under the Ivy",
    "Un Baiser D'Enfant",
    "The Handsome Cabin Boy",
    "The Empty Bullring",
    "Ran Tan Waltz",
    "Passing Through Air",
    "Not This Time",
    "Ne T'En Fui Pas",
    "My Lagan Love",
    "Lord of the Reedy River",
    "December Will Be Magic Again",
    "Burning Bridge",
    "Be Kind to My Mistakes",
    "One Last Look Around the House",
    "I'm Still Waiting",
    "Experiment 4 (12 inch Mix)",
    "Experiment 4",
]

# Exact track -> (target album, target MBID). Explicit lookup (not a regex) so
# every transformation is auditable and no surprise track gets moved. Any track
# found on a source album that is NOT in this map is reported and left untouched.
TRACK_TO_ALBUM = {
    # --- The Kick Inside (1978) ---
    "Wuthering Heights": ("The Kick Inside", KICK_INSIDE),
    "Them Heavy People": ("The Kick Inside", KICK_INSIDE),
    # NOTE: the stored name is truncated mid-word (30 chars, should be
    # "...Like You"); the exact stored value is used here so this scrobble moves
    # and groups with the existing identically-truncated Kick Inside scrobble.
    # The truncation itself is a separate cleanup (see report), not handled here.
    "L'Amour Looks Something Like Y": ("The Kick Inside", KICK_INSIDE),
    "James and the Cold Gun": ("The Kick Inside", KICK_INSIDE),
    # --- Hounds of Love (1985) ---
    "The Big Sky": ("Hounds of Love", HOUNDS_OF_LOVE),
    "Running up That Hill": ("Hounds of Love", HOUNDS_OF_LOVE),
    "Hounds of Love": ("Hounds of Love", HOUNDS_OF_LOVE),
    "Cloudbusting": ("Hounds of Love", HOUNDS_OF_LOVE),
    # --- The Sensual World (1989) ---
    "Walk Straight Down the Middle": ("The Sensual World", SENSUAL_WORLD),
}
# B-sides/rarities -> 1990 box set.
for _track in B_SIDES:
    TRACK_TO_ALBUM[_track] = (TWW_ANTHOLOGY_NAME, TWW_ANTHOLOGY)


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
    placeholders = ",".join("?" for _ in SOURCE_ALBUMS)

    # Distinct tracks currently on the source albums.
    source_tracks = [
        r["track"]
        for r in conn.execute(
            f"""
            SELECT DISTINCT track FROM scrobble
            WHERE artist = ? AND album IN ({placeholders})
            ORDER BY track
            """,
            (ARTIST, *SOURCE_ALBUMS),
        ).fetchall()
    ]

    unmapped = [t for t in source_tracks if t not in TRACK_TO_ALBUM]
    for t in unmapped:
        logger.warning("Unmapped track on %s, leaving untouched: %r", SOURCE_ALBUMS, t)

    rows = conn.execute(
        f"""
        SELECT id, album, track, uts FROM scrobble
        WHERE artist = ? AND album IN ({placeholders})
        ORDER BY album, track, uts
        """,
        (ARTIST, *SOURCE_ALBUMS),
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
            detail.append((scrobble["id"], scrobble["album"], track, target_album))
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
            detail.append((scrobble["id"], scrobble["album"], track, target_album))
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
        description="Route Kate Bush 'This Woman's Work 1/2' scrobbles to their "
        "proper albums (studio albums + the 1990 box set for B-sides)."
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

    print(f"{prefix}Transformations (id: source album / track -> target album):")
    for sid, src_album, track, target_album in result["detail"]:
        print(f"    {sid}: {src_album} / {track!r} -> {target_album!r}")

    if not args.dry_run and result["moved"]:
        print(
            "\nRun `python -m app.services.seed_entities` to repopulate the "
            "now-NULL album_id/track_id columns."
        )
    return 0


if __name__ == "__main__":
    main()
