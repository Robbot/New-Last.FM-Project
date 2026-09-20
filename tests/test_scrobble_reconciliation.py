import sqlite3

import pytest

from app.db.entities import Resolver
from app.services.ingest import AlbumlessScrobbleError, RawScrobble, ingest_scrobble
from app.services.migrate_entity_tables import ensure_entity_schema
from app.services.migrations.reindex_scrobble_identity import (
    ensure_scrobble_identity_index,
)
from app.services.sync_lastfm import (
    _update_compilation_albums,
    apply_scrobble_metadata_mapping,
    clean_album_name,
    clean_title,
)


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


def test_limahl_release_mapping_pins_canonical_album_and_recording_mbids():
    mapped = apply_scrobble_metadata_mapping(
        "Limahl",
        "Don't Suppose",
        "Never Ending Story",
        "ba147912-dc39-416f-9e4b-09765d671674",
        "1e828d49-9809-47b6-9582-c503f0d2c488",
        "e085fdbd-4934-4bfd-b368-d5725d740302",
    )

    assert mapped == (
        "Limahl",
        "Don't Suppose",
        "Never Ending Story",
        "ba147912-dc39-416f-9e4b-09765d671674",
        "3dbd3d32-d79f-439a-ba10-17d1e5ef3c97",
        "360af6e3-6c05-4e96-8623-8e2650780341",
    )


def test_siouxsie_truncated_track_title_maps_to_complete_title():
    mapped = apply_scrobble_metadata_mapping(
        "Siouxsie and the Banshees",
        "Through the Looking Glass",
        "This Town Ain't Big Enough For",
    )

    assert mapped[2] == "This Town Ain't Big Enough for the Both of Us"
    assert mapped[5] == "adb76536-9498-45dd-8007-6f96d29512cd"


def test_siouxsie_missing_article_maps_to_complete_title():
    mapped = apply_scrobble_metadata_mapping(
        "Siouxsie and the Banshees",
        "Through the Looking Glass",
        "This Town Ain't Big Enough for Both of Us",
    )

    assert mapped[2] == "This Town Ain't Big Enough for the Both of Us"
    assert mapped[5] == "adb76536-9498-45dd-8007-6f96d29512cd"


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


def test_ingest_preserves_existing_two_artist_compilation_owner():
    conn = _connection()
    ensure_scrobble_identity_index(conn)
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id("Trevor Jones")
    compilation_id = resolver.resolve_album_id(
        artist_id,
        "Two Artist Soundtrack",
        album_mbid="compilation-mbid",
        album_artist_text="Various Artists",
    )

    result = ingest_scrobble(
        conn,
        resolver,
        RawScrobble(
            artist_name="Trevor Jones",
            album_name="Two Artist Soundtrack",
            album_mbid="compilation-mbid",
            track_name="Opening Track",
            uts=123,
        ),
        run_album_autocorrect=False,
        run_track_validation=False,
    )

    row = conn.execute(
        "SELECT album_artist, album_id FROM scrobble WHERE uts = 123"
    ).fetchone()
    assert result.album_artist == "Various Artists"
    assert tuple(row) == ("Various Artists", compilation_id)
    assert conn.execute("SELECT COUNT(*) FROM album").fetchone()[0] == 1
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


def test_tlove_pocisk_milosci_restores_polish_album_title():
    assert clean_album_name("T.Love", "Pocisk Milosci") == "Pocisk Miłości"


@pytest.mark.parametrize(
    "variant",
    [
        "Council Skies (Deluxe)",
        "Council Skies [Deluxe Edition]",
        "Council Skies - Deluxe Version",
        "Council Skies / Super Deluxe Edition",
        "Council Skies (Remastered and Expanded)",
        "Council Skies [Remastered & Expanded Edition]",
        "Council Skies - Expanded and Remastered",
        "Council Skies (Expanded Edition - Remastered)",
        "Council Skies [Remastered - Expanded Edition]",
    ],
)
def test_deluxe_album_suffixes_always_collapse_to_base_album(variant):
    assert clean_album_name(
        "Noel Gallagher's High Flying Birds", variant
    ) == "Council Skies"
    assert clean_title(variant) == "Council Skies"


def test_resolver_cannot_create_a_separate_deluxe_album_entity():
    conn = _connection()
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id("Noel Gallagher's High Flying Birds")

    canonical_id = resolver.resolve_album_id(artist_id, "Council Skies")
    deluxe_id = resolver.resolve_album_id(artist_id, "Council Skies (Deluxe)")

    assert deluxe_id == canonical_id
    assert conn.execute("SELECT title FROM album").fetchall()[0][0] == "Council Skies"
    assert conn.execute("SELECT COUNT(*) FROM album").fetchone()[0] == 1
    conn.close()


def test_resolver_cannot_create_combined_remaster_expanded_album_entity():
    conn = _connection()
    resolver = Resolver(conn)
    artist_id = resolver.resolve_artist_id("Siouxsie and the Banshees")

    canonical_id = resolver.resolve_album_id(artist_id, "Through the Looking Glass")
    edition_id = resolver.resolve_album_id(
        artist_id, "Through the Looking Glass (Remastered and Expanded)"
    )

    assert edition_id == canonical_id
    assert conn.execute("SELECT title FROM album").fetchall()[0][0] == "Through the Looking Glass"
    assert conn.execute("SELECT COUNT(*) FROM album").fetchone()[0] == 1
    conn.close()
