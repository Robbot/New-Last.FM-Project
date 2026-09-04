#!/usr/bin/env python3
"""Review and resolve track-mismatch notifications safely.

Mutating commands are previews unless ``--apply`` is supplied. Decisions are
album-scoped and persisted in ``track_mismatch_resolution`` so later Last.fm
syncs do not recreate the same issue.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.db.entities import Resolver
from app.services.migrate_entity_tables import ensure_entity_schema


DEFAULT_DB = Path(__file__).resolve().parents[2] / "files" / "lastfmstats.sqlite"


@dataclass(frozen=True)
class ResolutionResult:
    action: str
    artist: str
    album: str
    source_track: str
    canonical_track: str | None
    scrobbles_updated: int = 0
    album_tracks_added: int = 0
    album_tracks_shifted: int = 0
    notifications_dismissed: int = 0
    dry_run: bool = True


def _notification_details(conn: sqlite3.Connection, notification_id: int) -> dict:
    row = conn.execute(
        "SELECT type, details FROM notifications WHERE id = ?", (notification_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"notification {notification_id} does not exist")
    if row["type"] != "track_mismatch":
        raise ValueError(f"notification {notification_id} is not a track mismatch")
    try:
        details = json.loads(row["details"] or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"notification {notification_id} has invalid details") from exc
    required = ("artist", "album", "scrobble_track")
    missing = [key for key in required if not details.get(key)]
    if missing:
        raise ValueError(
            f"notification {notification_id} is missing: {', '.join(missing)}"
        )
    return details


def _record_decision(
    conn: sqlite3.Connection,
    details: dict,
    action: str,
    canonical_track: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO track_mismatch_resolution
            (artist, album, source_track, action, canonical_track)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(artist, album, source_track) DO UPDATE SET
            action = excluded.action,
            canonical_track = excluded.canonical_track,
            created_at = CURRENT_TIMESTAMP
        """,
        (
            details["artist"],
            details["album"],
            details["scrobble_track"],
            action,
            canonical_track,
        ),
    )


def _dismiss_matching_notifications(conn: sqlite3.Connection, details: dict) -> int:
    return conn.execute(
        """
        UPDATE notifications
        SET dismissed_at = ?
        WHERE type = 'track_mismatch'
          AND dismissed_at IS NULL
          AND json_extract(details, '$.artist') = ?
          AND json_extract(details, '$.album') = ?
          AND json_extract(details, '$.scrobble_track') = ?
        """,
        (
            int(time.time()),
            details["artist"],
            details["album"],
            details["scrobble_track"],
        ),
    ).rowcount


def _finish(conn: sqlite3.Connection, *, dry_run: bool) -> None:
    if dry_run:
        conn.execute("ROLLBACK TO track_mismatch_resolution")
    conn.execute("RELEASE track_mismatch_resolution")


def _abort(conn: sqlite3.Connection) -> None:
    conn.execute("ROLLBACK TO track_mismatch_resolution")
    conn.execute("RELEASE track_mismatch_resolution")


