"""Tests for the admin database browser and editor."""

import sqlite3

import pytest


@pytest.mark.unit
class TestAdminDatabase:
    def test_entity_update_preserves_mbid_and_other_omitted_fields(self, app, client):
        db_path = app.config["DATABASE_PATH"]
        with sqlite3.connect(db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO artist (name, mbid, created_at) VALUES (?, ?, ?)",
                ("Original name", "canonical-mbid", "2026-09-14 12:00:00"),
            )
            artist_id = cursor.lastrowid

        with client.session_transaction() as admin_session:
            admin_session["admin_csrf_token"] = "correct"

        response = client.post(
            "/admin/database/update",
            data={
                "table": "artist",
                "rowid": artist_id,
                "name": "Updated name",
                # Even a manually crafted request cannot update a protected MBID.
                "mbid": "",
            },
            headers={"X-CSRF-Token": "correct"},
        )

        assert response.status_code == 200
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                "SELECT name, mbid, created_at FROM artist WHERE artist_id = ?",
                (artist_id,),
            ).fetchone()

        assert row == ("Updated name", "canonical-mbid", "2026-09-14 12:00:00")

    def test_browser_uses_server_supplied_editable_columns(
        self, app, client, monkeypatch
    ):
        monkeypatch.setattr("app.admin.routes.get_unread_count", lambda: 0)
        db_path = app.config["DATABASE_PATH"]
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "INSERT INTO artist (name, mbid) VALUES (?, ?)",
                ("An artist", "canonical-mbid"),
            )

        response = client.get("/admin/database?table=artist")

        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert (
            'const editableColumns = ["artist_id", "name", "created_at"];'
            in page
        )
        assert "col.includes('mbid')" not in page
