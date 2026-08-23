import sqlite3

import pytest

from app.db.entities import Resolver
from app.services.ingest import AlbumlessScrobbleError, RawScrobble, ingest_scrobble
from app.services.migrate_entity_tables import ensure_entity_schema
from app.services.migrations.reindex_scrobble_identity import (
    ensure_scrobble_identity_index,
)
from app.services.sync_lastfm import _update_compilation_albums, clean_album_name


def _connection():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE scrobble (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL, artist_mbid TEXT,
            album TEXT NOT NULL, album_mbid TEXT, album_artist TEXT,
            track TEXT NOT NULL, track_mbid TEXT, uts INTEGER NOT NULL,
            source TEXT DEFAULT 'lastfm'
        )
        """
    )
    ensure_entity_schema(conn)
    return conn


def test_migration_keeps_later_corrected_album():
    conn = _connection()
    conn.execute(
        "CREATE UNIQUE INDEX idx_scrobble_unique "
        "ON scrobble(uts, artist, album, track)"
    )
    rows = [
        ("Metallica", "S&M", "wrong-live-mbid", "Master of Puppets", 123),
        ("Metallica", "Master of Puppets", "studio-mbid", "Master of Puppets", 123),
    ]
    conn.executemany(
        "INSERT INTO scrobble(artist, album, album_mbid, track, uts) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )

    assert ensure_scrobble_identity_index(conn) == 1
    remaining = conn.execute("SELECT album, album_mbid FROM scrobble").fetchone()
    assert tuple(remaining) == ("Master of Puppets", "studio-mbid")
    conn.close()


def test_later_api_metadata_reconciles_without_duplicate():
    conn = _connection()
    ensure_scrobble_identity_index(conn)
    resolver = Resolver(conn)

    first = ingest_scrobble(
        conn,
        resolver,
        RawScrobble(
            artist_name="Metallica", album_name="S&M",
            album_mbid="wrong-live-mbid", track_name="Master of Puppets", uts=123,
        ),
        run_album_autocorrect=False,
        run_track_validation=False,
    )
    corrected = ingest_scrobble(
        conn,
        resolver,
        RawScrobble(
            artist_name="Metallica", album_name="Master of Puppets",
            album_mbid="studio-mbid", track_name="Master of Puppets", uts=123,
        ),
        run_track_validation=False,
    )

    assert first.inserted is True
    assert corrected.inserted is False
    assert corrected.reconciled is True
    row = conn.execute(
        "SELECT album, album_mbid, COUNT(*) AS count FROM scrobble"
    ).fetchone()
    assert tuple(row) == ("Master of Puppets", "studio-mbid", 1)
    conn.close()


def test_albumless_scrobble_is_rejected_without_database_writes():
    conn = _connection()
    ensure_scrobble_identity_index(conn)
    resolver = Resolver(conn)

    with pytest.raises(AlbumlessScrobbleError):
        ingest_scrobble(
            conn,
            resolver,
            RawScrobble(
                artist_name="Buzu Squat",
                album_name="",
                track_name="Nasze Przebudzenie",
                uts=1787315746,
            ),
            run_album_autocorrect=False,
            run_track_validation=False,
        )

    assert conn.execute("SELECT COUNT(*) FROM scrobble").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM artist").fetchone()[0] == 0
    conn.close()


def test_named_greatest_hits_stay_single_artist_after_bulk_detection():
    conn = _connection()
    rows = [
        (1, "Eurythmics", "Eurythmics", "Sweet Dreams"),
        (2, "Boney M.", "Boney M.", "Rasputin"),
        (3, "Artist A", "Artist A", "Track A"),
        (4, "Artist B", "Artist B", "Track B"),
        (5, "Artist C", "Artist C", "Track C"),
    ]
    conn.executemany(
        """INSERT INTO scrobble(uts,artist,album,album_mbid,album_artist,track)
           VALUES (?,?,'Greatest Hits','shared-mbid',?,?)""",
        rows,
    )

    _update_compilation_albums(conn)

    owners = dict(conn.execute(
        """SELECT artist,album_artist FROM scrobble
           WHERE artist IN ('Eurythmics','Boney M.')
             AND album='Greatest Hits'"""
    ).fetchall())
    assert owners == {
        "Eurythmics": "Eurythmics",
        "Boney M.": "Boney M.",
    }
    conn.close()


def test_andy_gibb_greatest_hits_maps_to_self_titled_album():
    assert clean_album_name("Andy Gibb", "Greatest Hits") == "Andy Gibb"