def map_mismatch(
    conn: sqlite3.Connection,
    notification_id: int,
    canonical_track: str,
    *,
    dry_run: bool = True,
) -> ResolutionResult:
    """Map one album-scoped source title to an existing canonical track."""
    canonical_track = canonical_track.strip()
    if not canonical_track:
        raise ValueError("canonical track title cannot be empty")
    details = _notification_details(conn, notification_id)
    conn.execute("SAVEPOINT track_mismatch_resolution")
    try:
        album_track = conn.execute(
            """
            SELECT track_id, track_mbid, artist_id, album_id
            FROM album_tracks
            WHERE artist = ? AND album = ? AND track = ?
            """,
            (details["artist"], details["album"], canonical_track),
        ).fetchone()
        if album_track is None:
            raise ValueError(
                f"{canonical_track!r} is not in album_tracks for "
                f"{details['artist']} - {details['album']}; use add-to-tracklist"
            )

        sample = conn.execute(
            """
            SELECT artist_id, album_id
            FROM scrobble
            WHERE artist = ? AND album = ? AND track = ?
            LIMIT 1
            """,
            (details["artist"], details["album"], details["scrobble_track"]),
        ).fetchone()
        resolver = Resolver(conn)
        artist_id = album_track["artist_id"] or (sample["artist_id"] if sample else None)
        if artist_id is None:
            artist_id = resolver.resolve_artist_id(details["artist"])

        canonical_track_id = album_track["track_id"]
        if canonical_track_id is None:
            canonical_track_id = resolver.resolve_track_id(
                artist_id, canonical_track, album_track["track_mbid"]
            )
            conn.execute(
                """
                UPDATE album_tracks
                SET track_id = ?
                WHERE artist = ? AND album = ? AND track = ?
                """,
                (
                    canonical_track_id,
                    details["artist"],
                    details["album"],
                    canonical_track,
                ),
            )

        conflicts = conn.execute(
            """
            SELECT COUNT(*)
            FROM scrobble source
            WHERE source.artist = ? AND source.album = ? AND source.track = ?
              AND EXISTS (
                  SELECT 1 FROM scrobble target
                  WHERE target.id != source.id
                    AND target.uts = source.uts
                    AND target.artist = source.artist
                    AND target.track = ?
              )
            """,
            (
                details["artist"],
                details["album"],
                details["scrobble_track"],
                canonical_track,
            ),
        ).fetchone()[0]
        if conflicts:
            raise ValueError(
                f"mapping would collide with {conflicts} existing scrobble(s); "
                "manual duplicate review is required"
            )

        updated = conn.execute(
            """
            UPDATE scrobble
            SET track = ?, track_id = ?,
                track_mbid = COALESCE(?, track_mbid)
            WHERE artist = ? AND album = ? AND track = ?
            """,
            (
                canonical_track,
                canonical_track_id,
                album_track["track_mbid"],
                details["artist"],
                details["album"],
                details["scrobble_track"],
            ),
        ).rowcount
        _record_decision(conn, details, "map", canonical_track)
        dismissed = _dismiss_matching_notifications(conn, details)
        result = ResolutionResult(
            action="map",
            artist=details["artist"],
            album=details["album"],
            source_track=details["scrobble_track"],
            canonical_track=canonical_track,
            scrobbles_updated=updated,
            notifications_dismissed=dismissed,
            dry_run=dry_run,
        )
        _finish(conn, dry_run=dry_run)
        return result
    except Exception:
        _abort(conn)
        raise


