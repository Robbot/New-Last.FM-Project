import sqlite3

import pytest

from app.db.entities import Resolver, lookup_track_id
from app.services.migrations.reindex_track_aliases import reindex_track_aliases


def _artist(conn, name="System of a Down"):
    return Resolver(conn).resolve_artist_id(name)


@pytest.mark.unit
def test_resolver_self_heals_legacy_punctuation_alias(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        artist_id = _artist(conn)
        track_id = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Chop Suey!', ?)", (artist_id,)
        ).lastrowid
        conn.execute(
            "INSERT INTO track_alias VALUES(?, 'chop suey!', ?)", (artist_id, track_id)
        )

        resolved = Resolver(conn).resolve_track_id(artist_id, "Chop Suey!")

        assert resolved == track_id
        assert conn.execute("SELECT COUNT(*) FROM track").fetchone()[0] == 1
        assert conn.execute(
            "SELECT track_id FROM track_alias WHERE artist_id=? AND norm_title='chop suey'",
            (artist_id,),
        ).fetchone()[0] == track_id


@pytest.mark.unit
def test_read_lookup_understands_legacy_punctuation_alias(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        artist_id = _artist(conn)
        track_id = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Chop Suey!', ?)", (artist_id,)
        ).lastrowid
        conn.execute(
            "INSERT INTO track_alias VALUES(?, 'chop suey!', ?)", (artist_id, track_id)
        )

        assert lookup_track_id(conn, "System of a Down", "Chop Suey!") == track_id


@pytest.mark.unit
def test_read_lookup_prefers_exact_named_mix_over_normalized_base_track(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        artist_id = _artist(conn, "R.E.M.")
        base_id = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Finest Worksong', ?)",
            (artist_id,),
        ).lastrowid
        mix_title = "Finest Worksong (Mutual Drum Horn Mix)"
        mix_id = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES(?, ?)", (mix_title, artist_id)
        ).lastrowid
        conn.execute(
            "INSERT INTO track_alias VALUES(?, 'finest worksong', ?)",
            (artist_id, base_id),
        )
        conn.execute(
            "INSERT INTO track_alias VALUES(?, 'finest worksong (mutual drum horn mix)', ?)",
            (artist_id, mix_id),
        )

        assert lookup_track_id(conn, "R.E.M.", mix_title) == mix_id


@pytest.mark.unit
def test_resolver_refuses_ambiguous_legacy_aliases(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        artist_id = _artist(conn)
        first = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Hello!', ?)", (artist_id,)
        ).lastrowid
        second = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Hello?', ?)", (artist_id,)
        ).lastrowid
        conn.execute("INSERT INTO track_alias VALUES(?, 'hello!', ?)", (artist_id, first))
        conn.execute("INSERT INTO track_alias VALUES(?, 'hello?', ?)", (artist_id, second))

        with pytest.raises(sqlite3.IntegrityError, match="ambiguous normalized track alias"):
            Resolver(conn).resolve_track_id(artist_id, "Hello.")
        assert conn.execute("SELECT COUNT(*) FROM track").fetchone()[0] == 2


@pytest.mark.unit
def test_reindex_seeds_current_key_and_records_version(app):
    with sqlite3.connect(app.config["DATABASE_PATH"]) as conn:
        artist_id = _artist(conn)
        track_id = conn.execute(
            "INSERT INTO track(title, artist_id) VALUES('Chop Suey!', ?)", (artist_id,)
        ).lastrowid
        conn.execute(
            "INSERT INTO track_alias VALUES(?, 'chop suey!', ?)", (artist_id, track_id)
        )

        result = reindex_track_aliases(conn)

        assert result == {"aliases_inserted": 1, "ambiguous": 0}
        assert conn.execute(
            "SELECT track_id FROM track_alias WHERE artist_id=? AND norm_title='chop suey'",
            (artist_id,),
        ).fetchone()[0] == track_id
        assert conn.execute(
            "SELECT value FROM schema_metadata WHERE key='track_alias_normalizer_version'"
        ).fetchone()[0] == "2"
