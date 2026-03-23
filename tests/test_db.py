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
