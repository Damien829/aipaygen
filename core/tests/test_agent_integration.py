"""Integration test: full ReAct agent flow with mocked model calls."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from react_agent import ReActAgent, make_tool_handler

_call_sequence = []

def _sequenced_call_model(model, messages, **kwargs):
    _call_sequence.append(model)
    step = len(_call_sequence)
    if step == 1:
        return {
            "text": '{"thought": "I should research AI agents first", "action": "research", "params": {"topic": "AI agents comparison"}}',
            "model": "claude-haiku", "model_id": "test", "provider": "test",
            "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.002,
            "selected_reason": "complexity=2/5",
        }
    else:
        return {
            "text": '{"thought": "I have enough information to answer", "answer": "The top AI agent frameworks are CrewAI, LangGraph, and AutoGen. CrewAI focuses on role-based agents, LangGraph on graph-based workflows, and AutoGen on multi-agent conversations."}',
            "model": "claude-sonnet", "model_id": "test", "provider": "test",
            "input_tokens": 500, "output_tokens": 200, "cost_usd": 0.01,
            "selected_reason": "complexity=3/5",
        }

def test_full_agent_flow():
    _call_sequence.clear()
    batch_handlers = {
        "research": lambda d: {"summary": "CrewAI, LangGraph, and AutoGen are top frameworks", "key_points": ["role-based", "graph-based", "multi-agent"]},
    }
    handler = make_tool_handler(batch_handlers, None, None, ":memory:")
    agent = ReActAgent(call_model_fn=_sequenced_call_model, tool_handler_fn=handler)
    result = agent.run("Compare the top AI agent frameworks", max_steps=5, max_cost_usd=1.0)
    assert result["stop_reason"] == "completed"
    assert "CrewAI" in result["answer"]
    assert result["steps_taken"] == 2
    assert result["total_cost_usd"] > 0
    assert len(result["reasoning_trace"]) == 2
    assert result["reasoning_trace"][0]["action"] == "research"
    assert result["reasoning_trace"][1]["action"] == "final_answer"

def test_agent_stream_flow():
    _call_sequence.clear()
    batch_handlers = {
        "research": lambda d: {"summary": "Test result"},
    }
    handler = make_tool_handler(batch_handlers, None, None, ":memory:")
    agent = ReActAgent(call_model_fn=_sequenced_call_model, tool_handler_fn=handler)
    events = list(agent.run_stream("Compare frameworks", max_steps=5, max_cost_usd=1.0))
    event_types = [e["event"] for e in events]
    assert "thought" in event_types
    assert "answer" in event_types
    assert "done" in event_types
    done_event = [e for e in events if e["event"] == "done"][0]
    assert done_event["data"]["reason"] == "completed"
