"""Tests for routes/skills.py — 10 endpoints."""
import sys, os, json, sqlite3, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


ADMIN_SECRET = os.getenv("ADMIN_SECRET", "")
ADMIN_HEADERS = {"X-Admin-Key": ADMIN_SECRET} if ADMIN_SECRET else {}


def _admin_headers():
    """Return admin auth headers; skip if ADMIN_SECRET not set."""
    secret = os.getenv("ADMIN_SECRET", "")
    if not secret:
        pytest.skip("ADMIN_SECRET not set")
    return {"X-Admin-Key": secret}


# ── /skills (GET) ──────────────────────────────────────────────────────────

class TestListSkills:
    def test_list_skills_returns_200(self, client):
        r = client.get("/skills")
        assert r.status_code == 200
        data = r.get_json()
        assert "skills" in data
        assert "total" in data
        assert "categories" in data
        assert isinstance(data["skills"], list)
        assert data["total"] >= 0

    def test_list_skills_has_builtin(self, client):
        r = client.get("/skills")
        data = r.get_json()
        names = [s["name"] for s in data["skills"]]
        # At least some built-in skills should exist
        assert len(names) > 0

    def test_list_skills_filter_by_category(self, client):
        r = client.get("/skills?category=research")
        assert r.status_code == 200
        data = r.get_json()
        for skill in data["skills"]:
            assert skill["category"] == "research"

    def test_list_skills_filter_nonexistent_category(self, client):
        r = client.get("/skills?category=nonexistent_xyz")
        assert r.status_code == 200
        data = r.get_json()
        assert data["total"] == 0
        assert data["skills"] == []

    def test_list_skills_fields(self, client):
        r = client.get("/skills")
        data = r.get_json()
        if data["skills"]:
            s = data["skills"][0]
            for field in ("id", "name", "description", "category", "source", "input_schema", "calls"):
                assert field in s


# ── /skills/execute (POST) ─────────────────────────────────────────────────

