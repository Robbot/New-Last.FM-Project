"""Tests for Flask routes."""

import sqlite3

import pytest
from app import create_app
from app.db.entities import Resolver


@pytest.mark.unit
class TestScrobblesRoutes:
    """Tests for scrobbles blueprint routes."""

    def test_library_scrobbles_redirects_to_index(self, client):
        """Test that root redirects to scrobbles page."""
        response = client.get('/', follow_redirects=False)
        assert response.status_code == 302
        assert '/library/scrobbles' in response.location

    def test_library_scrobbles_page_loads(self, client, sample_scrobbles):
        """Test that scrobbles page loads successfully."""
        response = client.get('/library/scrobbles')
        assert response.status_code == 200
        assert b'Library' in response.data
        assert b'Scrobbles' in response.data

    def test_library_scrobbles_pagination(self, client, sample_scrobbles):
        """Test scrobbles pagination."""
        response = client.get('/library/scrobbles?page=1')
        assert response.status_code == 200

        response = client.get('/library/scrobbles?page=999')
        assert response.status_code == 200  # Should just show last page

    def test_scrobbles_page_uses_canonical_album_title(self, app, client):
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('The Police')
            album_id = resolver.resolve_album_id(artist_id, "Outlandos d'Amour")
            track_id = resolver.resolve_track_id(artist_id, 'Roxanne')
            conn.execute(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, source,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'The Police', "Outlandos D'Amour", 'The Police', 'Roxanne',
                    1, 'lastfm', artist_id, album_id, track_id,
                ),
            )
            conn.commit()

        response = client.get('/library/scrobbles')

        assert response.status_code == 200
        assert b"Outlandos d&#39;Amour" in response.data
        assert b"Outlandos D&#39;Amour" not in response.data


@pytest.mark.unit
class TestArtistsRoutes:
    """Tests for artists blueprint routes."""

    def test_library_artists_page_loads(self, client):
        """Test that artists page loads successfully."""
        response = client.get('/library/artists')
        assert response.status_code == 200
        assert b'Artists' in response.data

    def test_artist_compilation_without_mbid_links_to_compilation_page(
        self, app, client, monkeypatch
    ):
        monkeypatch.setattr(
            'app.artists.routes.ensure_artist_info_cached', lambda _artist_name: None
        )
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('Track Artist')
            album_id = resolver.resolve_album_id(
                artist_id,
                'Compilation Without MBID',
                album_artist_text='Various Artists',
            )
            track_id = resolver.resolve_track_id(artist_id, 'Compilation Track')
            conn.execute(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, source,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'Track Artist', 'Compilation Without MBID', 'Various Artists',
                    'Compilation Track', 1, 'lastfm', artist_id, album_id, track_id,
                ),
            )
            conn.commit()

        response = client.get('/library/artists/Track%20Artist')

        assert response.status_code == 200
        assert (
            b'href="/library/compilations/Compilation%20Without%20MBID"'
            in response.data
        )


@pytest.mark.unit
class TestAlbumsRoutes:
    """Tests for albums blueprint routes."""

    def test_library_albums_page_loads(self, client):
        """Test that albums page loads successfully."""
        response = client.get('/library/albums')
        assert response.status_code == 200
        assert b'Albums' in response.data

    def test_album_alias_url_redirects_to_canonical_title(self, app, client):
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('The Police')
            album_id = resolver.resolve_album_id(
                artist_id,
                "Outlandos d'Amour",
                album_artist_text='The Police',
            )
            track_id = resolver.resolve_track_id(artist_id, 'Roxanne')
            conn.execute(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, source,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'The Police', "Outlandos d'Amour", 'The Police', 'Roxanne',
                    1, 'lastfm', artist_id, album_id, track_id,
                ),
            )
            conn.commit()

        response = client.get(
            "/library/artists/The%20Police/albums/Outlandos%20D'Amour?sort=plays",
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert response.location.endswith(
            "/library/artists/The%20Police/albums/Outlandos%20d'Amour?sort=plays"
        )


@pytest.mark.unit
class TestTracksRoutes:
    """Tests for tracks blueprint routes."""

    def test_library_tracks_page_loads(self, client):
        """Test that tracks page loads successfully."""
        response = client.get('/library/tracks')
        assert response.status_code == 200
        assert b'Tracks' in response.data

    def test_track_detail_preserves_slash_in_artist_name(self, app, client):
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('AC/DC')
            album_id = resolver.resolve_album_id(artist_id, 'The Razors Edge')
            track_id = resolver.resolve_track_id(artist_id, 'Thunderstruck')
            conn.execute(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, source,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'AC/DC', 'The Razors Edge', 'AC/DC', 'Thunderstruck',
                    1, 'lastfm', artist_id, album_id, track_id,
                ),
            )
            conn.commit()

        response = client.get(
            '/library/track',
            query_string={'artist_name': 'AC/DC', 'track_name': 'Thunderstruck'},
        )

        assert response.status_code == 200
        assert b'artist: <a href="/library/artists/AC/DC">AC/DC</a>' in response.data
        assert b'track: Thunderstruck' in response.data

    def test_legacy_track_url_recovers_slash_in_artist_name(self, app, client):
        db_path = app.config['DATABASE_PATH']
        with sqlite3.connect(db_path) as conn:
            resolver = Resolver(conn)
            artist_id = resolver.resolve_artist_id('AC/DC')
            album_id = resolver.resolve_album_id(artist_id, 'The Razors Edge')
            track_id = resolver.resolve_track_id(artist_id, 'Thunderstruck')
            conn.execute(
                """
                INSERT INTO scrobble
                    (artist, album, album_artist, track, uts, source,
                     artist_id, album_id, track_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    'AC/DC', 'The Razors Edge', 'AC/DC', 'Thunderstruck',
                    2, 'lastfm', artist_id, album_id, track_id,
                ),
            )
            conn.commit()

        response = client.get(
            '/library/track/AC/DC/Thunderstruck', follow_redirects=False
        )

        assert response.status_code == 302
        assert response.location.endswith(
            '/library/track?artist_name=AC/DC&track_name=Thunderstruck'
        )


@pytest.mark.unit
class TestTrackGapsRoutes:
    """Tests for track gaps blueprint routes."""

    def test_library_trackgaps_page_loads(self, client):
        """Test that track gaps page loads successfully."""
        response = client.get('/library/trackgaps')
        assert response.status_code == 200
        assert b'Track gaps' in response.data


@pytest.mark.unit
class TestErrorHandlers:
    """Tests for error handlers."""

    def test_404_handler(self, client):
        """Test that 404 errors are handled."""
        response = client.get('/this-route-does-not-exist')
        assert response.status_code == 404 or response.status_code == 302  # May redirect
