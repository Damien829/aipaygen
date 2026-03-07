"""Tests for Discovery Scouts."""
import os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_init_scout_db():
    from discovery_scouts import init_scout_db, _scout_conn
    init_scout_db()
    with _scout_conn() as c:
        tables = [r[0] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
    assert "scout_outreach" in tables
    assert "scout_conversions" in tables


def test_log_and_dedup():
    from discovery_scouts import init_scout_db, _log_outreach, _already_scouted, _scout_conn
    init_scout_db()
    # Clean up stale test data so INSERT OR IGNORE doesn't skip
    with _scout_conn() as c:
        c.execute("DELETE FROM scout_outreach WHERE scout='test' AND target_id='target1' AND action='test_action'")
    _log_outreach("test", "target1", "test_action", message="hi")
    assert _already_scouted("test", "target1", within_days=1)
    assert not _already_scouted("test", "target_other", within_days=1)


def test_ref_code():
    from discovery_scouts import _ref_code
    code = _ref_code("github", "test/repo")
    assert code.startswith("gi_")
    assert len(code) == 11  # 2 chars + _ + 8 hex


def test_github_scout_search(monkeypatch):
    from discovery_scouts import GitHubScout, init_scout_db
    init_scout_db()

    def fake_call_model(model, messages, **kw):
        return {"text": "Integration suggestion\n\nCheck out AiPayGen for 646+ skills.",
                "cost_usd": 0.001, "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        if "search/repositories" in url:
            return {"status": 200, "body": json.dumps({"items": [
                {"full_name": "test/agent-repo", "html_url": "https://github.com/test/agent-repo",
                 "description": "An AI agent framework", "stargazers_count": 100,
                 "topics": ["ai-agent", "tools"]}
            ]}), "headers": {}}
        if "issues" in url and kw.get("method") == "POST":
            return {"status": 201, "body": '{"html_url": "https://github.com/test/agent-repo/issues/1"}', "headers": {}}
        return {"status": 200, "body": "{}", "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    scout = GitHubScout(fake_call_model)
    result = scout.run(max_actions=1)
    assert result["issues_opened"] >= 0
    assert "errors" in result


def test_registry_scout_run(monkeypatch):
    from discovery_scouts import RegistryScout, init_scout_db
    init_scout_db()

    def fake_call_model(model, messages, **kw):
        return {"text": "Found 3 new registries", "cost_usd": 0.001,
                "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        return {"status": 200, "body": "{}", "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    scout = RegistryScout(fake_call_model)
    result = scout.run(max_actions=2)
    assert "registered" in result
    assert "errors" in result


def test_social_scout_run(monkeypatch):
    from discovery_scouts import SocialScout, init_scout_db
    init_scout_db()

    def fake_call_model(model, messages, **kw):
        return {"text": "Great suggestion reply", "cost_usd": 0.001,
                "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        if "reddit.com" in url:
            return {"status": 200, "body": json.dumps({
                "data": {"children": [
                    {"data": {"id": "abc123", "title": "Looking for AI agent tools",
                              "selftext": "Need MCP server provider",
                              "permalink": "/r/AutoGPT/comments/abc123/test/",
                              "num_comments": 5, "score": 10}}
                ]}
            }), "headers": {}}
        return {"status": 200, "body": "{}", "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    scout = SocialScout(fake_call_model)
    result = scout.run(max_actions=1)
    assert "threads_found" in result
    assert "errors" in result


def test_a2a_scout_run(monkeypatch):
    from discovery_scouts import A2AScout, init_scout_db
    init_scout_db()

    def fake_call_model(model, messages, **kw):
        return {"text": "Hello agent! AiPayGen offers 646+ skills.",
                "cost_usd": 0.001, "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        if "mcp.so" in url or "smithery" in url or "glama" in url:
            return {"status": 200, "body": json.dumps([
                {"url": "https://example-agent.com", "name": "TestAgent"}
            ]), "headers": {}}
        if "well-known" in url:
            return {"status": 200, "body": json.dumps({
                "name": "TestAgent", "capabilities": ["tools"]
            }), "headers": {}}
        if "messages" in url or "inbox" in url:
            return {"status": 200, "body": '{"ok": true}', "headers": {}}
        return {"status": 200, "body": "{}", "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    scout = A2AScout(fake_call_model)
    result = scout.run(max_actions=1)
    assert "agents_contacted" in result
    assert "errors" in result


def test_twitter_scout_run(monkeypatch):
    from discovery_scouts import TwitterScout, init_scout_db
    init_scout_db()

    def fake_call_model(model, messages, **kw):
        return {"text": "Check out AiPayGen! 646+ AI skills via MCP.",
                "cost_usd": 0.001, "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        return {"status": 200, "body": json.dumps({"data": []}), "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    scout = TwitterScout(fake_call_model)
    result = scout.run(max_actions=1)
    assert "tweets_found" in result
    assert "errors" in result


def test_followup_agent_run(monkeypatch):
    from discovery_scouts import FollowUpAgent, init_scout_db, _log_outreach
    init_scout_db()
    # Insert an old outreach entry
    from discovery_scouts import _scout_conn
    with _scout_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO scout_outreach (scout, target_id, action, message, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("github", "test/old-repo", "issue_opened", "test", "sent", "2026-01-01T00:00:00"),
        )

    def fake_call_model(model, messages, **kw):
        return {"text": "Follow up message", "cost_usd": 0.001,
                "input_tokens": 50, "output_tokens": 30}

    import discovery_scouts as ds
    def fake_fetch(url, **kw):
        if "issues" in url:
            return {"status": 200, "body": json.dumps([
                {"body": "Interesting!", "user": {"login": "someone"}}
            ]), "headers": {}}
        return {"status": 200, "body": "{}", "headers": {}}
    monkeypatch.setattr(ds, "_fetch", fake_fetch)

    agent = FollowUpAgent(fake_call_model)
    result = agent.run(max_actions=5)
    assert "checked" in result
    assert "errors" in result


def test_record_conversion_and_stats():
    from discovery_scouts import (
        record_scout_conversion, get_scout_stats, init_scout_db, _log_outreach
    )
    init_scout_db()
    _log_outreach("github", "test/stats-repo", "issue_opened", message="test", status="sent")
    record_scout_conversion(ref_code="gh_abc12345", caller_ip="1.2.3.4",
                            user_agent="test-agent", endpoint="/ask")
    stats = get_scout_stats()
    assert stats["total_outreach"] >= 1


def test_run_scout_by_name():
    from discovery_scouts import run_scout_by_name, init_scout_db
    init_scout_db()
    def fake_call_model(model, messages, **kw):
        return {"text": "test", "cost_usd": 0.001, "input_tokens": 50, "output_tokens": 30}
    result = run_scout_by_name("unknown_scout", fake_call_model)
    assert result is None
