import json
import sqlite3

from app.db.entities import Resolver
from app.services.ingest import RawScrobble, ingest_scrobble
from app.services.resolve_track_mismatch import (
    add_to_tracklist,
    keep_mismatch,
    map_mismatch,
)
from app.services.track_mismatch_resolutions import apply_track_mismatch_decision


def _connection(app):
    conn = sqlite3.connect(app.config["DATABASE_PATH"])
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            created_at INTEGER NOT NULL,
            dismissed_at INTEGER,
            severity TEXT NOT NULL DEFAULT 'info'
        )
        """
    )
    return conn


def _notification(conn, artist, album, source, candidates):
    details = {
        "artist": artist,
        "album": album,
        "scrobble_track": source,
        "track_mbid": None,
        "album_tracks": [
            {"track": title, "track_number": number}
            for number, title in enumerate(candidates, 1)
        ],
    }
    return conn.execute(
        """
        INSERT INTO notifications(type, title, message, details, created_at, severity)
        VALUES('track_mismatch', ?, 'mismatch', ?, 1, 'warning')
        """,
        (f"Track mismatch: {artist} - {source}", json.dumps(details)),
    ).lastrowid


def _seed_release(conn, artist="Example Artist", album="Example Album"):
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id(artist)
    album_id = resolver.resolve_album_id(artist_id, album)
    return resolver, artist_id, album_id


def test_map_preview_rolls_back_and_apply_updates_text_id_and_duplicates(app):
    with _connection(app) as conn:
        resolver, artist_id, album_id = _seed_release(conn)
        source_id = resolver.resolve_track_id(artist_id, "Song - Mono")
        canonical_id = resolver.resolve_track_id(artist_id, "Song")
        conn.execute(
            """INSERT INTO album_tracks
               (artist, album, track_number, track, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 1, 'Song', ?, ?, ?)""",
            (artist_id, album_id, canonical_id),
        )
        conn.execute(
            """INSERT INTO scrobble
               (artist, album, track, uts, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 'Song - Mono', 100, ?, ?, ?)""",
            (artist_id, album_id, source_id),
        )
        notification_id = _notification(
            conn, "Example Artist", "Example Album", "Song - Mono", ["Song"]
        )
        _notification(
            conn, "Example Artist", "Example Album", "Song - Mono", ["Song"]
        )
        conn.commit()

        preview = map_mismatch(conn, notification_id, "Song", dry_run=True)
        assert preview.scrobbles_updated == 1
        assert preview.notifications_dismissed == 2
        assert conn.execute("SELECT track FROM scrobble").fetchone()[0] == "Song - Mono"
        assert conn.execute("SELECT COUNT(*) FROM track_mismatch_resolution").fetchone()[0] == 0

        result = map_mismatch(conn, notification_id, "Song", dry_run=False)
        assert result.scrobbles_updated == 1
        row = conn.execute("SELECT track, track_id FROM scrobble").fetchone()
        assert tuple(row) == ("Song", canonical_id)
        assert conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE dismissed_at IS NULL"
        ).fetchone()[0] == 0
        assert apply_track_mismatch_decision(
            conn, "Example Artist", "Example Album", "Song - Mono"
        ) == ("Song", False)


def test_keep_records_acceptance_without_changing_scrobble(app):
    with _connection(app) as conn:
        notification_id = _notification(
            conn, "Example Artist", "Example Album", "Song - Live", ["Song"]
        )
        conn.commit()

        result = keep_mismatch(conn, notification_id, dry_run=False)

        assert result.notifications_dismissed == 1
        assert apply_track_mismatch_decision(
            conn, "Example Artist", "Example Album", "Song - Live"
        ) == ("Song - Live", True)


def test_add_to_tracklist_uses_existing_relational_ids(app):
    with _connection(app) as conn:
        resolver, artist_id, album_id = _seed_release(conn)
        track_id = resolver.resolve_track_id(artist_id, "Missing Song")
        conn.execute(
            """INSERT INTO scrobble
               (artist, album, track, uts, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 'Missing Song', 100, ?, ?, ?)""",
            (artist_id, album_id, track_id),
        )
        notification_id = _notification(
            conn, "Example Artist", "Example Album", "Missing Song", ["Other Song"]
        )
        conn.commit()

        result = add_to_tracklist(conn, notification_id, 7, dry_run=False)

        assert result.album_tracks_added == 1
        row = conn.execute(
            """SELECT track, track_number, artist_id, album_id, track_id
               FROM album_tracks WHERE track = 'Missing Song'"""
        ).fetchone()
        assert tuple(row) == ("Missing Song", 7, artist_id, album_id, track_id)


def test_add_to_tracklist_can_shift_an_incomplete_tracklist(app):
    with _connection(app) as conn:
        resolver, artist_id, album_id = _seed_release(conn)
        missing_id = resolver.resolve_track_id(artist_id, "Missing Opener")
        existing_id = resolver.resolve_track_id(artist_id, "Former Opener")
        conn.execute(
            """INSERT INTO album_tracks
               (artist, album, track_number, track, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 1, 'Former Opener', ?, ?, ?)""",
            (artist_id, album_id, existing_id),
        )
        conn.execute(
            """INSERT INTO scrobble
               (artist, album, track, uts, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 'Missing Opener', 100, ?, ?, ?)""",
            (artist_id, album_id, missing_id),
        )
        notification_id = _notification(
            conn, "Example Artist", "Example Album", "Missing Opener", ["Former Opener"]
        )
        conn.commit()

        result = add_to_tracklist(
            conn, notification_id, 1, shift_existing=True, dry_run=False
        )

        assert result.album_tracks_shifted == 1
        rows = conn.execute(
            """SELECT track_number, track FROM album_tracks
               ORDER BY track_number"""
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            (1, "Missing Opener"),
            (2, "Former Opener"),
        ]


def test_ingest_creates_only_one_notification_for_repeated_mismatch(app):
    with _connection(app) as conn:
        # The production ingest conflict target is (uts, artist, track). The
        # broad legacy test fixture also includes album, so add the production
        # identity index for this ingest integration test.
        conn.execute(
            "CREATE UNIQUE INDEX idx_scrobble_identity_test "
            "ON scrobble(uts, artist, track)"
        )
        resolver, artist_id, album_id = _seed_release(conn)
        canonical_id = resolver.resolve_track_id(artist_id, "Canonical Song")
        conn.execute(
            """INSERT INTO album_tracks
               (artist, album, track_number, track, artist_id, album_id, track_id)
               VALUES('Example Artist', 'Example Album', 1, 'Canonical Song', ?, ?, ?)""",
            (artist_id, album_id, canonical_id),
        )
        for uts in (100, 200):
            ingest_scrobble(
                conn,
                resolver,
                RawScrobble(
                    artist_name="Example Artist",
                    album_name="Example Album",
                    track_name="Different Song",
                    uts=uts,
                ),
                run_album_autocorrect=False,
            )

        assert conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE type='track_mismatch'"
        ).fetchone()[0] == 1