def add_to_tracklist(
    conn: sqlite3.Connection,
    notification_id: int,
    track_number: int,
    *,
    shift_existing: bool = False,
    dry_run: bool = True,
) -> ResolutionResult:
    """Accept the incoming title by adding it to the stored album tracklist."""
    if track_number < 1:
        raise ValueError("track number must be at least 1")
    details = _notification_details(conn, notification_id)
    conn.execute("SAVEPOINT track_mismatch_resolution")
    try:
        collision = conn.execute(
            """
            SELECT track FROM album_tracks
            WHERE artist = ? AND album = ? AND track_number = ?
            """,
            (details["artist"], details["album"], track_number),
        ).fetchone()
        if (
            collision
            and collision["track"] != details["scrobble_track"]
            and not shift_existing
        ):
            raise ValueError(
                f"track number {track_number} is already used by {collision['track']!r}; "
                "use --shift-existing only after confirming the tracklist gap"
            )

        existing = conn.execute(
            """
            SELECT 1 FROM album_tracks
            WHERE artist = ? AND album = ? AND track = ?
            """,
            (details["artist"], details["album"], details["scrobble_track"]),
        ).fetchone()
        added = 0
        shifted = 0
        if existing is None:
            if collision and shift_existing:
                # Negate first so schemas with a unique (artist, album,
                # track_number) key cannot collide while numbers move upward.
                shifted = conn.execute(
                    """
                    UPDATE album_tracks SET track_number = -track_number
                    WHERE artist = ? AND album = ? AND track_number >= ?
                    """,
                    (details["artist"], details["album"], track_number),
                ).rowcount
                conn.execute(
                    """
                    UPDATE album_tracks SET track_number = (-track_number) + 1
                    WHERE artist = ? AND album = ? AND track_number <= ?
                    """,
                    (details["artist"], details["album"], -track_number),
                )
            sample = conn.execute(
                """
                SELECT artist_id, album_id, track_id, track_mbid
                FROM scrobble
                WHERE artist = ? AND album = ? AND track = ?
                LIMIT 1
                """,
                (details["artist"], details["album"], details["scrobble_track"]),
            ).fetchone()
            resolver = Resolver(conn)
            artist_id = sample["artist_id"] if sample else None
            if artist_id is None:
                artist_id = resolver.resolve_artist_id(details["artist"])
            album_id = sample["album_id"] if sample else None
            if album_id is None:
                album_id = resolver.resolve_album_id(artist_id, details["album"])
            track_id = sample["track_id"] if sample else None
            if track_id is None:
                track_id = resolver.resolve_track_id(
                    artist_id,
                    details["scrobble_track"],
                    details.get("track_mbid"),
                )
            conn.execute(
                """
                INSERT INTO album_tracks
                    (artist, album, track, track_number, track_mbid,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    details["artist"], details["album"],
                    details["scrobble_track"], track_number,
                    details.get("track_mbid"), artist_id, album_id, track_id,
                ),
            )
            added = 1

        _record_decision(conn, details, "add", details["scrobble_track"])
        dismissed = _dismiss_matching_notifications(conn, details)
        result = ResolutionResult(
            action="add",
            artist=details["artist"],
            album=details["album"],
            source_track=details["scrobble_track"],
            canonical_track=details["scrobble_track"],
            album_tracks_added=added,
            album_tracks_shifted=shifted,
            notifications_dismissed=dismissed,
            dry_run=dry_run,
        )
        _finish(conn, dry_run=dry_run)
        return result
    except Exception:
        _abort(conn)
        raise


def keep_mismatch(
    conn: sqlite3.Connection,
    notification_id: int,
    *,
    dry_run: bool = True,
) -> ResolutionResult:
    """Accept a distinct source title without adding it to this tracklist."""
    details = _notification_details(conn, notification_id)
    conn.execute("SAVEPOINT track_mismatch_resolution")
    try:
        _record_decision(conn, details, "keep")
        dismissed = _dismiss_matching_notifications(conn, details)
        result = ResolutionResult(
            action="keep",
            artist=details["artist"],
            album=details["album"],
            source_track=details["scrobble_track"],
            canonical_track=None,
            notifications_dismissed=dismissed,
            dry_run=dry_run,
        )
        _finish(conn, dry_run=dry_run)
        return result
    except Exception:
        _abort(conn)
        raise


def list_mismatches(conn: sqlite3.Connection) -> list[dict]:
    """Return one row per unique active mismatch, newest first."""
    rows = conn.execute(
        """
        SELECT MAX(id) AS notification_id,
               json_extract(details, '$.artist') AS artist,
               json_extract(details, '$.album') AS album,
               json_extract(details, '$.scrobble_track') AS source_track,
               COUNT(*) AS repeated_notifications,
               MAX(created_at) AS newest_at
        FROM notifications
        WHERE type = 'track_mismatch' AND dismissed_at IS NULL
        GROUP BY artist, album, source_track
        ORDER BY newest_at DESC, artist, album, source_track
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list unique active mismatches")

    map_parser = sub.add_parser("map", help="map a variant to an existing track")
    map_parser.add_argument("notification_id", type=int)
    map_parser.add_argument("--to", required=True, dest="canonical_track")
    map_parser.add_argument("--apply", action="store_true")

    add_parser = sub.add_parser(
        "add-to-tracklist", help="add the incoming title to the album tracklist"
    )
    add_parser.add_argument("notification_id", type=int)
    add_parser.add_argument("--track-number", type=int, required=True)
    add_parser.add_argument(
        "--shift-existing",
        action="store_true",
        help="shift this and later track numbers up by one before inserting",
    )
    add_parser.add_argument("--apply", action="store_true")

    keep_parser = sub.add_parser(
        "keep", help="accept an intentionally distinct title for this album"
    )
    keep_parser.add_argument("notification_id", type=int)
    keep_parser.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if not args.database.exists():
        raise SystemExit(f"database not found: {args.database}")
    with sqlite3.connect(args.database) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        ensure_entity_schema(conn)
        if args.command == "list":
            results = list_mismatches(conn)
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0
        dry_run = not args.apply
        if args.command == "map":
            result = map_mismatch(
                conn, args.notification_id, args.canonical_track, dry_run=dry_run
            )
        elif args.command == "add-to-tracklist":
            result = add_to_tracklist(
                conn,
                args.notification_id,
                args.track_number,
                shift_existing=args.shift_existing,
                dry_run=dry_run,
            )
        else:
            result = keep_mismatch(conn, args.notification_id, dry_run=dry_run)
        if not dry_run:
            conn.commit()
        print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
        if dry_run:
            print("DRY RUN: rerun with --apply to commit this resolution")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