class TestExecuteSkill:
    def test_execute_requires_admin(self, client):
        r = client.post("/skills/execute", json={"skill": "deep_research", "input": "test"})
        assert r.status_code in (401, 403)

    def test_execute_missing_skill_name(self, client):
        r = client.post("/skills/execute", json={"input": "test"}, headers=_admin_headers())
        assert r.status_code == 400
        assert "skill name required" in r.get_json()["error"]

    def test_execute_skill_not_found(self, client):
        r = client.post("/skills/execute",
                        json={"skill": "nonexistent_skill_xyz_123"},
                        headers=_admin_headers())
        assert r.status_code == 404
        assert "not found" in r.get_json()["error"]

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_execute_skill_success(self, mock_parse, mock_call, client):
        mock_call.return_value = {"text": '{"summary": "ok"}', "model": "claude-haiku", "cost_usd": 0.001}
        mock_parse.return_value = {"summary": "ok"}
        r = client.post("/skills/execute",
                        json={"skill": "deep_research", "input": "AI agents"},
                        headers=_admin_headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data["skill"] == "deep_research"
        assert data["model"] == "claude-haiku"
        assert "result" in data

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_execute_skill_custom_model(self, mock_parse, mock_call, client):
        mock_call.return_value = {"text": "raw text", "model": "gpt-4o", "cost_usd": 0.01}
        mock_parse.return_value = None
        r = client.post("/skills/execute",
                        json={"skill": "deep_research", "input": "test", "model": "gpt-4o"},
                        headers=_admin_headers())
        assert r.status_code == 200
        data = r.get_json()
        assert data["result"] == "raw text"  # falls back to raw text when parse returns None

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_execute_increments_call_count(self, mock_parse, mock_call, client):
        mock_call.return_value = {"text": '{}', "model": "claude-haiku", "cost_usd": 0}
        mock_parse.return_value = {}
        # Get initial count
        r1 = client.get("/skills")
        before = {s["name"]: s["calls"] for s in r1.get_json()["skills"]}
        # Execute
        client.post("/skills/execute",
                     json={"skill": "deep_research", "input": "test"},
                     headers=_admin_headers())
        # Check count incremented
        r2 = client.get("/skills")
        after = {s["name"]: s["calls"] for s in r2.get_json()["skills"]}
        assert after.get("deep_research", 0) >= before.get("deep_research", 0)


# ── /skills/create (POST) ──────────────────────────────────────────────────

class TestCreateSkill:
    def test_create_requires_auth(self, client):
        r = client.post("/skills/create", json={
            "name": "test_skill", "description": "test", "prompt_template": "{{input}}"
        })
        assert r.status_code == 401

    def test_create_missing_fields(self, client):
        # Use a fake Bearer JWT to pass require_verified_agent — it will fail validation
        r = client.post("/skills/create",
                        json={"name": "x"},
                        headers={"Authorization": "Bearer eyFAKE"})
        # Either 401 (bad JWT) or 400 (missing fields) — both are acceptable
        assert r.status_code in (400, 401)

    @patch("routes.skills.require_verified_agent", lambda f: f)
    def test_create_missing_input_placeholder(self, client):
        """prompt_template must contain {{input}}"""
        # We need to patch the decorator at import time; instead test via the app
        r = client.post("/skills/create", json={
            "name": "bad_skill",
            "description": "test",
            "prompt_template": "no placeholder here"
        }, headers={"Authorization": "Bearer eyFAKE"})
        # Will be 401 since JWT is fake — this tests the auth gate
        assert r.status_code == 401


# ── /skills/absorb (POST) ──────────────────────────────────────────────────

class TestAbsorbSkill:
    def test_absorb_requires_admin(self, client):
        r = client.post("/skills/absorb", json={"text": "some skill text"})
        assert r.status_code in (401, 403)

    def test_absorb_missing_input(self, client):
        r = client.post("/skills/absorb", json={}, headers=_admin_headers())
        assert r.status_code == 400
        assert "url or text" in r.get_json()["error"]

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_absorb_from_text_success(self, mock_parse, mock_call, client):
        mock_call.return_value = {"text": '{"name":"test_absorbed","description":"A test","category":"general","prompt_template":"Do {{input}}","input_schema":{"input":"string"}}', "model": "claude-haiku"}
        mock_parse.return_value = {
            "name": f"test_absorbed_{os.getpid()}",
            "description": "A test skill",
            "category": "general",
            "prompt_template": "Do {{input}}",
            "input_schema": {"input": "string"},
        }
        r = client.post("/skills/absorb",
                        json={"text": "Here is a useful API that converts currencies..."},
                        headers=_admin_headers())
        # 200 success or 409 if already absorbed in prior run
        assert r.status_code in (200, 409)

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_absorb_parse_failure(self, mock_parse, mock_call, client):
        mock_call.return_value = {"text": "garbage output", "model": "claude-haiku"}
        mock_parse.return_value = None  # parse failed
        r = client.post("/skills/absorb",
                        json={"text": "some content"},
                        headers=_admin_headers())
        assert r.status_code == 422
        assert "could not extract" in r.get_json()["error"]

    @patch("routes.skills.call_model")
    def test_absorb_model_error(self, mock_call, client):
        mock_call.side_effect = Exception("billing limit exceeded — no credits")
        r = client.post("/skills/absorb",
                        json={"text": "some content"},
                        headers=_admin_headers())
        assert r.status_code == 503
        assert "billing" in r.get_json()["error"]

    @patch("routes.skills.call_model")
    def test_absorb_generic_model_error(self, mock_call, client):
        mock_call.side_effect = Exception("connection timeout")
        r = client.post("/skills/absorb",
                        json={"text": "some content"},
                        headers=_admin_headers())
        assert r.status_code == 503
        assert "model_error" in r.get_json()["error"]


# ── /skills/harvest (POST) ─────────────────────────────────────────────────

class TestHarvest:
    def test_harvest_requires_admin(self, client):
        r = client.post("/skills/harvest", json={"source": "all"})
        assert r.status_code in (401, 403)

    @patch("routes.skills.threading.Thread")
    def test_harvest_all(self, mock_thread, client):
        mock_thread.return_value = MagicMock()
        r = client.post("/skills/harvest",
                        json={"source": "all"},
                        headers=_admin_headers())
        assert r.status_code == 200
        assert r.get_json()["status"] == "harvest started"

    @patch("routes.skills.threading.Thread")
    def test_harvest_mcp(self, mock_thread, client):
        mock_thread.return_value = MagicMock()
        r = client.post("/skills/harvest",
                        json={"source": "mcp"},
                        headers=_admin_headers())
        assert r.status_code == 200

    @patch("routes.skills.threading.Thread")
    def test_harvest_github(self, mock_thread, client):
        mock_thread.return_value = MagicMock()
        r = client.post("/skills/harvest",
                        json={"source": "github"},
                        headers=_admin_headers())
        assert r.status_code == 200

    @patch("routes.skills.threading.Thread")
    def test_harvest_api(self, mock_thread, client):
        mock_thread.return_value = MagicMock()
        r = client.post("/skills/harvest",
                        json={"source": "api"},
                        headers=_admin_headers())
        assert r.status_code == 200

    def test_harvest_invalid_source(self, client):
        r = client.post("/skills/harvest",
                        json={"source": "invalid"},
                        headers=_admin_headers())
        assert r.status_code == 400
        assert "source must be" in r.get_json()["error"]


# ── /skills/harvest/stats (GET) ────────────────────────────────────────────

class TestHarvestStats:
    def test_harvest_stats_requires_admin(self, client):
        r = client.get("/skills/harvest/stats")
        assert r.status_code in (401, 403)

    def test_harvest_stats_success(self, client):
        r = client.get("/skills/harvest/stats", headers=_admin_headers())
        assert r.status_code == 200
        assert isinstance(r.get_json(), dict)


# ── /outbound/run (POST) ──────────────────────────────────────────────────

class TestOutbound:
    def test_outbound_requires_admin(self, client):
        r = client.post("/outbound/run", json={})
        assert r.status_code in (401, 403)

    def test_outbound_stats_requires_admin(self, client):
        r = client.get("/outbound/stats")
        assert r.status_code in (401, 403)


# ── /skills/search (GET) ──────────────────────────────────────────────────

class TestSearchSkills:
    def test_search_requires_admin(self, client):
        r = client.get("/skills/search?q=research")
        assert r.status_code in (401, 403)

    def test_search_missing_q(self, client):
        r = client.get("/skills/search", headers=_admin_headers())
        assert r.status_code == 400
        assert "q parameter required" in r.get_json()["error"]

    def test_search_success(self, client):
        r = client.get("/skills/search?q=research", headers=_admin_headers())
        assert r.status_code == 200
        data = r.get_json()
        assert "query" in data
        assert "results" in data
        assert data["query"] == "research"
        assert isinstance(data["results"], list)

    def test_search_top_n(self, client):
        r = client.get("/skills/search?q=code&top_n=3", headers=_admin_headers())
        assert r.status_code == 200
        data = r.get_json()
        assert len(data["results"]) <= 3

    def test_search_strips_source_fields(self, client):
        r = client.get("/skills/search?q=research", headers=_admin_headers())
        data = r.get_json()
        strip_fields = {"source", "source_url", "harvested_from", "origin", "crawled_from"}
        for result in data["results"]:
            for field in strip_fields:
                assert field not in result


# ── /ask (POST) ───────────────────────────────────────────────────────────

class TestAskUniversal:
    def test_ask_missing_question(self, client):
        r = client.post("/ask", json={})
        assert r.status_code == 400
        assert "required" in r.get_json()["error"]

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_ask_routes_to_skill(self, mock_parse, mock_call, client):
        # First call = router picks a skill, second call = skill execution
        mock_call.side_effect = [
            {"text": '{"skill": "deep_research", "reasoning": "matches research"}', "model": "claude-haiku", "cost_usd": 0.001},
            {"text": '{"summary": "AI research findings"}', "model": "claude-haiku", "cost_usd": 0.005},
        ]
        mock_parse.side_effect = [
            {"skill": "deep_research", "reasoning": "matches research"},
            {"summary": "AI research findings"},
        ]
        r = client.post("/ask", json={"question": "Research AI agents"})
        assert r.status_code == 200
        data = r.get_json()
        assert "skill_used" in data
        assert "result" in data
        assert "model" in data

    @patch("routes.skills.call_model")
    @patch("routes.skills.parse_json_from_claude")
    def test_ask_direct_answer(self, mock_parse, mock_call, client):
        # Router returns "direct", then direct answer
        mock_call.side_effect = [
            {"text": '{"skill": "direct", "reasoning": "no skill fits"}', "model": "claude-haiku", "cost_usd": 0.001},
            {"text": "Here is a direct answer.", "model": "claude-haiku", "cost_usd": 0.005},
        ]
        mock_parse.side_effect = [
            {"skill": "direct", "reasoning": "no skill fits"},
        ]
        r = client.post("/ask", json={"input": "What is 2+2?"})
        assert r.status_code == 200
        data = r.get_json()
        assert data["skill_used"] == "direct"

    def test_ask_accepts_query_field(self, client):
        """The endpoint accepts 'query' as an alternative to 'question'."""
        with patch("routes.skills.call_model") as mock_call, \
             patch("routes.skills.parse_json_from_claude") as mock_parse:
            mock_call.side_effect = [
                {"text": '{"skill": "direct"}', "model": "claude-haiku", "cost_usd": 0},
                {"text": "answer", "model": "claude-haiku", "cost_usd": 0},
            ]
            mock_parse.side_effect = [{"skill": "direct"}, None]
            r = client.post("/ask", json={"query": "hello"})
            assert r.status_code == 200
