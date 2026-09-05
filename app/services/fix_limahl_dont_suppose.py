#!/usr/bin/env python3
"""Correct Limahl's Don't Suppose to MusicBrainz release 3dbd3d32....

The target is the official 2009 worldwide Digital Media release with 15
tracks. The command previews by default; pass ``--apply`` to commit.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db.entities import Resolver


DEFAULT_DB = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
ARTIST = "Limahl"
ALBUM = "Don't Suppose"
ARTIST_MBID = "ba147912-dc39-416f-9e4b-09765d671674"
RELEASE_MBID = "3dbd3d32-d79f-439a-ba10-17d1e5ef3c97"
RELEASE_YEAR = 2009

# MusicBrainz release-track titles passed through sync_lastfm.clean_title(),
# paired with their recording MBIDs.
TRACKS = (
    (1, "Don't Suppose", "e6968cac-6a4a-47be-b167-f5fa70361801"),
    (2, "That Special Something", "1474688a-b6c4-4aa8-894d-37f2f9027557"),
    (3, "Your Love", "3884a400-9101-4f4b-91fb-dd7047682a85"),
    (4, "Too Much Trouble", "a213a5f5-50fb-41fd-8ab1-7807fb9a9b88"),
    (5, "Never Ending Story", "360af6e3-6c05-4e96-8623-8e2650780341"),
    (6, "Only for Love", "47fc4555-16d9-4e5b-989b-1b8cb958e7b1"),
    (7, "I Was a Fool", "5ad7165b-16cf-4ac7-b736-5288b1a044fe"),
    (8, "The Waiting Game", "1b309c6d-00fd-46ce-8d6b-bde6f33411b8"),
    (9, "Tar Beach", "3ef51a78-cc86-4ac1-a5ff-374b62069c1e"),
    (10, "Oh Girl", "027c7326-051f-47a9-8dbf-85c43be53d55"),
    (11, "O.T.T. (Over the Top)", "ba507a53-0764-4579-8c48-4607fe0b3b8e"),
    (12, "Only for Love (Dance Mix)", "dc0106bd-0dd7-4103-8be7-8fa954f9c799"),
    (13, "Only for Love (Dub Mix)", "395897e4-3fd0-4cab-b3c2-9581dc3ab398"),
    (14, "You've Been Gone for a Little While", "a6eb8013-7629-4503-91b3-0a2f97a51374"),
    (15, "Never Ending Story (12'' Dance Mix)", "cfedd97e-36fb-4a1f-b017-dada6329c616"),
)


def correct_release(conn: sqlite3.Connection) -> dict[str, int]:
    """Apply the correction inside the caller's transaction."""
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")

    artist = conn.execute(
        "SELECT artist_id FROM artist WHERE name = ?", (ARTIST,)
    ).fetchone()
    if artist is None:
        raise RuntimeError(f"canonical artist not found: {ARTIST}")
    artist_id = artist["artist_id"]

    album = conn.execute(
        """
        SELECT album.album_id
        FROM album
        JOIN album_alias ON album_alias.album_id = album.album_id
        WHERE album_alias.artist_id = ? AND album_alias.norm_title = 'dont suppose'
        """,
        (artist_id,),
    ).fetchone()
    if album is None:
        raise RuntimeError(f"canonical album not found: {ARTIST} - {ALBUM}")
    album_id = album["album_id"]

    conn.execute(
        "UPDATE artist SET mbid = ? WHERE artist_id = ?",
        (ARTIST_MBID, artist_id),
    )
    conn.execute(
        "UPDATE album SET title = ?, mbid = ? WHERE album_id = ?",
        (ALBUM, RELEASE_MBID, album_id),
    )
    art_updated = conn.execute(
        """
        UPDATE album_art
        SET album_mbid = ?, artist_mbid = ?, year_col = ?,
            artist_id = ?, album_id = ?
        WHERE artist = ? AND album = ?
        """,
        (RELEASE_MBID, ARTIST_MBID, RELEASE_YEAR, artist_id, album_id, ARTIST, ALBUM),
    ).rowcount
    scrobbles_updated = conn.execute(
        """
        UPDATE scrobble
        SET album_mbid = ?, artist_mbid = ?, artist_id = ?, album_id = ?,
            album_artist = ?
        WHERE artist = ? AND album = ?
        """,
        (RELEASE_MBID, ARTIST_MBID, artist_id, album_id, ARTIST, ARTIST, ALBUM),
    ).rowcount

    old_tracks = conn.execute(
        "DELETE FROM album_tracks WHERE artist = ? AND album = ?",
        (ARTIST, ALBUM),
    ).rowcount

    resolver = Resolver(conn)
    primary_recording_by_track_id: dict[int, tuple[str, str]] = {}
    track_rows = []
    track_ids_by_title = {}
    for number, title, recording_mbid in TRACKS:
        track_id = resolver.resolve_track_id(artist_id, title, recording_mbid)
        track_ids_by_title[title] = track_id
        primary_recording_by_track_id.setdefault(track_id, (title, recording_mbid))
        track_rows.append(
            (
                ARTIST,
                ALBUM,
                title,
                number,
                recording_mbid,
                RELEASE_MBID,
                artist_id,
                album_id,
                track_id,
            )
        )

    # Track entities intentionally merge normalized versions. Preserve the
    # first/base recording as the entity hint, while each album_tracks row
    # retains the exact recording MBID for that release position.
    for track_id, (title, recording_mbid) in primary_recording_by_track_id.items():
        conn.execute(
            "UPDATE track SET title = ?, mbid = ? WHERE track_id = ?",
            (title, recording_mbid, track_id),
        )

    conn.executemany(
        """
        INSERT INTO album_tracks
            (artist, album, track, track_number, track_mbid, album_mbid,
             artist_id, album_id, track_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        track_rows,
    )

    scrobble_tracks_updated = 0
    for _, title, recording_mbid in TRACKS:
        scrobble_tracks_updated += conn.execute(
            """
            UPDATE scrobble
            SET track_mbid = ?, track_id = ?
            WHERE artist = ? AND album = ? AND track = ?
            """,
            (recording_mbid, track_ids_by_title[title], ARTIST, ALBUM, title),
        ).rowcount

    stale_resolutions_deleted = conn.execute(
        "DELETE FROM track_mismatch_resolution WHERE artist = ? AND album = ?",
        (ARTIST, ALBUM),
    ).rowcount
    notifications_dismissed = conn.execute(
        """
        UPDATE notifications
        SET dismissed_at = unixepoch()
        WHERE type = 'track_mismatch' AND dismissed_at IS NULL
          AND json_extract(details, '$.artist') = ?
          AND json_extract(details, '$.album') = ?
        """,
        (ARTIST, ALBUM),
    ).rowcount

    actual = conn.execute(
        """
        SELECT COUNT(*) AS count, MIN(track_number) AS first,
               MAX(track_number) AS last,
               COUNT(DISTINCT album_mbid) AS release_count
        FROM album_tracks WHERE artist = ? AND album = ?
        """,
        (ARTIST, ALBUM),
    ).fetchone()
    if tuple(actual) != (15, 1, 15, 1):
        raise RuntimeError(f"post-correction tracklist validation failed: {tuple(actual)}")
    wrong_mbid = conn.execute(
        """
        SELECT COUNT(*) FROM album_tracks
        WHERE artist = ? AND album = ? AND album_mbid != ?
        """,
        (ARTIST, ALBUM, RELEASE_MBID),
    ).fetchone()[0]
    if wrong_mbid:
        raise RuntimeError(f"{wrong_mbid} tracklist rows have the wrong release MBID")

    return {
        "album_art_rows_updated": art_updated,
        "scrobbles_updated": scrobbles_updated,
        "scrobble_tracks_updated": scrobble_tracks_updated,
        "old_tracklist_rows_removed": old_tracks,
        "new_tracklist_rows_inserted": len(track_rows),
        "stale_resolutions_deleted": stale_resolutions_deleted,
        "notifications_dismissed": notifications_dismissed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with sqlite3.connect(args.database) as conn:
        conn.execute("BEGIN IMMEDIATE")
        summary = correct_release(conn)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
    for key, value in summary.items():
        print(f"{key}: {value}")
    print("APPLIED" if args.apply else "DRY RUN: no changes committed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
