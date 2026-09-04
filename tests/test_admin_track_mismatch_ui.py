"""Admin UI integration tests for schema-aware mismatch resolution."""

import json
import sqlite3

from app.db.entities import Resolver


def _seed_mismatch(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE notifications (
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

        resolver = Resolver(conn)
        artist_id = resolver.resolve_artist_id("Example Artist")
        album_id = resolver.resolve_album_id(artist_id, "Example Album")
        source_id = resolver.resolve_track_id(artist_id, "Song - Mono")
        canonical_id = resolver.resolve_track_id(artist_id, "Song")
        conn.execute(
            """
            INSERT INTO album_tracks
                (artist, album, track_number, track, artist_id, album_id, track_id)
            VALUES ('Example Artist', 'Example Album', 1, 'Song', ?, ?, ?)
            """,
            (artist_id, album_id, canonical_id),
        )
        conn.execute(
            """
            INSERT INTO scrobble
                (artist, album, track, uts, artist_id, album_id, track_id)
            VALUES ('Example Artist', 'Example Album', 'Song - Mono', 100, ?, ?, ?)
            """,
            (artist_id, album_id, source_id),
        )
        details = json.dumps(
            {
                "artist": "Example Artist",
                "album": "Example Album",
                "scrobble_track": "Song - Mono",
                "track_mbid": None,
                "album_tracks": [{"track": "Song", "track_number": 1}],
            }
        )
        notification_ids = []
        for created_at in (1, 2):
            notification_ids.append(
                conn.execute(
                    """
                    INSERT INTO notifications
                        (type, title, message, details, created_at, severity)
                    VALUES ('track_mismatch', 'Track mismatch', 'mismatch', ?, ?, 'warning')
                    """,
                    (details, created_at),
                ).lastrowid
            )
        conn.commit()
        return notification_ids[-1]


def _csrf_headers(client):
    with client.session_transaction() as admin_session:
        admin_session["admin_csrf_token"] = "resolver-token"
    return {"X-CSRF-Token": "resolver-token"}


def test_notifications_page_groups_mismatches_and_offers_candidates(app, client):
    _seed_mismatch(app)

    response = client.get("/admin/notifications")

    assert response.status_code == 200
    assert response.text.count("Song - Mono") == 1
    assert "2 alerts" in response.text
    assert '<option value="Song">' in response.text
    assert "Preview map" in response.text
    assert "Preview add" in response.text
    assert "Preview keep" in response.text


def test_map_resolution_requires_csrf(app, client):
    notification_id = _seed_mismatch(app)

    response = client.post(
        f"/admin/notifications/{notification_id}/resolve",
        json={"action": "map", "canonical_track": "Song", "apply": True},
    )

    assert response.status_code == 403


def test_map_preview_is_rolled_back_then_apply_commits(app, client):
    notification_id = _seed_mismatch(app)
    headers = _csrf_headers(client)
    payload = {"action": "map", "canonical_track": "Song"}

    preview = client.post(
        f"/admin/notifications/{notification_id}/resolve",
        json={**payload, "apply": False},
        headers=headers,
    )

    assert preview.status_code == 200
    assert preview.get_json()["result"]["dry_run"] is True
    assert preview.get_json()["result"]["scrobbles_updated"] == 1
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        assert conn.execute("SELECT track FROM scrobble").fetchone()[0] == "Song - Mono"
        assert conn.execute(
            "SELECT COUNT(*) FROM track_mismatch_resolution"
        ).fetchone()[0] == 0

    applied = client.post(
        f"/admin/notifications/{notification_id}/resolve",
        json={**payload, "apply": True},
        headers=headers,
    )

    assert applied.status_code == 200
    assert applied.get_json()["applied"] is True
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        assert conn.execute("SELECT track FROM scrobble").fetchone()[0] == "Song"
        assert conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE dismissed_at IS NULL"
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT action FROM track_mismatch_resolution"
        ).fetchone()[0] == "map"


def test_resolver_rejects_unknown_action(app, client):
    notification_id = _seed_mismatch(app)

    response = client.post(
        f"/admin/notifications/{notification_id}/resolve",
        json={"action": "delete", "apply": False},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 400
    assert "map, add, keep" in response.get_json()["error"]
