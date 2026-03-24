"""Tests for Flask routes."""

import pytest
from app import create_app


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


@pytest.mark.unit
class TestArtistsRoutes:
    """Tests for artists blueprint routes."""

    def test_library_artists_page_loads(self, client):
        """Test that artists page loads successfully."""
        response = client.get('/library/artists')
        assert response.status_code == 200
        assert b'Artists' in response.data


@pytest.mark.unit
class TestAlbumsRoutes:
    """Tests for albums blueprint routes."""

    def test_library_albums_page_loads(self, client):
        """Test that albums page loads successfully."""
        response = client.get('/library/albums')
        assert response.status_code == 200
        assert b'Albums' in response.data


@pytest.mark.unit
class TestTracksRoutes:
    """Tests for tracks blueprint routes."""

    def test_library_tracks_page_loads(self, client):
        """Test that tracks page loads successfully."""
        response = client.get('/library/tracks')
        assert response.status_code == 200
        assert b'Tracks' in response.data


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
