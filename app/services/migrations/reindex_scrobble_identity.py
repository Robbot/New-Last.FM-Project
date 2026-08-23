"""Make a listen's identity independent of correctable album metadata."""

from __future__ import annotations

import sqlite3


def ensure_scrobble_identity_index(conn: sqlite3.Connection) -> int:
    """Deduplicate legacy collisions and enforce ``(uts, artist, track)``.

    Later rows win because a later import is the application's opportunity to
    observe corrected Last.fm metadata.  Returns the number of removed rows.
    The caller owns the transaction.
    """
    duplicate_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM scrobble AS s
        WHERE EXISTS (
            SELECT 1 FROM scrobble AS newer
            WHERE newer.uts = s.uts
              AND newer.artist = s.artist
              AND newer.track = s.track
              AND newer.id > s.id
        )
        """
    ).fetchone()[0]

    conn.execute(
        """
        DELETE FROM scrobble
        WHERE EXISTS (
            SELECT 1 FROM scrobble AS newer
            WHERE newer.uts = scrobble.uts
              AND newer.artist = scrobble.artist
              AND newer.track = scrobble.track
              AND newer.id > scrobble.id
        )
        """
    )
    conn.execute("DROP INDEX IF EXISTS idx_scrobble_unique")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scrobble_unique
        ON scrobble(uts, artist, track)
        """
    )
    return duplicate_count

