"""Extended builder tests — template filtering, agent config persistence,
_row_to_dict helper, duplicate agent names, and run history ordering."""

import sys, os, json, sqlite3, tempfile, uuid
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock

import routes.builder as builder_mod

_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_test_db_path = _test_db.name
_test_db.close()
builder_mod.DB_PATH = _test_db_path

FAKE_KEY = "apk_test_ext_key"
AUTH_HEADER = {"Authorization": f"Bearer {FAKE_KEY}"}


def _validate_key_mock(key):
    if key == FAKE_KEY:
        return {"key": FAKE_KEY, "balance_usd": 100.0, "is_active": 1}
    return None


def _reset_db():
    builder_mod.DB_PATH = _test_db_path
    c = sqlite3.connect(_test_db_path)
    for tbl in ["agents_custom", "agent_templates", "agent_runs"]:
        c.execute(f"DROP TABLE IF EXISTS {tbl}")
    c.commit()
    c.close()
    builder_mod.init_builder_db()


@pytest.fixture(scope="module")
def client():
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        from app import app
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


@pytest.fixture(autouse=True)
def clean_db():
    _reset_db()


def _create_agent(client, **overrides):
    payload = {
        "name": "Ext Agent",
        "system_prompt": "You are an extended test agent.",
        "tools": ["research"],
        "model": "auto",
        "memory_enabled": True,
    }
    payload.update(overrides)
    with patch("api_keys.validate_key", side_effect=_validate_key_mock):
        with patch("routes.builder.validate_key", side_effect=_validate_key_mock):
            r = client.post("/agents/build", json=payload,
                            headers=AUTH_HEADER,
                            content_type="application/json")
    return r, r.get_json()


# ---------------------------------------------------------------------------
# _row_to_dict helper
# ---------------------------------------------------------------------------

class TestRowToDict:

    def test_none_returns_none(self):
        assert builder_mod._row_to_dict(None) is None

    def test_json_fields_parsed(self):
        """JSON string fields (tools, knowledge_base, schedule) should be parsed."""
        conn = sqlite3.connect(_test_db_path)
        conn.row_factory = sqlite3.Row
        agent_id = str(uuid.uuid4())
        now = "2026-01-01T00:00:00Z"
        conn.execute("""
            INSERT INTO agents_custom
            (id, creator_key, name, system_prompt, tools, knowledge_base, schedule,
             model, memory_enabled, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'auto', 1, 'active', ?, ?)
        """, (agent_id, FAKE_KEY, "Test", "Prompt",
              '["research","summarize"]', '["doc.txt"]',
              '{"type":"loop","config":{"minutes":30}}', now, now))
        conn.commit()
        row = conn.execute("SELECT * FROM agents_custom WHERE id=?", (agent_id,)).fetchone()
        conn.close()

        d = builder_mod._row_to_dict(row)
        assert isinstance(d["tools"], list)
        assert d["tools"] == ["research", "summarize"]
        assert isinstance(d["knowledge_base"], list)
        assert isinstance(d["schedule"], dict)
        assert d["schedule"]["type"] == "loop"

    def test_invalid_json_left_as_string(self):
        conn = sqlite3.connect(_test_db_path)
        conn.row_factory = sqlite3.Row
        agent_id = str(uuid.uuid4())
        now = "2026-01-01T00:00:00Z"
        conn.execute("""
            INSERT INTO agents_custom
            (id, creator_key, name, system_prompt, tools, model, memory_enabled,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'auto', 1, 'active', ?, ?)
        """, (agent_id, FAKE_KEY, "Test", "Prompt", "not-json", now, now))
        conn.commit()
        row = conn.execute("SELECT * FROM agents_custom WHERE id=?", (agent_id,)).fetchone()
        conn.close()

        d = builder_mod._row_to_dict(row)
        assert d["tools"] == "not-json"  # stays as string


# ---------------------------------------------------------------------------
# Duplicate agent names allowed
# ---------------------------------------------------------------------------

class TestDuplicateAgentNames:

    def test_same_name_different_agents(self, client):
        r1, d1 = _create_agent(client, name="Duplicate Name")
        r2, d2 = _create_agent(client, name="Duplicate Name")
        assert r1.status_code == 201
        assert r2.status_code == 201
        assert d1["agent_id"] != d2["agent_id"]


# ---------------------------------------------------------------------------
# Agent config persistence round-trip
# ---------------------------------------------------------------------------

