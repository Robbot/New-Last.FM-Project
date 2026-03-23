"""Pytest configuration and fixtures."""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from app import create_app


@pytest.fixture
def app():
    """Create a test Flask app with temporary database."""
    # Create temporary file for test database
    db_fd, db_path = tempfile.mkstemp(suffix='.sqlite')

    # Create app config
    app = create_app()
    app.config['TESTING'] = True
    app.config['DATABASE_PATH'] = db_path
    app.config['SECRET_KEY'] = 'test-secret-key'

    # Initialize test database schema
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scrobble (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                artist TEXT,
                artist_mbid TEXT,
                album TEXT,
                album_mbid TEXT,
                album_artist TEXT,
                track TEXT,
                track_mbid TEXT,
                uts INTEGER,
                UNIQUE(uts, artist, album, track)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS album_art (
                artist TEXT,
                album TEXT,
                album_mbid TEXT,
                artist_mbid TEXT,
                image_small TEXT,
                image_medium TEXT,
                image_large TEXT,
                image_xlarge TEXT,
                last_updated TEXT,
                year_col INTEGER,
                PRIMARY KEY (artist, album)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS album_tracks (
                artist TEXT,
                album TEXT,
                track_number INTEGER,
                track TEXT,
                track_mbid TEXT,
                duration INTEGER,
                PRIMARY KEY (artist, album, track_number)
            )
        """)
        conn.commit()

    yield app

    # Cleanup
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """Create a test client for the app."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner for the app."""
    return app.test_cli_runner()


@pytest.fixture
def sample_scrobbles(app):
    """Insert sample scrobbles into test database."""
    db_path = app.config['DATABASE_PATH']
    with sqlite3.connect(db_path) as conn:
        scrobbles = [
            ('Metallica', '123', 'Master of Puppets', '456', 'Battery', '789', 1700000000),
            ('Metallica', '123', 'Master of Puppets', '456', 'Master of Puppets', '790', 1700000100),
            ('Megadeth', '124', 'Rust in Peace', '457', 'Holy Wars', '791', 1700000200),
        ]
        conn.executemany(
            "INSERT OR IGNORE INTO scrobble (artist, artist_mbid, album, album_mbid, track, track_mbid, uts) VALUES (?, ?, ?, ?, ?, ?, ?)",
            scrobbles
        )
        conn.commit()
    return scrobbles
