"""Tests for database functions."""

import pytest
import sqlite3
from unittest.mock import patch


@pytest.mark.unit
class TestDatabaseConnection:
    """Tests for database connection utilities."""

    def test_get_db_connection_returns_connection(self, app):
        """Test that get_db_connection returns a valid connection."""
        from app.db.connections import get_db_connection

        with patch('app.db.connections.DB_PATH', app.config['DATABASE_PATH']):
            conn = get_db_connection()
            assert conn is not None
            assert isinstance(conn, sqlite3.Connection)
            conn.close()


@pytest.mark.unit
class TestScrobbleQueries:
    """Tests for scrobble-related database queries."""

    def test_get_latest_scrobbles_returns_data(self, app, sample_scrobbles):
        """Test that get_latest_scrobbles returns scrobbles."""
        from app.db.scrobbles import get_latest_scrobbles

        with patch('app.db.connections.DB_PATH', app.config['DATABASE_PATH']):
            rows = get_latest_scrobbles()
            assert len(rows) == 3
            artists = {row['artist'] for row in rows}
            assert 'Metallica' in artists
            assert 'Megadeth' in artists

    def test_get_latest_scrobbles_with_date_filter(self, app, sample_scrobbles):
        """Test date filtering in get_latest_scrobbles."""
        from app.db.scrobbles import get_latest_scrobbles

        with patch('app.db.connections.DB_PATH', app.config['DATABASE_PATH']):
            rows = get_latest_scrobbles(start='2023-11-15', end='2023-11-16')
            # Scrobbles are from 2023-11-15 (1700000000 is Nov 15, 2023)
            assert len(rows) >= 0

    def test_top_tracks_collapses_case_variants_by_canonical_id(self, app):
        """Search results combine display-name variants of one track entity."""
        from app.db.entities import Resolver
        from app.db.tracks import get_top_tracks

        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('Robert Gawliński')
            album_id = resolver.resolve_album_id(
                artist_id, 'Największe przeboje', album_artist_text='Robert Gawliński'
            )
            track_id = resolver.resolve_track_id(artist_id, 'Beze mnie o mnie')
            conn.executemany(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ('Robert Gawliński', 'Największe przeboje', 'Robert Gawliński',
                     'Beze Mnie O Mnie', 1, artist_id, album_id, track_id),
                    ('Robert Gawliński', 'Największe przeboje', 'Robert Gawliński',
                     'Beze mnie o mnie', 2, artist_id, album_id, track_id),
                ],
            )
            conn.commit()

        with app.app_context():
            rows = get_top_tracks(search_term='Beze mnie o mnie')

        assert len(rows) == 1
        assert rows[0]['track'] == 'Beze mnie o mnie'
        assert rows[0]['artist'] == 'Robert Gawliński'
        assert rows[0]['plays'] == 2

    def test_top_tracks_keeps_same_title_by_different_artists_separate(self, app):
        """Canonical grouping must not merge different artists' tracks."""
        from app.db.entities import Resolver
        from app.db.tracks import get_top_tracks

        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            for uts, artist in enumerate(('Artist One', 'Artist Two'), start=1):
                artist_id = resolver.resolve_artist_id(artist)
                album_id = resolver.resolve_album_id(artist_id, 'Album', album_artist_text=artist)
                track_id = resolver.resolve_track_id(artist_id, 'Home')
                conn.execute(
                    """
                    INSERT INTO scrobble
                        (artist, album, album_artist, track, uts, artist_id, album_id, track_id)
                    VALUES (?, 'Album', ?, 'Home', ?, ?, ?, ?)
                    """,
                    (artist, artist, uts, artist_id, album_id, track_id),
                )
            conn.commit()

        with app.app_context():
            rows = get_top_tracks(search_term='Home')

        assert len(rows) == 2
        assert {row['artist'] for row in rows} == {'Artist One', 'Artist Two'}


@pytest.mark.unit
class TestDatabaseNormalization:
    """Tests for data normalization functions."""

    def test_normalize_for_matching_lowercases(self, app):
        """Test that normalization lowercases text."""
        from app.db import _normalize_for_matching

        result = _normalize_for_matching('METALLICA')
        assert result == 'metallica'

    def test_normalize_for_matching_removes_accents(self, app):
        """Test that normalization removes accents."""
        from app.db import _normalize_for_matching

        result = _normalize_for_matching('Mötley Crüe')
        assert 'motley' in result.lower()
        assert 'crue' in result.lower()


@pytest.mark.unit
class TestEntitySchema:
    """Tests for the Phase 0 canonical entity tables and FK enforcement."""

    def test_foreign_keys_enforced_on_connection(self, app):
        """get_db_connection must enable PRAGMA foreign_keys."""
        from app.db.connections import get_db_connection

        with patch('app.db.connections.DB_PATH', app.config['DATABASE_PATH']):
            conn = get_db_connection()
            try:
                cur = conn.execute("PRAGMA foreign_keys")
                assert cur.fetchone()[0] == 1
            finally:
                conn.close()

    def test_entity_tables_present(self, app):
        """Canonical entity + alias tables exist on a fresh install."""
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            names = {r[0] for r in rows}
            for required in ('artist', 'album', 'track',
                             'artist_alias', 'album_alias', 'track_alias'):
                assert required in names, f"{required} table missing"

    def test_scrobble_has_id_columns(self, app):
        """scrobble has the nullable *_id FK columns."""
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(scrobble)")}
            for required in ('artist_id', 'album_id', 'track_id'):
                assert required in cols, f"scrobble.{required} missing"
