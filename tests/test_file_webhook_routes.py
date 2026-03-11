"""Comprehensive tests for file storage, webhook relay, and async job endpoints in routes/admin.py."""
import sys, os, json, base64
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

os.environ.setdefault("WEBHOOKS_DB", ":memory:")

FAKE_KEY = "apk_test_file_wh_key"
AUTH = {"Authorization": f"Bearer {FAKE_KEY}", "Content-Type": "application/json"}
ADMIN_SECRET = "test-admin-secret-fw"


def _validate_key_ok(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


@pytest.fixture(scope="module")
def client():
    os.environ["ADMIN_SECRET"] = ADMIN_SECRET
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _admin_headers():
    return {"Authorization": f"Bearer {ADMIN_SECRET}", "Content-Type": "application/json"}


# ══════════════════════════════════════════════════════════════════════════════
# FILE STORAGE
# ══════════════════════════════════════════════════════════════════════════════


class TestFilesUpload:
    def test_no_auth(self, client):
        r = client.post("/files/upload", json={"base64_data": "aGVsbG8=", "filename": "test.txt"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.save_file", return_value={"file_id": "f1", "filename": "test.txt"})
    def test_upload_base64_success(self, mock_save, mock_vk, client):
        b64 = base64.b64encode(b"hello world").decode()
        r = client.post("/files/upload", headers=AUTH,
                        json={"base64_data": b64, "filename": "test.txt",
                              "content_type": "text/plain", "agent_id": "agent-a"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["file_id"] == "f1"

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_upload_invalid_base64(self, mock_vk, client):
        r = client.post("/files/upload", headers=AUTH,
                        json={"base64_data": "not-valid-b64!!!", "filename": "bad.txt",
                              "content_type": "text/plain"})
        assert r.status_code == 400
        assert "base64" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_upload_blocked_extension(self, mock_vk, client):
        b64 = base64.b64encode(b"malicious").decode()
        r = client.post("/files/upload", headers=AUTH,
                        json={"base64_data": b64, "filename": "evil.exe",
                              "content_type": "application/octet-stream"})
        assert r.status_code == 400
        assert "Blocked file extension" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_upload_blocked_content_type(self, mock_vk, client):
        b64 = base64.b64encode(b"data").decode()
        r = client.post("/files/upload", headers=AUTH,
                        json={"base64_data": b64, "filename": "file.dat",
                              "content_type": "application/x-executable"})
        assert r.status_code == 400
        assert "Blocked content type" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.save_file", side_effect=ValueError("File too large"))
    def test_upload_too_large(self, mock_save, mock_vk, client):
        b64 = base64.b64encode(b"data").decode()
        r = client.post("/files/upload", headers=AUTH,
                        json={"base64_data": b64, "filename": "big.txt",
                              "content_type": "text/plain"})
        assert r.status_code == 413


class TestFilesGet:
    def test_no_auth(self, client):
        r = client.get("/files/f1")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.get_file", return_value=({"filename": "test.txt", "content_type": "text/plain"}, b"hello"))
    def test_success(self, mock_get, mock_vk, client):
        r = client.get("/files/f1", headers=AUTH)
        assert r.status_code == 200
        assert r.data == b"hello"
        assert "attachment" in r.headers.get("Content-Disposition", "")

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.get_file", return_value=(None, None))
    def test_not_found(self, mock_get, mock_vk, client):
        r = client.get("/files/nonexistent", headers=AUTH)
        assert r.status_code == 404


class TestFilesDelete:
    def test_no_auth(self, client):
        r = client.delete("/files/f1", json={"agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    def test_missing_agent_id(self, mock_vk, client):
        r = client.delete("/files/f1", headers=AUTH, json={})
        assert r.status_code == 400
        assert "agent_id" in r.get_json()["error"]

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.delete_file", return_value=True)
    def test_success(self, mock_del, mock_vk, client):
        r = client.delete("/files/f1", headers=AUTH, json={"agent_id": "agent-a"})
        assert r.status_code == 200
        assert r.get_json()["deleted"] is True


class TestFilesList:
    def test_no_auth(self, client):
        r = client.get("/files/list/agent-a")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.list_files", return_value=[{"file_id": "f1", "filename": "test.txt"}])
    def test_success(self, mock_list, mock_vk, client):
        r = client.get("/files/list/agent-a", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["agent_id"] == "agent-a"


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK RELAY
# ══════════════════════════════════════════════════════════════════════════════


class TestWebhooksCreate:
    def test_no_auth(self, client):
        r = client.post("/webhooks/create", json={"agent_id": "a"})
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.create_webhook", return_value={"webhook_id": "wh1", "endpoint": "/webhooks/wh1/receive"})
    def test_success(self, mock_create, mock_vk, client):
        r = client.post("/webhooks/create", headers=AUTH,
                        json={"agent_id": "agent-a", "label": "my-hook"})
        assert r.status_code == 200
        assert r.get_json()["webhook_id"] == "wh1"


class TestWebhooksReceive:
    """The receive endpoint should work WITHOUT auth."""

    @patch("routes.admin.receive_webhook_event", return_value={"event_id": "ev1"})
    def test_receive_post_no_auth(self, mock_recv, client):
        r = client.post("/webhooks/wh1/receive", data='{"event": "test"}',
                        content_type="application/json")
        assert r.status_code == 200
        assert r.get_json()["received"] is True

    @patch("routes.admin.receive_webhook_event", return_value={"event_id": "ev2"})
    def test_receive_get_no_auth(self, mock_recv, client):
        r = client.get("/webhooks/wh1/receive")
        assert r.status_code == 200

    @patch("routes.admin.receive_webhook_event", return_value=None)
    def test_receive_webhook_not_found(self, mock_recv, client):
        r = client.post("/webhooks/nonexistent/receive", data="test")
        assert r.status_code == 404


class TestWebhooksEvents:
    def test_no_auth(self, client):
        r = client.get("/webhooks/wh1/events")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.get_webhook", return_value={"webhook_id": "wh1", "event_count": 5})
    @patch("routes.admin.get_webhook_events", return_value=[{"event_id": "ev1"}])
    def test_success(self, mock_events, mock_hook, mock_vk, client):
        r = client.get("/webhooks/wh1/events", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert data["total_received"] == 5

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.get_webhook", return_value=None)
    def test_webhook_not_found(self, mock_hook, mock_vk, client):
        r = client.get("/webhooks/nonexistent/events", headers=AUTH)
        assert r.status_code == 404


class TestWebhooksList:
    def test_no_auth(self, client):
        r = client.get("/webhooks/list/agent-a")
        assert r.status_code == 401

    @patch("api_keys.validate_key", side_effect=_validate_key_ok)
    @patch("routes.admin.list_webhooks", return_value=[{"webhook_id": "wh1"}])
    def test_success(self, mock_list, mock_vk, client):
        r = client.get("/webhooks/list/agent-a", headers=AUTH)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC JOBS
# ══════════════════════════════════════════════════════════════════════════════


class TestAsyncSubmit:
    def test_no_auth(self, client):
        r = client.post("/async/submit", json={"endpoint": "test", "payload": {}})
        assert r.status_code == 401

    def test_no_api_key_auth(self, client):
        """Async submit requires admin auth, not API key."""
        with patch("api_keys.validate_key", side_effect=_validate_key_ok):
            r = client.post("/async/submit", headers=AUTH,
                            json={"endpoint": "test", "payload": {"q": "test"}})
        assert r.status_code == 401

    def test_missing_fields(self, client):
        r = client.post("/async/submit", headers=_admin_headers(),
                        json={"endpoint": ""})
        assert r.status_code == 400

    def test_unsupported_endpoint(self, client):
        r = client.post("/async/submit", headers=_admin_headers(),
                        json={"endpoint": "nonexistent", "payload": {"q": "test"}})
        assert r.status_code == 400
        assert "unsupported" in r.get_json()["error"]


class TestAsyncStatus:
    def test_no_auth(self, client):
        r = client.get("/async/status/job123")
        assert r.status_code == 401

    @patch("routes.admin.get_job", return_value=None)
    def test_not_found(self, mock_job, client):
        r = client.get("/async/status/nonexistent", headers=_admin_headers())
        assert r.status_code == 404

    @patch("routes.admin.get_job", return_value={"job_id": "j1", "status": "completed", "result": {"data": "ok"}})
    def test_success(self, mock_job, client):
        r = client.get("/async/status/j1", headers=_admin_headers())
        assert r.status_code == 200
        assert r.get_json()["status"] == "completed"
