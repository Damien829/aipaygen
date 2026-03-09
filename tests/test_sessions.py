import pytest, os, json
os.environ.setdefault("SESSIONS_DB", ":memory:")

from sessions import init_sessions_db, create_session, get_session, update_session_context, cleanup_expired

def setup_module():
    init_sessions_db()

def test_create_session():
    sid = create_session(agent_id="agent-1", context={"topic": "AI"})
    assert sid is not None
    assert len(sid) > 10

def test_get_session():
    sid = create_session(agent_id="agent-2", context={"topic": "ML"})
    s = get_session(sid)
    assert s["agent_id"] == "agent-2"
    assert s["context"]["topic"] == "ML"

def test_update_context():
    sid = create_session(agent_id="agent-3", context={"history": []})
    update_session_context(sid, {"history": [{"role": "user", "content": "hello"}]})
    s = get_session(sid)
    assert len(s["context"]["history"]) == 1

def test_session_not_found():
    assert get_session("nonexistent-id-12345") is None

def test_create_session_default_context():
    sid = create_session(agent_id="agent-4")
    s = get_session(sid)
    assert s["context"] == {}

def test_cleanup_expired():
    # Just verify it doesn't crash
    cleanup_expired()
