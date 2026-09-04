"""Persistent decisions for scrobble/album-track mismatches."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class TrackMismatchDecision:
    action: str
    canonical_track: str | None


def get_track_mismatch_decision(
    conn: sqlite3.Connection,
    artist: str,
    album: str,
    source_track: str,
) -> TrackMismatchDecision | None:
    """Return the persisted decision for an exact mismatch identity."""
    try:
        row = conn.execute(
            """
            SELECT action, canonical_track
            FROM track_mismatch_resolution
            WHERE artist = ? AND album = ? AND source_track = ?
            """,
            (artist, album, source_track),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        # A direct-ingest process can briefly run old schema during a rolling
        # deployment. The regular sync creates the table through ensure_schema.
        if "no such table" in str(exc):
            return None
        raise
    if not row:
        return None
    return TrackMismatchDecision(action=row[0], canonical_track=row[1])


def apply_track_mismatch_decision(
    conn: sqlite3.Connection,
    artist: str,
    album: str,
    track: str,
) -> tuple[str, bool]:
    """Return ``(effective_track, suppress_validation)`` for ingest."""
    decision = get_track_mismatch_decision(conn, artist, album, track)
    if decision is None:
        return track, False
    if decision.action == "map":
        return decision.canonical_track or track, False
    if decision.action == "keep":
        return track, True
    # An ``add`` decision is represented by the repaired album_tracks row, so
    # normal validation should still prove that the repair remains present.
    return track, False


def track_mismatch_notification_exists(
    conn: sqlite3.Connection,
    artist: str,
    album: str,
    track: str,
) -> bool:
    """Whether this exact mismatch has already generated a notification."""
    row = conn.execute(
        """
        SELECT 1
        FROM notifications
        WHERE type = 'track_mismatch'
          AND json_extract(details, '$.artist') = ?
          AND json_extract(details, '$.album') = ?
          AND json_extract(details, '$.scrobble_track') = ?
        LIMIT 1
        """,
        (artist, album, track),
    ).fetchone()
    return row is not None
