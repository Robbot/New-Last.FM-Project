"""Tests for targeted MusicBrainz album classification repair."""

from unittest.mock import Mock, patch

import pytest


@pytest.mark.unit
def test_fetch_release_group_classifies_plain_album():
    from app.services.fetch_musicbrainz_releases import (
        fetch_release_group_from_musicbrainz,
    )

    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "release-group": {
            "id": "release-group-id",
            "title": "Toys in the Attic",
            "primary-type": "Album",
            "secondary-types": [],
            "first-release-date": "1975-04-08",
        }
    }

    with patch(
        "app.services.fetch_musicbrainz_releases.requests.get",
        return_value=response,
    ):
        release = fetch_release_group_from_musicbrainz("release-id")

    assert release["release_type"] == "Album"
    assert release["secondary_types"] == []
    assert release["release_year"] == "1975"
    assert release["album_mbid"] == "release-group-id"


@pytest.mark.unit
def test_refresh_unmatched_album_caches_classification_under_library_title():
    from app.db.artists import _refresh_unmatched_played_albums

    played = {
        "Rockin' the Joint": {
            "album_mbid": "release-id",
            "plays": 4,
        }
    }
    lookup = {}
    fetched = {
        "title": "Rockin’ the Joint",
        "album_title": "Rockin’ the Joint",
        "mbid": "release-group-id",
        "album_mbid": "release-group-id",
        "release_type": "Album + Live",
        "primary_type": "Album",
        "secondary_types": ["Live"],
    }

    with (
        patch(
            "app.services.fetch_musicbrainz_releases.fetch_release_group_from_musicbrainz",
            return_value=fetched,
        ) as fetch,
        patch("app.db.artists.set_musicbrainz_releases", return_value=True) as store,
    ):
        _refresh_unmatched_played_albums(
            "artist-id", "Aerosmith", played, lookup
        )

    fetch.assert_called_once_with("release-id")
    cached_release = store.call_args.args[2][0]
    assert cached_release["title"] == "Rockin' the Joint"
    assert lookup["rockin the joint"]["release_type"] == "Album + Live"


@pytest.mark.unit
def test_refresh_skips_unknown_album_without_release_id():
    from app.db.artists import _refresh_unmatched_played_albums

    with patch(
        "app.services.fetch_musicbrainz_releases.fetch_release_group_from_musicbrainz"
    ) as fetch:
        _refresh_unmatched_played_albums(
            "artist-id",
            "Aerosmith",
            {"Unknown Album": {"album_mbid": None}},
            {},
        )

    fetch.assert_not_called()