class TestConfigPersistence:

    def test_tools_persist_correctly(self, client):
        tools = ["research", "summarize", "code"]
        _, created = _create_agent(client, tools=tools)
        agent_id = created["agent_id"]
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get(f"/agents/custom/{agent_id}", headers=AUTH_HEADER)
        data = r.get_json()
        assert data["tools"] == tools

    def test_model_persists(self, client):
        _, created = _create_agent(client, model="gpt-4")
        agent_id = created["agent_id"]
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get(f"/agents/custom/{agent_id}", headers=AUTH_HEADER)
        assert r.get_json()["model"] == "gpt-4"

    def test_knowledge_base_persists(self, client):
        _, created = _create_agent(client, knowledge_base=["doc1.txt", "doc2.pdf"])
        agent_id = created["agent_id"]
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get(f"/agents/custom/{agent_id}", headers=AUTH_HEADER)
        data = r.get_json()
        assert data["knowledge_base"] == ["doc1.txt", "doc2.pdf"]


# ---------------------------------------------------------------------------
# Run history ordering — most recent first
# ---------------------------------------------------------------------------

class TestRunHistoryOrdering:

    def test_runs_ordered_desc(self, client):
        _, created = _create_agent(client)
        agent_id = created["agent_id"]

        conn = sqlite3.connect(_test_db_path)
        for i in range(3):
            conn.execute("""
                INSERT INTO agent_runs (id, agent_id, task, result, status, triggered_by, created_at)
                VALUES (?, ?, ?, ?, 'completed', 'manual', ?)
            """, (str(uuid.uuid4()), agent_id, f"task-{i}",
                  json.dumps({"i": i}), f"2026-01-0{i+1}T00:00:00Z"))
        conn.commit()
        conn.close()

        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            r = client.get(f"/agents/custom/{agent_id}/runs", headers=AUTH_HEADER)
        data = r.get_json()
        assert data["count"] == 3
        # Most recent first
        assert data["runs"][0]["task"] == "task-2"
        assert data["runs"][2]["task"] == "task-0"


# ---------------------------------------------------------------------------
# Template seeding — verify structure
# ---------------------------------------------------------------------------

class TestTemplateStructure:

    def test_all_templates_have_required_fields(self, client):
        r = client.get("/builder/templates")
        data = r.get_json()
        for t in data["templates"]:
            assert "id" in t
            assert "name" in t
            assert len(t["name"]) > 0
            assert "system_prompt" in t
            assert len(t["system_prompt"]) > 10
            assert "category" in t
            assert "tools" in t

    def test_template_categories_diverse(self, client):
        r = client.get("/builder/templates")
        data = r.get_json()
        categories = {t["category"] for t in data["templates"]}
        # Should have multiple categories
        assert len(categories) >= 5

    def test_templates_have_descriptions(self, client):
        r = client.get("/builder/templates")
        data = r.get_json()
        for t in data["templates"]:
            assert t.get("description") is not None
            assert len(t["description"]) > 0


# ---------------------------------------------------------------------------
# List agents filters only creator's agents
# ---------------------------------------------------------------------------

class TestAgentIsolation:

    def test_agents_isolated_by_key(self, client):
        """Each API key only sees its own agents."""
        _create_agent(client, name="My Agent")

        other_key = "apk_other_ext"
        other_header = {"Authorization": f"Bearer {other_key}"}

        def other_validate(key):
            if key == other_key:
                return {"key": other_key, "balance_usd": 50.0, "is_active": 1}
            return None

        with patch("api_keys.validate_key", side_effect=other_validate):
            r = client.get("/agents/custom", headers=other_header)
        data = r.get_json()
        assert data["count"] == 0  # other user sees none


# ---------------------------------------------------------------------------
# Update agent — tools validation on update
# ---------------------------------------------------------------------------

class TestUpdateToolsValidation:

    def test_update_invalid_tool_rejected(self, client):
        _, created = _create_agent(client)
        agent_id = created["agent_id"]
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            with patch("routes.builder.validate_key", side_effect=_validate_key_mock):
                r = client.put(f"/agents/custom/{agent_id}",
                               json={"tools": ["INVALID!"]},
                               headers=AUTH_HEADER)
        assert r.status_code == 400

    def test_update_too_many_tools_rejected(self, client):
        _, created = _create_agent(client)
        agent_id = created["agent_id"]
        with patch("api_keys.validate_key", side_effect=_validate_key_mock):
            with patch("routes.builder.validate_key", side_effect=_validate_key_mock):
                r = client.put(f"/agents/custom/{agent_id}",
                               json={"tools": ["t"] * 251},
                               headers=AUTH_HEADER)
        assert r.status_code == 400
