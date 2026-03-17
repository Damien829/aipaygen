"""Tests for the showcase social proof system."""
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ["SHOWCASE_DB"] = ":memory:"

import showcase


def setup_function():
    """Reset DB before each test."""
    showcase.DB_PATH = ":memory:"
    showcase._memory_conn = None  # Force new in-memory DB
    showcase.init_showcase_db()


# ── DB + CRUD ────────────────────────────────────────────────────────────────

def test_init_creates_table():
    showcase.init_showcase_db()
    entries = showcase.get_approved()
    assert isinstance(entries, list)


def test_log_and_get_pending():
    showcase.log_showcase("research", "AI agents", "Found 12 frameworks", 1200, "claude-haiku")
    pending = showcase.get_pending()
    assert len(pending) == 1
    assert pending[0]["tool_name"] == "research"
    assert pending[0]["approved"] == 0


def test_approved_empty_by_default():
    showcase.log_showcase("code", "Python parser", "Generated code", 800, "claude-haiku")
    assert len(showcase.get_approved()) == 0


def test_approve_entry():
    showcase.log_showcase("summarize", "whitepaper", "Summary text", 600, "claude-haiku")
    pending = showcase.get_pending()
    entry_id = pending[0]["id"]
    assert showcase.approve(entry_id)
    assert len(showcase.get_approved()) == 1
    assert len(showcase.get_pending()) == 0


def test_reject_entry():
    showcase.log_showcase("translate", "hello world", "hola mundo", 500, "claude-haiku")
    pending = showcase.get_pending()
    entry_id = pending[0]["id"]
    assert showcase.reject(entry_id)
    assert len(showcase.get_pending()) == 0
    assert len(showcase.get_approved()) == 0


def test_approve_nonexistent():
    assert not showcase.approve(9999)


def test_reject_nonexistent():
    assert not showcase.reject(9999)


def test_input_sanitized():
    showcase.log_showcase("code", "<script>alert(1)</script>", "output", 100, "model")
    pending = showcase.get_pending()
    assert "<script>" not in pending[0]["input_preview"]
    assert "&lt;script&gt;" in pending[0]["input_preview"]


def test_input_truncated():
    long_input = "x" * 200
    showcase.log_showcase("code", long_input, "out", 100, "model")
    pending = showcase.get_pending()
    assert len(pending[0]["input_preview"]) <= 100


def test_output_truncated():
    long_output = "y" * 500
    showcase.log_showcase("code", "in", long_output, 100, "model")
    pending = showcase.get_pending()
    assert len(pending[0]["output_preview"]) <= 200


# ── is_interesting ───────────────────────────────────────────────────────────

def test_interesting_research_fast():
    assert showcase.is_interesting("research", 1500)


def test_interesting_code_fast():
    assert showcase.is_interesting("code", 800)


def test_not_interesting_slow():
    assert not showcase.is_interesting("research", 5000)


def test_not_interesting_wrong_tool():
    assert not showcase.is_interesting("get_weather", 500)


def test_all_interesting_tools():
    for tool in showcase.INTERESTING_TOOLS:
        assert showcase.is_interesting(tool, 1000)


# ── Seed Data ────────────────────────────────────────────────────────────────

def test_seed_initial_data():
    assert showcase.seed_initial_data()
    approved = showcase.get_approved(20)
    assert len(approved) == 10
    tools = {e["tool_name"] for e in approved}
    assert "research" in tools
    assert "code" in tools


def test_seed_idempotent():
    showcase.seed_initial_data()
    assert not showcase.seed_initial_data()  # second call returns False
    assert len(showcase.get_approved(20)) == 10  # still 10


# ── Limit bounds ─────────────────────────────────────────────────────────────

def test_get_approved_limit():
    showcase.seed_initial_data()
    assert len(showcase.get_approved(3)) == 3


def test_get_approved_negative_limit():
    showcase.seed_initial_data()
    result = showcase.get_approved(-5)
    assert len(result) >= 1  # clamped to 1


# ── API routes (via Flask test client) ───────────────────────────────────────

@pytest.fixture
def client():
    """Create a minimal Flask app with the meta_bp and admin_bp for testing."""
    from flask import Flask
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "routes"))
    from routes.meta import meta_bp
    from routes.admin import admin_bp

    app = Flask(__name__, template_folder=os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates"))
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test-secret-key-32bytes-long!!"
    app.register_blueprint(meta_bp)
    app.register_blueprint(admin_bp)
    return app.test_client()


def test_get_showcase_api(client):
    showcase.seed_initial_data()
    resp = client.get("/api/showcase")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "showcase" in data
    assert data["count"] > 0


def test_get_showcase_limit(client):
    showcase.seed_initial_data()
    resp = client.get("/api/showcase?limit=3")
    data = resp.get_json()
    assert len(data["showcase"]) == 3


def test_post_showcase_api(client):
    resp = client.post("/api/showcase", json={
        "tool_name": "research",
        "input_preview": "test input",
        "output_preview": "test output",
        "response_time_ms": 1000,
        "model": "claude-haiku",
    })
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["status"] == "captured"


def test_post_showcase_missing_tool(client):
    resp = client.post("/api/showcase", json={"input_preview": "test"})
    assert resp.status_code == 400


def test_admin_showcase_requires_auth(client):
    os.environ["ADMIN_SECRET"] = "test-admin-secret"
    resp = client.get("/admin/showcase")
    assert resp.status_code == 401
    del os.environ["ADMIN_SECRET"]


def test_admin_approve_requires_auth(client):
    os.environ["ADMIN_SECRET"] = "test-admin-secret"
    resp = client.post("/admin/showcase/1/approve")
    assert resp.status_code == 401
    del os.environ["ADMIN_SECRET"]


def test_admin_reject_requires_auth(client):
    os.environ["ADMIN_SECRET"] = "test-admin-secret"
    resp = client.post("/admin/showcase/1/reject")
    assert resp.status_code == 401
    del os.environ["ADMIN_SECRET"]


def test_admin_approve_with_auth(client):
    os.environ["ADMIN_SECRET"] = "test-admin-secret"
    showcase.log_showcase("code", "test", "output", 500, "model")
    pending = showcase.get_pending()
    entry_id = pending[0]["id"]
    resp = client.post(f"/admin/showcase/{entry_id}/approve",
                       headers={"Authorization": "Bearer test-admin-secret"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "approved"
    del os.environ["ADMIN_SECRET"]


def test_admin_reject_with_auth(client):
    os.environ["ADMIN_SECRET"] = "test-admin-secret"
    showcase.log_showcase("code", "test", "output", 500, "model")
    pending = showcase.get_pending()
    entry_id = pending[0]["id"]
    resp = client.post(f"/admin/showcase/{entry_id}/reject",
                       headers={"Authorization": "Bearer test-admin-secret"})
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "rejected"
    del os.environ["ADMIN_SECRET"]
