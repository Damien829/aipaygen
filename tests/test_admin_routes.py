"""Comprehensive tests for routes/admin.py — 52 endpoints covering admin panel,
stats, user management, blog, changelog, referral, discovery, scouts, economy,
async jobs, file storage, webhooks, free tier, reputation, and more."""

import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

# Set ADMIN_SECRET before app import
ADMIN_SECRET = "test-admin-secret-xyz"
os.environ["ADMIN_SECRET"] = ADMIN_SECRET
os.environ.setdefault("WEBHOOKS_DB", ":memory:")

ADMIN_HEADERS = {"Authorization": f"Bearer {ADMIN_SECRET}"}
FAKE_API_KEY = "apk_test_admin_key_999"
API_KEY_HEADERS = {"Authorization": f"Bearer {FAKE_API_KEY}"}


def _validate_key_mock(key):
    if key == FAKE_API_KEY:
        return {"key": FAKE_API_KEY, "balance_usd": 50.0, "is_active": 1}
    return None


@pytest.fixture(scope="module")
def client():
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        from app import app
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        with app.test_client() as c:
            yield c


# ══════════════════════════════════════════════════════════════════════════════
# AUTH DECORATOR TESTS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminAuth:
    """Test require_admin decorator across admin-protected endpoints."""

    def test_stats_no_auth_returns_401(self, client):
        r = client.get("/stats")
        assert r.status_code == 401
        assert r.get_json()["error"] == "unauthorized"

    def test_stats_wrong_token_returns_401(self, client):
        r = client.get("/stats", headers={"Authorization": "Bearer wrong-token"})
        assert r.status_code == 401

    def test_stats_x_admin_key_header(self, client):
        """X-Admin-Key header should also work."""
        with patch("routes.admin.os.path.exists", return_value=False):
            r = client.get("/stats", headers={"X-Admin-Key": ADMIN_SECRET})
            assert r.status_code == 200

    def test_admin_secret_not_set_returns_503(self, client):
        with patch.dict(os.environ, {"ADMIN_SECRET": ""}, clear=False):
            r = client.get("/stats", headers=ADMIN_HEADERS)
            assert r.status_code == 503
            assert "misconfigured" in r.get_json()["error"]


# ══════════════════════════════════════════════════════════════════════════════
# STATS
# ══════════════════════════════════════════════════════════════════════════════

