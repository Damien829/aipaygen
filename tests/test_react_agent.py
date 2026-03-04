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
    content = messages[-1]["content"] if messages else ""
    if "Step" not in content and "Continue" not in content:
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
