#!/usr/bin/env python3
"""
Redistribute Tin Machine - "Live - Oy Vey, Baby" scrobbles to their original
studio albums.

"Live - Oy Vey, Baby" (album_mbid 60dde5c1-e0a3-47de-914d-5c7b77caa604) is a
Tin Machine live album whose tracks are all originals drawn from the two studio
albums. Routing each scrobble back to the studio album it came from stops the
play counts being stranded under the live album.

The two studio albums:
    Tin Machine    (mbid 1ac8dc32-91c4-4010-8021-3f08d4c75354, album_id 1621)
    Tin Machine II (mbid 3307d456-af89-4e9b-b621-5cefc5e05d62, album_id 3337)

One track is a name-variant split: the live scrobble "You Belong In Rock & Roll"
(track_id 25234) must become the studio-canonical "You Belong in Rock n' Roll"
(track_id 24749) or it will not join the Tin Machine II tracklist on the album
page. So that row additionally repoints its track_id + the
"you belong in rock & roll" alias to 24749, and the orphan entity 25234 is
deleted afterwards (it had only this one scrobble).

Per matched scrobble row the script sets, with explicit canonical values:
    track      -> studio-canonical name (renamed only for the & / n' variant)
    album      -> the original studio album
    album_mbid -> that album's MBID
    album_id   -> that album's canonical album_id
    track_id   -> the studio track's canonical track_id

The now-empty source album "Live - Oy Vey, Baby" (album_art, album_tracks,
album entity + alias) is intentionally left in place, matching the other
redistribute_* scripts; it simply becomes a zero-scrobble album.

Usage:
    python -m app.services.redistribute_oy_vey_baby --dry-run
    python -m app.services.redistribute_oy_vey_baby            # apply for real
"""

import argparse
import sqlite3
from pathlib import Path

from app.logging_config import get_logger

logger = get_logger(__name__)

ARTIST = "Tin Machine"
SOURCE_ALBUM = "Live - Oy Vey, Baby"

TIN_MACHINE = "Tin Machine"
TIN_MACHINE_II = "Tin Machine II"
MBID_I = "1ac8dc32-91c4-4010-8021-3f08d4c75354"
MBID_II = "3307d456-af89-4e9b-b621-5cefc5e05d62"
ALBUM_ID_I = 1621
ALBUM_ID_II = 3337

# Tracks that need their name variant merged into the studio entity.
#   "You Belong In Rock & Roll" (live tag, & ) -> "You Belong in Rock n' Roll"
#   (studio tracklist, n'). Entity 25234 merges into 24749.
TRACK_RENAME = {
    "You Belong In Rock & Roll": "You Belong in Rock n' Roll",
}

# Source track name -> (album, album_mbid, album_id, track_id).
# track_id is the studio tracklist's canonical entity; for the six exact-name
# matches it already equals what the live scrobbles carry, for the & / n'
# variant it is the merge target 24749.
ROUTING = {
    "Amazing": (TIN_MACHINE, MBID_I, ALBUM_ID_I, 9272),
    "Heaven's in Here": (TIN_MACHINE, MBID_I, ALBUM_ID_I, 9271),
    "I Can't Read": (TIN_MACHINE, MBID_I, ALBUM_ID_I, 9273),
    "Under the God": (TIN_MACHINE, MBID_I, ALBUM_ID_I, 9270),
    "Goodbye Mr. Ed": (TIN_MACHINE_II, MBID_II, ALBUM_ID_II, 26892),
    "If There Is Something": (TIN_MACHINE_II, MBID_II, ALBUM_ID_II, 24750),
    "You Belong In Rock & Roll": (TIN_MACHINE_II, MBID_II, ALBUM_ID_II, 24749),
}

# Alias repoint + orphan delete for the & / n' variant merge.
ALIAS_REPOINT = ("you belong in rock & roll", 24749)  # (norm_title, -> track_id)
ORPHAN_TRACK_IDS = (25234,)


def get_db_path() -> str:
    db_path = Path.cwd() / "files" / "lastfmstats.sqlite"
    if db_path.exists():
        return str(db_path)
    raise FileNotFoundError("Database not found at files/lastfmstats.sqlite")


