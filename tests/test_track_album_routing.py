"""Tests for recording-aware track-to-album routing."""

import sqlite3

import pytest

from app.db.entities import Resolver
from app.services import track_album_routing


@pytest.mark.unit
def test_source_recording_filter_moves_only_matching_scrobbles(app, monkeypatch):
    db_path = app.config["DATABASE_PATH"]
    bad_recording = "bad-compilation-recording"
    target_recording = "original-album-recording"
    target_release = "original-release"

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        resolver = Resolver(conn)
        artist_id = resolver.resolve_artist_id("T.Love")
        compilation_id = resolver.resolve_album_id(artist_id, "Złota kolekcja")
        target_id = resolver.resolve_album_id(
            artist_id, "CHŁOPAKI NIE PŁACZĄ", target_release
        )
        track_id = resolver.resolve_track_id(artist_id, "Chłopaki nie płaczą")
        conn.executemany(
            """
            INSERT INTO scrobble
                (artist, album, album_artist, track, track_mbid, uts,
                 artist_id, album_id, track_id)
            VALUES ('T.Love', 'Złota kolekcja', 'T.Love',
                    'Chłopaki nie płaczą', ?, ?, ?, ?, ?)
            """,
            [
                (None, 1, artist_id, compilation_id, track_id),
                (bad_recording, 2, artist_id, compilation_id, track_id),
            ],
        )
        conn.commit()

        monkeypatch.setattr(track_album_routing, "_routing_cache", [{
            "artist": "T.Love",
            "conflict_albums": ["Złota kolekcja"],
            "routes": [{
                "album": "CHŁOPAKI NIE PŁACZĄ",
                "album_mbid": target_release,
                "track_mbid": target_recording,
                "source_track_mbids": [bad_recording],
                "tracks": ["Chłopaki nie płaczą"],
            }],
        }])

        summary = track_album_routing.apply_track_album_routing(conn)
        rows = conn.execute(
            "SELECT album, album_mbid, track_mbid, album_id "
            "FROM scrobble ORDER BY uts"
        ).fetchall()

    assert summary["total_moves"] == 1
    assert tuple(rows[0]) == ("Złota kolekcja", None, None, compilation_id)
    assert tuple(rows[1]) == (
        "CHŁOPAKI NIE PŁACZĄ",
        target_release,
        target_recording,
        target_id,
    )
