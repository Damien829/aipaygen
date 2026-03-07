"""Tests for model router feedback loop and ReAct synthesis improvements."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model_router import record_outcome, get_outcome_adjustment, get_all_outcomes, _outcome_stats


def setup_function():
    """Clear outcome stats before each test."""
    _outcome_stats.clear()


def test_record_outcome_basic():
    record_outcome("claude-haiku", "code", 0.8)
    assert "claude-haiku" in _outcome_stats
    assert "code" in _outcome_stats["claude-haiku"]
    assert list(_outcome_stats["claude-haiku"]["code"]) == [0.8]


def test_record_outcome_clamps():
    record_outcome("test-model", "general", -0.5)
    record_outcome("test-model", "general", 1.5)
    scores = list(_outcome_stats["test-model"]["general"])
    assert scores == [0.0, 1.0]


def test_get_outcome_adjustment_no_data():
    assert get_outcome_adjustment("nonexistent", "general") == 0.0


def test_get_outcome_adjustment_insufficient_data():
    record_outcome("test-model", "code", 0.9)
    record_outcome("test-model", "code", 0.8)
    # Only 2 samples, need 3 minimum
    assert get_outcome_adjustment("test-model", "code") == 0.0


def test_get_outcome_adjustment_positive():
    for _ in range(5):
        record_outcome("good-model", "code", 0.9)
    adj = get_outcome_adjustment("good-model", "code")
    assert adj > 0, "High-quality model should get positive adjustment"
    assert adj <= 0.1, "Adjustment should be capped at 0.1"


def test_get_outcome_adjustment_negative():
    for _ in range(5):
        record_outcome("bad-model", "code", 0.1)
    adj = get_outcome_adjustment("bad-model", "code")
    assert adj < 0, "Low-quality model should get negative adjustment"
    assert adj >= -0.1, "Adjustment should be floored at -0.1"


def test_get_outcome_adjustment_neutral():
    for _ in range(5):
        record_outcome("neutral-model", "code", 0.5)
    adj = get_outcome_adjustment("neutral-model", "code")
    assert abs(adj) < 0.01, "Neutral outcomes should give ~0 adjustment"


def test_get_all_outcomes():
    record_outcome("m1", "code", 0.8)
    record_outcome("m1", "code", 0.7)
    record_outcome("m1", "research", 0.9)
    stats = get_all_outcomes()
    assert "m1" in stats
    assert "code" in stats["m1"]
    assert stats["m1"]["code"]["count"] == 2
    assert 0.7 <= stats["m1"]["code"]["avg"] <= 0.8


def test_rolling_window():
    """Outcome stats should use a rolling window of 20."""
    for i in range(25):
        record_outcome("window-model", "code", 0.5)
    assert len(_outcome_stats["window-model"]["code"]) == 20


# Test synthesis fallback
from react_agent import _synthesize_answer


def test_synthesize_no_observations():
    result = _synthesize_answer([], "test task")
    assert "unable to complete" in result.lower()


def test_synthesize_naive_fallback():
    """Without call_model_fn, should use naive concatenation."""
    obs = [
        {"step": 1, "action": "research", "result": "Found info about topic X"},
        {"step": 2, "action": "summarize", "result": {"result": "Summary of X"}},
    ]
    result = _synthesize_answer(obs, "research X")
    assert "2 steps" in result
    assert "Found info" in result


def test_synthesize_with_model():
    """With call_model_fn, should use LLM synthesis."""
    def mock_call_model(model, messages, **kwargs):
        return {"text": "Synthesized answer about X based on research findings."}

    obs = [
        {"step": 1, "action": "research", "result": "Found info about topic X"},
    ]
    result = _synthesize_answer(obs, "research X", call_model_fn=mock_call_model)
    assert "Synthesized answer" in result


def test_synthesize_model_failure_fallback():
    """If model call fails, should fall back to naive concat."""
    def failing_model(model, messages, **kwargs):
        raise Exception("API error")

    obs = [
        {"step": 1, "action": "research", "result": "Found info"},
    ]
    result = _synthesize_answer(obs, "task", call_model_fn=failing_model)
    assert "1 steps" in result  # naive fallback
