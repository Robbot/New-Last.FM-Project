#!/usr/bin/env python3
"""Safely reassign one rare scrobble to an existing canonical album track.

The destination must already exist in ``artist``, ``album``, and
``album_tracks``.  All denormalized identity fields and IDs are copied from
those canonical records; MBIDs fall back to ``album_art``/``track`` only when
the album-track row does not contain them.

The command is a verified dry run unless ``--apply`` is supplied.  Use the
immutable scrobble ID rather than matching on mutable artist/title text:

    python -m app.services.reassign_rare_scrobble \
        --scrobble-id 168704 \
        --artist "Joy Division" \
        --album "Substance" \
        --track "Love Will Tear Us Apart"

After reviewing the preview, back up the database and repeat with ``--apply``.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"
DISPLAY_FIELDS = (
    "artist",
    "artist_mbid",
    "album_artist",
    "album",
    "album_mbid",
    "track",
    "track_mbid",
    "artist_id",
    "album_id",
    "track_id",
)


def _resolve_target(
    conn: sqlite3.Connection, artist: str, album: str, track: str
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT ar.name AS artist,
               ar.mbid AS artist_mbid,
               ar.name AS album_artist,
               a.title AS album,
               COALESCE(NULLIF(at.album_mbid, ''), NULLIF(a.mbid, ''),
                        NULLIF(aa.album_mbid, '')) AS album_mbid,
               at.track AS track,
               COALESCE(NULLIF(at.track_mbid, ''), NULLIF(t.mbid, '')) AS track_mbid,
               ar.artist_id,
               a.album_id,
               at.track_id
        FROM artist ar
        JOIN album a
          ON a.artist_id = ar.artist_id
        JOIN album_tracks at
          ON at.artist_id = ar.artist_id AND at.album_id = a.album_id
        LEFT JOIN track t
          ON t.track_id = at.track_id
        LEFT JOIN album_art aa
          ON aa.album_id = a.album_id
        WHERE ar.name = ? AND a.title = ? AND at.track = ?
        """,
        (artist, album, track),
    ).fetchall()
    if not row:
        raise RuntimeError(
            f"Canonical destination not found: {artist!r} / {album!r} / {track!r}"
        )
    if len(row) != 1:
        raise RuntimeError(f"Destination is ambiguous ({len(row)} matching rows)")

    target = dict(row[0])
    missing = [
        field
        for field in ("artist_mbid", "album_mbid", "track_mbid", "track_id")
        if not target[field]
    ]
    if missing:
        raise RuntimeError(
            "Canonical destination lacks required identity fields: " + ", ".join(missing)
        )
    return target


def _format_row(label: str, row: dict[str, Any]) -> None:
    print(label)
    for field in DISPLAY_FIELDS:
        print(f"  {field:12} {row.get(field)!r}")


def reassign(
    database: Path,
    scrobble_id: int,
    artist: str,
    album: str,
    track: str,
    *,
    apply: bool,
) -> None:
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        source_row = conn.execute(
            "SELECT * FROM scrobble WHERE id = ?", (scrobble_id,)
        ).fetchone()
        if source_row is None:
            raise RuntimeError(f"Scrobble ID {scrobble_id} does not exist")
        source = dict(source_row)
        target = _resolve_target(conn, artist, album, track)

        collision = conn.execute(
            """
            SELECT id FROM scrobble
            WHERE id != ? AND uts = ? AND artist = ? AND track = ?
            """,
            (scrobble_id, source["uts"], target["artist"], target["track"]),
        ).fetchone()
        if collision:
            raise RuntimeError(
                f"Reassignment would collide with scrobble ID {collision['id']}"
            )

        _format_row("Before:", source)
        _format_row("Destination:", target)

        assignments = ", ".join(f"{field} = ?" for field in DISPLAY_FIELDS)
        params = [target[field] for field in DISPLAY_FIELDS]
        result = conn.execute(
            f"UPDATE scrobble SET {assignments} WHERE id = ?",  # fixed field names
            (*params, scrobble_id),
        )
        if result.rowcount != 1:
            raise RuntimeError(f"Expected to update 1 row; updated {result.rowcount}")

        updated = dict(
            conn.execute("SELECT * FROM scrobble WHERE id = ?", (scrobble_id,)).fetchone()
        )
        mismatches = [
            field for field in DISPLAY_FIELDS if updated[field] != target[field]
        ]
        if mismatches:
            raise RuntimeError("Post-update verification failed: " + ", ".join(mismatches))

        if apply:
            conn.commit()
            print(f"Applied: scrobble {scrobble_id} reassigned and verified.")
        else:
            conn.rollback()
            print("Dry run verified; transaction rolled back. Repeat with --apply after backup.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--scrobble-id", type=int, required=True)
    parser.add_argument("--artist", required=True)
    parser.add_argument("--album", required=True)
    parser.add_argument("--track", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the verified reassignment (default: dry run and rollback)",
    )
    args = parser.parse_args()
    reassign(
        args.database,
        args.scrobble_id,
        args.artist,
        args.album,
        args.track,
        apply=args.apply,
    )


if __name__ == "__main__":
    main()
