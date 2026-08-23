"""Security tests for the admin access and mutation boundary."""

import pytest


@pytest.mark.unit
class TestAdminSecurity:
    def test_admin_rejects_public_remote_address(self, client):
        response = client.get("/admin", environ_base={"REMOTE_ADDR": "203.0.113.10"})

        assert response.status_code == 403

    def test_proxy_forwarded_public_address_is_rejected(self, client):
        response = client.get(
            "/admin",
            environ_base={"REMOTE_ADDR": "127.0.0.1"},
            headers={"X-Forwarded-For": "203.0.113.10"},
        )

        assert response.status_code == 403

    def test_admin_mutation_rejects_missing_csrf_token(self, client):
        response = client.post("/admin/notifications/dismiss-all")

        assert response.status_code == 403
        assert response.get_json() == {"error": "Invalid or missing CSRF token"}

    def test_admin_mutation_rejects_incorrect_csrf_token(self, client):
        with client.session_transaction() as admin_session:
            admin_session["admin_csrf_token"] = "correct"

        response = client.post(
            "/admin/database/execute",
            data={"query": "SELECT 1"},
            headers={"X-CSRF-Token": "incorrect"},
        )

        assert response.status_code == 403

    def test_admin_mutation_accepts_session_csrf_token(self, client):
        with client.session_transaction() as admin_session:
            admin_session["admin_csrf_token"] = "correct"

        response = client.post(
            "/admin/database/execute",
            data={"query": "SELECT 1 AS value"},
            headers={"X-CSRF-Token": "correct"},
        )

        assert response.status_code == 200
        assert response.get_json()["success"] is True
