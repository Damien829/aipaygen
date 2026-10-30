"""Requests to current Claude models: no sampling params, per-model defaults, text from any block."""
from types import SimpleNamespace as NS

import pytest

import model_router as mr


def test_current_models_drop_sampling_and_get_defaults():
    k = mr.prepare_claude_request({"model": mr.CLAUDE_HAIKU, "temperature": 0.7, "top_p": 0.9, "max_tokens": 10})
    assert k == {"model": mr.CLAUDE_HAIKU, "max_tokens": 10, "thinking": {"type": "disabled"}}
    for model in (mr.CLAUDE_SONNET, mr.CLAUDE_OPUS):
        k = mr.prepare_claude_request({"model": model, "temperature": 0.2})
        assert "temperature" not in k and k["output_config"] == {"effort": "low"}


def test_caller_settings_win_and_defaults_are_not_shared():
    k = mr.prepare_claude_request({"model": mr.CLAUDE_OPUS, "output_config": {"effort": "high"}})
    assert k["output_config"] == {"effort": "high"}
    a = mr.prepare_claude_request({"model": mr.CLAUDE_SONNET})
    a["output_config"]["effort"] = "max"
    assert mr.prepare_claude_request({"model": mr.CLAUDE_SONNET})["output_config"] == {"effort": "low"}


def test_unknown_models_are_left_alone():
    k = {"model": "some-other-model", "temperature": 0.3}
    assert mr.prepare_claude_request(dict(k)) == k


def test_response_text_skips_thinking_blocks():
    msg = NS(stop_reason="end_turn", content=[NS(type="thinking", thinking=""), NS(type="text", text="hi "), NS(type="text", text="there")])
    assert mr.response_text(msg) == "hi there"


def test_response_text_raises_on_refusal():
    msg = NS(stop_reason="refusal", stop_details=NS(category="cyber"), content=[])
    with pytest.raises(mr.ClaudeRefusal):
        mr.response_text(msg)


def test_registry_uses_current_claude_ids():
    ids = {c["model_id"] for c in mr.MODEL_REGISTRY.values() if c["provider"] == "anthropic"}
    assert ids <= {mr.CLAUDE_HAIKU, mr.CLAUDE_SONNET, mr.CLAUDE_OPUS}
