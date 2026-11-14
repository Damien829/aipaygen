import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from react_agent import build_tool_registry, format_tools_for_prompt

def test_build_tool_registry():
    tools = build_tool_registry()
    assert isinstance(tools, dict)
    assert len(tools) > 10
    for name, tool in tools.items():
        assert "description" in tool
        assert "params" in tool

def test_tool_registry_includes_skills():
    tools = build_tool_registry()
    assert "execute_skill" in tools

def test_tool_registry_includes_memory():
    tools = build_tool_registry()
    assert "memory_recall" in tools
    assert "memory_store" in tools

def test_format_tools_for_prompt():
    tools = build_tool_registry()
    prompt = format_tools_for_prompt(tools)
    assert isinstance(prompt, str)
    assert "research" in prompt
    assert "execute_skill" in prompt


from react_agent import ReActAgent

def _mock_call_model(model, messages, system="", max_tokens=None, temperature=0.7, max_cost_usd=None):
    # Check if this is a follow-up (conversation history contains assistant messages)
    has_assistant = any(m.get("role") == "assistant" for m in messages)
    last_content = messages[-1]["content"] if messages else ""

    if not has_assistant and "Continue" not in last_content:
        return {"text": '{"thought": "I need to research this", "action": "research", "params": {"topic": "AI agents"}}',
                "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
                "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}
    else:
        return {"text": '{"thought": "I have enough info", "answer": "AI agents are autonomous systems."}',
                "model": "claude-haiku", "model_id": "test", "provider": "anthropic",
                "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}

def _mock_tool_handler(name, params):
    return {"result": f"Mock result for {name}", "model": "claude-haiku"}

def test_react_agent_runs_loop():
    agent = ReActAgent(call_model_fn=_mock_call_model, tool_handler_fn=_mock_tool_handler)
    result = agent.run("What are AI agents?", max_steps=5, max_cost_usd=1.0)
    assert "answer" in result
    assert "reasoning_trace" in result
    assert "total_cost_usd" in result
    assert result["steps_taken"] >= 1

def test_react_agent_respects_budget():
    def expensive_call(model, messages, **kwargs):
        return {"text": '{"thought": "thinking", "action": "research", "params": {"topic": "test"}}',
                "model": "claude-haiku", "model_id": "test", "provider": "test",
                "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.50, "selected_reason": None}
    agent = ReActAgent(call_model_fn=expensive_call, tool_handler_fn=_mock_tool_handler)
    result = agent.run("Expensive task", max_steps=10, max_cost_usd=0.60)
    assert result["steps_taken"] <= 3

def test_react_agent_respects_max_steps():
    def always_act(model, messages, **kwargs):
        return {"text": '{"thought": "keep going", "action": "research", "params": {"topic": "test"}}',
                "model": "claude-haiku", "model_id": "test", "provider": "test",
                "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0001, "selected_reason": None}
    agent = ReActAgent(call_model_fn=always_act, tool_handler_fn=_mock_tool_handler)
    result = agent.run("Infinite task", max_steps=3, max_cost_usd=100.0)
    assert result["steps_taken"] <= 3

def test_make_tool_handler():
    from react_agent import make_tool_handler
    mock_handlers = {"research": lambda d: {"summary": "test result"}}
    handler = make_tool_handler(mock_handlers, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:", agent_id="")
    result = handler("research", {"topic": "AI"})
    assert result["summary"] == "test result"

def test_react_agent_stream():
    agent = ReActAgent(call_model_fn=_mock_call_model, tool_handler_fn=_mock_tool_handler)
    events = list(agent.run_stream("What are AI agents?", max_steps=5, max_cost_usd=1.0))
    assert len(events) >= 1
    event_types = [e["event"] for e in events]
    assert "thought" in event_types or "answer" in event_types
    assert events[-1]["event"] == "done"

def test_make_tool_handler_unknown_tool():
    from react_agent import make_tool_handler
    handler = make_tool_handler({}, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:", agent_id="")
    result = handler("nonexistent", {})
    assert "error" in result

def test_make_tool_handler_uses_tfidf_engine():
    from react_agent import make_tool_handler
    mock_engine = type("MockEngine", (), {"search": lambda self, q, top_n=10: [{"name": "web_scraper", "description": "Scrape websites", "category": "web", "score": 0.95}]})()
    handler = make_tool_handler({}, memory_search_fn=None, memory_set_fn=None, skills_db_path=":memory:", agent_id="", skills_search_engine=mock_engine)
    result = handler("search_skills", {"query": "scrape"})
    assert result["count"] == 1
    assert result["skills"][0]["name"] == "web_scraper"
    assert result["skills"][0]["score"] == 0.95


# --- New tests: observation compression ---

def test_compress_observation():
    from react_agent import _compress_observation
    # Dict compression: strips metadata keys
    result = _compress_observation({"result": "hello", "model": "claude-haiku", "input_tokens": 100, "provider": "anthropic"})
    assert "hello" in result
    assert "input_tokens" not in result

    # String passthrough
    result = _compress_observation("plain text result")
    assert result == "plain text result"

    # Long text truncation
    long_text = "x" * 1000
    result = _compress_observation(long_text, max_chars=200)
    assert len(result) <= 200
    assert "[truncated]" in result


# --- New tests: tool chaining ---

def test_tool_chaining():
    """Agent can pipe output of one tool into another."""
    call_count = [0]
    def chaining_call_model(model, messages, **kwargs):
        call_count[0] += 1
        has_assistant = any(m.get("role") == "assistant" for m in messages)
        if not has_assistant:
            return {"text": '{"thought": "research then summarize", "action": "research", "params": {"topic": "AI"}, "pipe_to": {"action": "summarize", "param_key": "text"}}',
                    "model": "claude-haiku", "model_id": "test", "provider": "test",
                    "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}
        else:
            return {"text": '{"thought": "done", "answer": "AI is summarized."}',
                    "model": "claude-haiku", "model_id": "test", "provider": "test",
                    "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}

    def chain_handler(name, params):
        if name == "research":
            return {"summary": "AI is a broad field covering ML, NLP, and robotics."}
        if name == "summarize":
            return {"result": f"Summary of: {params.get('text', '')[:50]}"}
        return {"error": "unknown"}

    agent = ReActAgent(call_model_fn=chaining_call_model, tool_handler_fn=chain_handler)
    result = agent.run("Research and summarize AI", max_steps=5, max_cost_usd=1.0)
    # Should have a chained action in trace
    chained = [t for t in result["reasoning_trace"] if "->" in str(t.get("action", ""))]
    assert len(chained) >= 1


# --- New tests: error recovery ---

def test_error_recovery_guidance():
    """When a tool errors, the conversation history includes recovery guidance."""
    call_count = [0]
    def recovery_call_model(model, messages, **kwargs):
        call_count[0] += 1
        # Check if there's error recovery guidance in messages
        has_error_guidance = any("DIFFERENT approach" in m.get("content", "") for m in messages if m.get("role") == "user")
        if has_error_guidance:
            return {"text": '{"thought": "switching approach", "answer": "recovered via different approach"}',
                    "model": "claude-haiku", "model_id": "test", "provider": "test",
                    "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}
        if call_count[0] == 1:
            return {"text": '{"thought": "try broken tool", "action": "broken_tool", "params": {}}',
                    "model": "claude-haiku", "model_id": "test", "provider": "test",
                    "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}
        return {"text": '{"thought": "done", "answer": "fallback answer"}',
                "model": "claude-haiku", "model_id": "test", "provider": "test",
                "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.001, "selected_reason": None}

    def error_handler(name, params):
        if name == "broken_tool":
            return {"error": "tool is broken"}
        return {"result": "ok"}

    agent = ReActAgent(call_model_fn=recovery_call_model, tool_handler_fn=error_handler)
    result = agent.run("Test error recovery", max_steps=5, max_cost_usd=1.0)
    assert result["steps_taken"] >= 2
    assert "answer" in result


# --- New tests: make_tool_handler with call_model_fn ---

def test_make_tool_handler_accepts_call_model_fn():
    """make_tool_handler should accept the new call_model_fn parameter."""
    from react_agent import make_tool_handler
    mock_call = lambda model, msgs, **kw: {"text": "result", "model": "claude-haiku", "cost_usd": 0.001}
    handler = make_tool_handler(
        {}, None, None, ":memory:", agent_id="",
        skills_search_engine=None, call_model_fn=mock_call,
    )
    # skill not found in :memory: db
    result = handler("execute_skill", {"skill": "nonexistent", "input": "test"})
    assert "error" in result


# --- New tests: extract_primary_result ---

def test_extract_primary_result():
    from react_agent import _extract_primary_result
    assert _extract_primary_result({"result": "hello"}) == "hello"
    assert _extract_primary_result({"text": "world"}) == "world"
    assert _extract_primary_result({"summary": "sum"}) == "sum"
    # Falls back to JSON
    result = _extract_primary_result({"custom_key": "val"})
    assert "custom_key" in result