def get_db_connection():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def redistribute(dry_run: bool = True) -> dict:
    conn = get_db_connection()

    # Distinct tracks currently on the source album, to detect anything unmapped.
    source_tracks = [
        r["track"]
        for r in conn.execute(
            "SELECT DISTINCT track FROM scrobble "
            "WHERE artist = ? AND album = ? ORDER BY track",
            (ARTIST, SOURCE_ALBUM),
        ).fetchall()
    ]
    unmapped = [t for t in source_tracks if t not in ROUTING]
    for t in unmapped:
        logger.warning("Unmapped track on %s, leaving untouched: %r", SOURCE_ALBUM, t)

    moved = 0
    skipped_integrity = 0
    detail = []

    rows = conn.execute(
        "SELECT id, track, uts FROM scrobble "
        "WHERE artist = ? AND album = ? ORDER BY track, uts",
        (ARTIST, SOURCE_ALBUM),
    ).fetchall()

    for scrobble in rows:
        src = scrobble["track"]
        if src not in ROUTING:
            continue  # reported above as unmapped
        album, album_mbid, album_id, track_id = ROUTING[src]
        new_track = TRACK_RENAME.get(src, src)

        if dry_run:
            moved += 1
            detail.append(
                (scrobble["id"], src, new_track, album, scrobble["uts"])
            )
            continue
        try:
            conn.execute(
                """
                UPDATE scrobble
                SET track = ?, album = ?, album_mbid = ?,
                    album_id = ?, track_id = ?
                WHERE id = ?
                """,
                (new_track, album, album_mbid, album_id, track_id, scrobble["id"]),
            )
            moved += 1
            detail.append((scrobble["id"], src, new_track, album, scrobble["uts"]))
        except sqlite3.IntegrityError:
            # Collision on unique (uts, artist, album, track): a scrobble for
            # this track on the target album already exists at this timestamp.
            skipped_integrity += 1
            logger.warning(
                "IntegrityError: skipped scrobble %s (%r) - a scrobble for %r "
                "on %r at uts=%s already exists",
                scrobble["id"], src, new_track, album, scrobble["uts"],
            )

    # Merge the & / n' variant entity: repoint its alias, then drop the orphan.
    alias_repointed = 0
    orphans_deleted = 0
    if not dry_run:
        norm_title, target_tid = ALIAS_REPOINT
        cur = conn.execute(
            "UPDATE track_alias SET track_id = ? "
            "WHERE artist_id = (SELECT artist_id FROM artist WHERE name = ?) "
            "AND norm_title = ?",
            (target_tid, ARTIST, norm_title),
        )
        alias_repointed = cur.rowcount
        for orphan in ORPHAN_TRACK_IDS:
            cur = conn.execute(
                "DELETE FROM track WHERE track_id = ?", (orphan,)
            )
            orphans_deleted += cur.rowcount
        conn.commit()
    conn.close()

    logger.info(
        "%s: %d scrobble(s) %s (%d integrity skips, %d unmapped tracks). "
        "Alias repointed=%d, orphan tracks deleted=%d.",
        "[DRY RUN]" if dry_run else "DONE",
        moved,
        "to update" if dry_run else "updated",
        skipped_integrity,
        len(unmapped),
        alias_repointed,
        orphans_deleted,
    )

    return {
        "dry_run": dry_run,
        "moved": moved,
        "skipped_integrity": skipped_integrity,
        "unmapped_tracks": unmapped,
        "alias_repointed": alias_repointed,
        "orphans_deleted": orphans_deleted,
        "detail": detail,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Route Tin Machine 'Live - Oy Vey, Baby' scrobbles back to "
        "their original studio albums (Tin Machine / Tin Machine II)."
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    result = redistribute(dry_run=args.dry_run)

    prefix = "[DRY RUN] " if result["dry_run"] else ""
    print(f"{prefix}Scrobbles {'to update' if args.dry_run else 'updated'}: {result['moved']}")
    print(f"{prefix}Integrity skips: {result['skipped_integrity']}")
    if not args.dry_run:
        print(f"{prefix}Alias rows repointed: {result['alias_repointed']}")
        print(f"{prefix}Orphan track entities deleted: {result['orphans_deleted']}")

    if result["unmapped_tracks"]:
        print(f"{prefix}Unmapped tracks left untouched:")
        for t in result["unmapped_tracks"]:
            print(f"    - {t}")

    print(f"{prefix}Routing (id: source -> new track @ album, uts):")
    for sid, src, new_track, album, uts in result["detail"]:
        arrow = " -> " + repr(new_track) if new_track != src else ""
        print(f"    {sid}: {src!r}{arrow} @ {album}  (uts={uts})")

    if not args.dry_run and result["moved"]:
        print(
            "\nSource album 'Live - Oy Vey, Baby' now has 0 scrobbles; its "
            "album_art / album_tracks / entity rows are intentionally left in place."
        )
    return 0


if __name__ == "__main__":
    main()