class TestStats:
    def test_stats_no_payments_log(self, client):
        with patch("routes.admin.os.path.exists", return_value=False):
            r = client.get("/stats", headers=ADMIN_HEADERS)
            assert r.status_code == 200
            data = r.get_json()
            assert data["total_requests"] == 0
            assert data["total_earned_usd"] == 0.0
            assert data["by_endpoint"] == {}

    def test_stats_with_payments(self, client):
        lines = [
            json.dumps({"endpoint": "/research", "amount_usd": 0.01}),
            json.dumps({"endpoint": "/research", "amount_usd": 0.01}),
            json.dumps({"endpoint": "/write", "amount_usd": 0.05}),
        ]
        fake_file = "\n".join(lines) + "\n"
        with patch("routes.admin.os.path.exists", return_value=True):
            with patch("builtins.open", MagicMock(return_value=__import__("io").StringIO(fake_file))):
                r = client.get("/stats", headers=ADMIN_HEADERS)
                assert r.status_code == 200
                data = r.get_json()
                assert data["total_requests"] == 3
                assert data["by_endpoint"]["/research"]["requests"] == 2
                assert data["by_endpoint"]["/write"]["requests"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN MANIFEST, ICONS, SW
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminAssets:
    def test_manifest_json(self, client):
        r = client.get("/admin/manifest.json")
        assert r.status_code == 200
        data = r.get_json()
        assert data["name"] == "AiPayGen Dashboard"
        assert len(data["icons"]) == 2

    def test_icon_192(self, client):
        r = client.get("/admin/icon-192.png")
        assert r.status_code == 200
        assert "svg" in r.content_type

    def test_icon_512(self, client):
        r = client.get("/admin/icon-512.png")
        assert r.status_code == 200

    def test_service_worker(self, client):
        r = client.get("/admin/sw.js")
        assert r.status_code == 200
        assert "javascript" in r.content_type
        assert b"fetch" in r.data


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN LOGIN
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminLogin:
    def test_login_get_returns_form(self, client):
        r = client.get("/admin/login")
        assert r.status_code == 200
        assert b"Admin Login" in r.data

    def test_login_post_wrong_key(self, client):
        r = client.post("/admin/login", data={"key": "wrong"})
        assert r.status_code == 401
        assert b"Invalid key" in r.data

    def test_login_post_correct_key(self, client):
        r = client.post("/admin/login", data={"key": ADMIN_SECRET})
        assert r.status_code == 302  # redirect


# ══════════════════════════════════════════════════════════════════════════════
# FUNNEL DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

class TestFunnelDashboard:
    @patch("routes.admin.get_funnel_stats", return_value={
        "total_events": 42, "by_type": {"discover_hit": 10}, "daily": []
    })
    def test_funnel_html_with_header_auth(self, mock_stats, client):
        r = client.get("/admin/funnel", headers={"Authorization": f"Bearer {ADMIN_SECRET}"})
        # Could be HTML (first /admin/funnel route) or JSON (second one)
        assert r.status_code == 200 or r.status_code == 302

    def test_funnel_no_auth_redirects(self, client):
        r = client.get("/admin/funnel")
        # Should redirect to login or return 401
        assert r.status_code in (302, 401)


# ══════════════════════════════════════════════════════════════════════════════
# BLOG
# ══════════════════════════════════════════════════════════════════════════════

class TestBlog:
    @patch("routes.admin.list_blog_posts", return_value=[
        {"slug": "test-post", "title": "Test Post", "generated_at": "2026-01-01T00:00:00"},
    ])
    def test_blog_index(self, mock_posts, client):
        r = client.get("/blog")
        assert r.status_code == 200
        assert b"Test Post" in r.data
        assert b"text/html" in r.content_type.encode()

    @patch("routes.admin.get_blog_post", return_value={
        "title": "My Tutorial",
        "content": "<p>Hello world</p>",
        "generated_at": "2026-01-01T00:00:00",
    })
    def test_blog_post_found(self, mock_get, client):
        r = client.get("/blog/my-tutorial")
        assert r.status_code == 200
        assert b"My Tutorial" in r.data

    @patch("routes.admin.get_blog_post", return_value=None)
    def test_blog_post_not_found(self, mock_get, client):
        r = client.get("/blog/nonexistent-slug")
        assert r.status_code == 404
        assert r.get_json()["error"] == "post not found"


# ══════════════════════════════════════════════════════════════════════════════
# REFERRAL / AFFILIATE
# ══════════════════════════════════════════════════════════════════════════════

class TestReferral:
    @patch("routes.admin.register_referral_agent", return_value={
        "agent_id": "my-agent", "referral_url": "https://api.aipaygen.com/ref/my-agent"
    })
    def test_referral_join_success(self, mock_reg, client):
        r = client.post("/referral/join", json={"agent_id": "my-agent"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["agent_id"] == "my-agent"
        assert "note" in data

    def test_referral_join_missing_agent_id(self, client):
        r = client.post("/referral/join", json={})
        assert r.status_code == 400
        assert r.get_json()["error"] == "agent_id required"

    @patch("routes.admin.get_referral_stats", return_value={"clicks": 5, "conversions": 1})
    def test_referral_stats(self, mock_stats, client):
        r = client.get("/referral/stats/my-agent")
        assert r.status_code == 200
        assert r.get_json()["clicks"] == 5

    @patch("routes.admin.get_referral_leaderboard", return_value=[
        {"agent_id": "top-agent", "clicks": 100}
    ])
    def test_referral_leaderboard(self, mock_lb, client):
        r = client.get("/referral/leaderboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data["commission_rate"] == "10%"
        assert len(data["leaderboard"]) == 1

    def test_referral_leaderboard_limit_capped(self, client):
        with patch("routes.admin.get_referral_leaderboard", return_value=[]) as mock_lb:
            r = client.get("/referral/leaderboard?limit=999")
            assert r.status_code == 200
            mock_lb.assert_called_once_with(100)  # capped at 100

    @patch("routes.admin.record_click")
    def test_referral_redirect(self, mock_click, client):
        r = client.get("/ref/my-agent")
        assert r.status_code == 302


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class TestDiscoveryEngine:
    @patch("routes.admin.list_blog_posts", return_value=[])
    @patch("routes.admin.get_outreach_log", return_value=[])
    def test_discovery_status_auth(self, mock_log, mock_posts, client):
        r = client.get("/discovery/status", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert "outreach_log" in data
        assert "blog_posts" in data

    def test_discovery_status_no_auth(self, client):
        r = client.get("/discovery/status")
        assert r.status_code == 401

    @patch("routes.admin.run_hourly")
    def test_discovery_trigger_hourly(self, mock_run, client):
        r = client.post("/discovery/trigger", json={"job": "hourly"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["triggered"] == "hourly"

    @patch("routes.admin.run_canary", return_value={"all_ok": True})
    def test_discovery_trigger_canary(self, mock_canary, client):
        r = client.post("/discovery/trigger", json={"job": "canary"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["result"]["all_ok"] is True

    @patch("routes.admin.run_maintenance", return_value={"cleaned": 5})
    def test_discovery_trigger_maintenance(self, mock_maint, client):
        r = client.post("/discovery/trigger", json={"job": "maintenance"}, headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["result"]["cleaned"] == 5

    def test_discovery_trigger_no_auth(self, client):
        r = client.post("/discovery/trigger", json={"job": "hourly"})
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# DISCOVERY SCOUTS
# ══════════════════════════════════════════════════════════════════════════════

class TestDiscoveryScouts:
    def test_scouts_status(self, client):
        r = client.get("/discovery/scouts/status", headers=ADMIN_HEADERS)
        assert r.status_code == 200

    def test_scouts_status_no_auth(self, client):
        r = client.get("/discovery/scouts/status")
        assert r.status_code == 401

    def test_scouts_stats(self, client):
        with patch("discovery_scouts.get_scout_stats", return_value={"total_runs": 10}):
            r = client.get("/discovery/scouts/stats", headers=ADMIN_HEADERS)
            assert r.status_code == 200

    def test_scouts_run_invalid_name(self, client):
        r = client.post("/discovery/scouts/run/INVALID-NAME!", headers=ADMIN_HEADERS)
        assert r.status_code == 400
        assert "Invalid scout name" in r.get_json()["error"]

    def test_scouts_run_valid_name_not_found(self, client):
        with patch("discovery_scouts.run_scout_by_name", return_value=None):
            r = client.post("/discovery/scouts/run/test_scout", headers=ADMIN_HEADERS)
            assert r.status_code == 404

    def test_scouts_run_valid_name_success(self, client):
        with patch("discovery_scouts.run_scout_by_name", return_value={"found": 5}):
            r = client.post("/discovery/scouts/run/github_scout", headers=ADMIN_HEADERS)
            assert r.status_code == 200
            assert r.get_json()["found"] == 5

    def test_scouts_report(self, client):
        with patch("discovery_scouts.get_weekly_report", return_value={"week": "2026-W10"}):
            r = client.get("/discovery/scouts/report", headers=ADMIN_HEADERS)
            assert r.status_code == 200

    def test_scouts_absorbed(self, client):
        with patch("discovery_scouts.get_absorbed_skills_stats", return_value={"total": 50}):
            r = client.get("/discovery/scouts/absorbed", headers=ADMIN_HEADERS)
            assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN HUNTER
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminHunter:
    def test_admin_hunter_stats(self, client):
        r = client.get("/admin/hunter", headers=ADMIN_HEADERS)
        assert r.status_code == 200

    def test_admin_hunter_no_auth(self, client):
        r = client.get("/admin/hunter")
        assert r.status_code == 401

    def test_admin_hunter_run(self, client):
        with patch("api_discovery.run_all_hunters", return_value=10):
            with patch("api_discovery.inject_high_scorers", return_value=3):
                r = client.post("/admin/hunter/run", headers=ADMIN_HEADERS)
                assert r.status_code == 200
                assert r.get_json()["status"] == "started"

    def test_admin_hunter_run_no_auth(self, client):
        r = client.post("/admin/hunter/run")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# CATALOG ECONOMICS + X402 SPEND
# ══════════════════════════════════════════════════════════════════════════════

class TestCatalogEconomics:
    @patch("api_catalog.get_catalog_economics", return_value={"total_apis": 100})
    def test_catalog_economics(self, mock_econ, client):
        r = client.get("/admin/catalog-economics", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["total_apis"] == 100

    def test_catalog_economics_no_auth(self, client):
        r = client.get("/admin/catalog-economics")
        assert r.status_code == 401


class TestX402Spend:
    def test_x402_spend_success(self, client):
        with patch("x402_client.get_spend_stats", return_value={"total": 1.23}):
            r = client.get("/admin/x402-spend", headers=ADMIN_HEADERS)
            assert r.status_code == 200

    def test_x402_spend_error(self, client):
        with patch("x402_client.get_spend_stats", side_effect=Exception("no module")):
            r = client.get("/admin/x402-spend", headers=ADMIN_HEADERS)
            assert r.status_code == 200
            assert "error" in r.get_json()

    def test_x402_spend_no_auth(self, client):
        r = client.get("/admin/x402-spend")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# FREE TIER STATUS
# ══════════════════════════════════════════════════════════════════════════════

class TestFreeTier:
    @patch("routes.admin.get_free_tier_status", return_value={
        "ip": "1.2.3.4", "calls_used": 3, "calls_remaining": 7, "limit": 10
    })
    def test_free_tier_status(self, mock_ft, client):
        r = client.get("/free-tier/status")
        assert r.status_code == 200
        data = r.get_json()
        assert data["calls_remaining"] == 7


# ══════════════════════════════════════════════════════════════════════════════
# AGENT LEADERBOARD + REPUTATION
# ══════════════════════════════════════════════════════════════════════════════

class TestAgentLeaderboard:
    @patch("routes.admin.get_leaderboard", return_value=[
        {"agent_id": "agent-1", "score": 10.5}
    ])
    def test_leaderboard(self, mock_lb, client):
        r = client.get("/agents/leaderboard")
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1
        assert "scoring" in data

    @patch("routes.admin.get_leaderboard", return_value=[])
    def test_leaderboard_limit_cap(self, mock_lb, client):
        r = client.get("/agents/leaderboard?limit=500")
        assert r.status_code == 200
        mock_lb.assert_called_once_with(100)

    @patch("routes.admin.get_reputation", return_value={
        "agent_id": "agent-x", "score": 5.0, "tasks_completed": 3
    })
    def test_agent_reputation(self, mock_rep, client):
        r = client.get("/agent/reputation/agent-x")
        assert r.status_code == 200
        assert r.get_json()["agent_id"] == "agent-x"


# ══════════════════════════════════════════════════════════════════════════════
# TASK SUBSCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════

class TestTaskSubscriptions:
    @patch("routes.admin.subscribe_tasks", return_value={"subscribed": True})
    def test_task_subscribe_success(self, mock_sub, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/task/subscribe",
                            json={"agent_id": "a1", "callback_url": "https://example.com/hook"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 200

    def test_task_subscribe_missing_fields(self, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/task/subscribe", json={}, headers=API_KEY_HEADERS)
            assert r.status_code == 400

    def test_task_subscribe_no_auth(self, client):
        r = client.post("/task/subscribe", json={"agent_id": "a1", "callback_url": "https://x.com"})
        assert r.status_code == 401

    @patch("routes.admin.get_task_subscribers", return_value={"agent_id": "a1", "active": True})
    def test_task_subscription_status(self, mock_subs, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/task/subscription/a1", headers=API_KEY_HEADERS)
            assert r.status_code == 200

    @patch("routes.admin.get_task_subscribers", return_value=None)
    def test_task_subscription_not_found(self, mock_subs, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/task/subscription/unknown", headers=API_KEY_HEADERS)
            assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# ASYNC JOBS
# ══════════════════════════════════════════════════════════════════════════════

class TestAsyncJobs:
    def test_async_submit_missing_fields(self, client):
        r = client.post("/async/submit", json={}, headers=ADMIN_HEADERS)
        assert r.status_code == 400

    def test_async_submit_unsupported_endpoint(self, client):
        r = client.post("/async/submit",
                        json={"endpoint": "nonexistent", "payload": {"q": "test"}},
                        headers=ADMIN_HEADERS)
        assert r.status_code == 400
        assert "unsupported" in r.get_json()["error"]

    def test_async_submit_no_auth(self, client):
        r = client.post("/async/submit", json={"endpoint": "test", "payload": {}})
        assert r.status_code == 401

    @patch("routes.admin.get_job", return_value={
        "job_id": "j123", "status": "completed", "result": {"data": "ok"}
    })
    def test_async_status_found(self, mock_job, client):
        r = client.get("/async/status/j123", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.get_json()["status"] == "completed"

    @patch("routes.admin.get_job", return_value=None)
    def test_async_status_not_found(self, mock_job, client):
        r = client.get("/async/status/nonexistent", headers=ADMIN_HEADERS)
        assert r.status_code == 404

    def test_async_status_no_auth(self, client):
        r = client.get("/async/status/j123")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# FILE STORAGE
# ══════════════════════════════════════════════════════════════════════════════

class TestFileStorage:
    @patch("routes.admin.save_file", return_value={"file_id": "f1", "size": 100})
    def test_upload_json_base64(self, mock_save, client):
        import base64
        b64 = base64.b64encode(b"hello world").decode()
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/files/upload",
                            json={"base64_data": b64, "filename": "test.txt",
                                  "content_type": "text/plain"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 200
            assert r.get_json()["file_id"] == "f1"

    def test_upload_blocked_extension(self, client):
        import base64
        b64 = base64.b64encode(b"evil").decode()
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/files/upload",
                            json={"base64_data": b64, "filename": "virus.exe",
                                  "content_type": "application/octet-stream"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 400
            assert "Blocked file extension" in r.get_json()["error"]

    def test_upload_blocked_content_type(self, client):
        import base64
        b64 = base64.b64encode(b"data").decode()
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/files/upload",
                            json={"base64_data": b64, "filename": "file.dat",
                                  "content_type": "application/x-evil"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 400
            assert "Blocked content type" in r.get_json()["error"]

    def test_upload_invalid_base64(self, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/files/upload",
                            json={"base64_data": "not-valid-b64!!!", "filename": "f.txt",
                                  "content_type": "text/plain"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 400

    def test_upload_no_auth(self, client):
        r = client.post("/files/upload", json={"base64_data": "aGk=", "filename": "t.txt"})
        assert r.status_code == 401

    @patch("routes.admin.get_file", return_value=(
        {"filename": "result.txt", "content_type": "text/plain"}, b"hello"
    ))
    def test_file_get(self, mock_get, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/files/f123", headers=API_KEY_HEADERS)
            assert r.status_code == 200
            assert r.data == b"hello"

    @patch("routes.admin.get_file", return_value=(None, None))
    def test_file_get_not_found(self, mock_get, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/files/nonexistent", headers=API_KEY_HEADERS)
            assert r.status_code == 404

    @patch("routes.admin.delete_file", return_value=True)
    def test_file_delete(self, mock_del, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.delete("/files/f123",
                              json={"agent_id": "my-agent"},
                              headers=API_KEY_HEADERS)
            assert r.status_code == 200
            assert r.get_json()["deleted"] is True

    def test_file_delete_missing_agent_id(self, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.delete("/files/f123", json={}, headers=API_KEY_HEADERS)
            assert r.status_code == 400

    @patch("routes.admin.list_files", return_value=[{"file_id": "f1"}, {"file_id": "f2"}])
    def test_file_list(self, mock_list, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/files/list/my-agent", headers=API_KEY_HEADERS)
            assert r.status_code == 200
            data = r.get_json()
            assert data["count"] == 2
            assert data["agent_id"] == "my-agent"

    @patch("routes.admin.save_file", side_effect=ValueError("File too large"))
    def test_upload_too_large(self, mock_save, client):
        import base64
        b64 = base64.b64encode(b"big data").decode()
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/files/upload",
                            json={"base64_data": b64, "filename": "big.txt",
                                  "content_type": "text/plain"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 413


# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK RELAY
# ══════════════════════════════════════════════════════════════════════════════

class TestWebhookRelay:
    @patch("routes.admin.create_webhook", return_value={
        "webhook_id": "wh1", "url": "https://api.aipaygen.com/webhooks/wh1/receive"
    })
    def test_create_webhook(self, mock_create, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.post("/webhooks/create",
                            json={"agent_id": "my-agent", "label": "test hook"},
                            headers=API_KEY_HEADERS)
            assert r.status_code == 200
            assert r.get_json()["webhook_id"] == "wh1"

    @patch("routes.admin.receive_webhook_event", return_value={"event_id": "ev1"})
    def test_receive_webhook_post(self, mock_recv, client):
        r = client.post("/webhooks/wh1/receive", data="payload data")
        assert r.status_code == 200
        assert r.get_json()["received"] is True

    @patch("routes.admin.receive_webhook_event", return_value=None)
    def test_receive_webhook_not_found(self, mock_recv, client):
        r = client.post("/webhooks/unknown/receive", data="data")
        assert r.status_code == 404

    @patch("routes.admin.get_webhook", return_value={"webhook_id": "wh1", "event_count": 5})
    @patch("routes.admin.get_webhook_events", return_value=[{"event_id": "e1"}])
    def test_webhook_events(self, mock_events, mock_hook, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/webhooks/wh1/events", headers=API_KEY_HEADERS)
            assert r.status_code == 200
            data = r.get_json()
            assert data["count"] == 1
            assert data["total_received"] == 5

    @patch("routes.admin.get_webhook", return_value=None)
    def test_webhook_events_not_found(self, mock_hook, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/webhooks/unknown/events", headers=API_KEY_HEADERS)
            assert r.status_code == 404

    @patch("routes.admin.list_webhooks", return_value=[{"webhook_id": "wh1"}])
    def test_webhook_list(self, mock_list, client):
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get("/webhooks/list/my-agent", headers=API_KEY_HEADERS)
            assert r.status_code == 200
            assert r.get_json()["count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST + HEALTH HISTORY
# ══════════════════════════════════════════════════════════════════════════════

class TestSelfTest:
    @patch("routes.admin.run_canary", return_value={"all_ok": True, "checks": []})
    def test_self_test_get(self, mock_canary, client):
        r = client.get("/self-test")
        assert r.status_code == 200
        assert r.get_json()["all_ok"] is True

    @patch("routes.admin.run_canary", return_value={"all_ok": False, "checks": []})
    def test_self_test_post(self, mock_canary, client):
        r = client.post("/self-test")
        assert r.status_code == 200

    @patch("routes.admin.get_health_history", return_value=[
        {"endpoint": "/health", "status": "ok", "ts": "2026-01-01"}
    ])
    def test_health_history(self, mock_hist, client):
        r = client.get("/health/history")
        assert r.status_code == 200
        assert len(r.get_json()["history"]) == 1

    @patch("routes.admin.get_health_history", return_value=[])
    def test_health_history_with_endpoint_filter(self, mock_hist, client):
        r = client.get("/health/history?endpoint=/health&limit=10")
        assert r.status_code == 200
        mock_hist.assert_called_once_with("/health", 10)


# ══════════════════════════════════════════════════════════════════════════════
# COSTS
# ══════════════════════════════════════════════════════════════════════════════

class TestCosts:
    @patch("routes.admin.is_cost_throttled", return_value=False)
    @patch("routes.admin.get_daily_cost", return_value={
        "total_cost_usd": 1.23, "calls": 50
    })
    def test_costs(self, mock_cost, mock_throttle, client):
        r = client.get("/costs")
        assert r.status_code == 200
        data = r.get_json()
        assert data["today"]["total_cost_usd"] == 1.23
        assert data["throttled"] is False
        assert "daily_limit_usd" in data


# ══════════════════════════════════════════════════════════════════════════════
# ECONOMY STATUS
# ══════════════════════════════════════════════════════════════════════════════

class TestEconomy:
    @patch("routes.admin.get_trending_topics", return_value=[{"topic": "ai", "score": 5}])
    @patch("routes.admin.is_cost_throttled", return_value=False)
    @patch("routes.admin.get_daily_cost", return_value={"total_cost_usd": 0.5})
    @patch("routes.admin.browse_tasks", return_value=[])
    def test_economy_status(self, mock_browse, mock_cost, mock_throttle, mock_trending, client):
        r = client.get("/economy/status")
        assert r.status_code == 200
        data = r.get_json()
        assert "stats" in data
        assert "task_board" in data
        assert "knowledge_base" in data


# ══════════════════════════════════════════════════════════════════════════════
# RSS FEED
# ══════════════════════════════════════════════════════════════════════════════

class TestRSSFeed:
    @patch("routes.admin.get_blog_post", return_value={"content": "<p>Hello</p>"})
    @patch("routes.admin.list_blog_posts", return_value=[
        {"slug": "post-1", "title": "Post 1", "generated_at": "2026-01-01", "endpoint": "research"},
    ])
    def test_rss_feed(self, mock_list, mock_get, client):
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert "application/rss+xml" in r.content_type
        assert b"<title>AiPayGen Developer Blog</title>" in r.data
        assert b"Post 1" in r.data

    @patch("routes.admin.get_blog_post", return_value=None)
    @patch("routes.admin.list_blog_posts", return_value=[])
    def test_rss_feed_empty(self, mock_list, mock_get, client):
        r = client.get("/feed.xml")
        assert r.status_code == 200
        assert b"<channel>" in r.data


# ══════════════════════════════════════════════════════════════════════════════
# OG IMAGE, FAVICON
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticAssets:
    def test_og_image(self, client):
        r = client.get("/og-image.png")
        assert r.status_code == 200
        assert "svg" in r.content_type
        assert b"AiPayGen" in r.data

    def test_favicon_svg(self, client):
        r = client.get("/favicon.svg")
        assert r.status_code == 200
        assert "svg" in r.content_type

    def test_favicon_ico(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 204


# ══════════════════════════════════════════════════════════════════════════════
# CHANGELOG
# ══════════════════════════════════════════════════════════════════════════════

class TestChangelog:
    @patch("routes.admin.run_canary")
    @patch("routes.admin.get_daily_cost", return_value={"total_cost_usd": 0.0})
    @patch("routes.admin.list_blog_posts", return_value=[])
    def test_changelog(self, mock_posts, mock_cost, mock_canary, client):
        with patch("routes.admin.os.path.exists", return_value=False):
            r = client.get("/changelog")
            assert r.status_code == 200
            assert b"Changelog" in r.data
            assert b"text/html" in r.content_type.encode()


# ══════════════════════════════════════════════════════════════════════════════
# INDEXNOW
# ══════════════════════════════════════════════════════════════════════════════

class TestIndexNow:
    def test_indexnow_verify(self, client):
        key = os.getenv("INDEXNOW_KEY", "aipaygen2026indexnow")
        r = client.get(f"/{key}.txt")
        assert r.status_code == 200
        assert key.encode() in r.data


# ══════════════════════════════════════════════════════════════════════════════
# REDDIT POSTS
# ══════════════════════════════════════════════════════════════════════════════

class TestRedditPosts:
    @patch("routes.admin.list_blog_posts", return_value=[
        {"slug": "test", "title": "Test Post"}
    ])
    def test_reddit_posts(self, mock_posts, client):
        r = client.get("/reddit-posts")
        assert r.status_code == 200
        data = r.get_json()
        assert "subreddits" in data
        assert len(data["subreddits"]) >= 1
        assert "note" in data


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN CRYPTO DEPOSITS
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminCryptoDeposits:
    @patch("crypto_deposits.get_all_deposits", return_value=[
        {"tx_hash": "0xabc", "amount": 5.0, "status": "confirmed"}
    ])
    def test_crypto_deposits(self, mock_deps, client):
        r = client.get("/admin/crypto/deposits", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        data = r.get_json()
        assert data["count"] == 1

    def test_crypto_deposits_no_auth(self, client):
        r = client.get("/admin/crypto/deposits")
        assert r.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN FUNNEL (JSON endpoint — the require_admin one)
# ══════════════════════════════════════════════════════════════════════════════

class TestAdminFunnelJSON:
    @patch("routes.admin.get_funnel_stats", return_value={
        "total_events": 100, "by_type": {}, "daily": []
    })
    def test_admin_funnel_json(self, mock_stats, client):
        r = client.get("/admin/funnel", headers=ADMIN_HEADERS)
        assert r.status_code == 200

    @patch("routes.admin.get_funnel_stats", return_value={
        "total_events": 0, "by_type": {}, "daily": []
    })
    def test_admin_funnel_custom_days(self, mock_stats, client):
        r = client.get("/admin/funnel?days=30", headers=ADMIN_HEADERS)
        assert r.status_code == 200
