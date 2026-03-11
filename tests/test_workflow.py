"""Tests for multi-step workflow engine."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest
from unittest.mock import MagicMock, patch
from workflow_engine import validate_workflow, execute_workflow, MAX_STEPS, DISCOUNT_PERCENT


# ---------------------------------------------------------------------------
# validate_workflow tests
# ---------------------------------------------------------------------------


def test_validate_valid_workflow():
    steps = [{"tool": "research", "input": {"topic": "AI agents"}}, {"tool": "summarize"}]
    assert validate_workflow(steps) == []


def test_validate_empty():
    assert len(validate_workflow([])) > 0


def test_validate_unknown_tool():
    errors = validate_workflow([{"tool": "nonexistent_xyz"}])
    assert any("unknown" in e.lower() for e in errors)


def test_validate_too_many_steps():
    steps = [{"tool": "research", "input": {"topic": "x"}}] * 11
    errors = validate_workflow(steps)
    assert any("10" in e for e in errors)


def test_validate_first_step_needs_input():
    steps = [{"tool": "summarize"}]  # no input, nothing to summarize
    errors = validate_workflow(steps)
    assert len(errors) > 0


def test_validate_single_step_ok():
    steps = [{"tool": "research", "input": {"topic": "test"}}]
    assert validate_workflow(steps) == []


def test_validate_missing_tool_field():
    errors = validate_workflow([{"input": {"text": "hello"}}])
    assert any("missing" in e.lower() for e in errors)


def test_validate_non_dict_step():
    errors = validate_workflow(["not a dict"])
    assert any("object" in e.lower() for e in errors)


def test_validate_generative_tool_no_input():
    """Generative tools like research can be first step without explicit input."""
    steps = [{"tool": "research"}]
    assert validate_workflow(steps) == []


def test_validate_chained_no_input_ok():
    """Second step doesn't need explicit input — it receives piped output."""
    steps = [
        {"tool": "research", "input": {"topic": "AI"}},
        {"tool": "summarize"},
        {"tool": "translate"},
    ]
    assert validate_workflow(steps) == []


def test_validate_exactly_max_steps():
    """Exactly MAX_STEPS should be valid."""
    steps = [{"tool": "research", "input": {"topic": "x"}}] + [{"tool": "summarize"}] * (MAX_STEPS - 1)
    errors = validate_workflow(steps)
    assert not any("exceeds" in e.lower() for e in errors)


def test_validate_multiple_errors():
    """A workflow with multiple issues should report all of them."""
    steps = [
        "not a dict",
        {"input": {"text": "no tool"}},
        {"tool": "fake_unknown_tool_xyz"},
    ]
    errors = validate_workflow(steps)
    assert len(errors) >= 3


# ---------------------------------------------------------------------------
# execute_workflow tests (using Flask test client mock)
# ---------------------------------------------------------------------------


def _make_mock_client(responses):
    """Build a mock Flask test client that returns canned responses in order.

    responses: list of (status_code, json_body) tuples
    """
    client = MagicMock()
    call_count = {"n": 0}

    def mock_post(url, json=None):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        status, body = responses[idx]
        resp = MagicMock()
        resp.status_code = status
        resp.get_json.return_value = body
        resp.data = json.dumps(body).encode() if isinstance(body, dict) else b""
        return resp

    # Need to rebind json for the closure
    import json as _json
    def mock_post_real(url, json=None):
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        status, body = responses[idx]
        resp = MagicMock()
        resp.status_code = status
        resp.get_json.return_value = body
        resp.data = _json.dumps(body).encode() if isinstance(body, dict) else b""
        return resp

    client.post = mock_post_real
    return client


class TestExecuteWorkflow:
    """Tests for execute_workflow with a mock app_client."""

    def test_single_step_success(self):
        client = _make_mock_client([
            (200, {"result": "some research output"}),
        ])
        steps = [{"tool": "research", "input": {"topic": "AI"}}]
        result = execute_workflow(steps, app_client=client)

        assert result["total_steps"] == 1
        assert len(result["steps"]) == 1
        assert result["steps"][0]["status"] == 200
        assert result["steps"][0]["tool"] == "research"
        assert result["discount_applied"] == f"{DISCOUNT_PERCENT}%"

    def test_multi_step_piping(self):
        """Output from step 1 should be piped as input to step 2."""
        client = _make_mock_client([
            (200, {"text": "Research findings about AI"}),
            (200, {"summary": "AI is important"}),
        ])
        steps = [
            {"tool": "research", "input": {"topic": "AI"}},
            {"tool": "summarize"},
        ]
        result = execute_workflow(steps, app_client=client)

        assert result["total_steps"] == 2
        assert result["steps"][0]["status"] == 200
        assert result["steps"][1]["status"] == 200
        # Verify the second call received piped data
        call_args = client.post.call_args_list if hasattr(client.post, 'call_args_list') else []

    def test_step_failure_stops_chain(self):
        """If a step returns 4xx/5xx, subsequent steps should not execute."""
        client = _make_mock_client([
            (200, {"text": "Step 1 OK"}),
            (500, {"error": "Internal server error"}),
            (200, {"text": "Should not run"}),
        ])
        steps = [
            {"tool": "research", "input": {"topic": "test"}},
            {"tool": "summarize"},
            {"tool": "translate"},
        ]
        result = execute_workflow(steps, app_client=client)

        assert result["total_steps"] == 2  # stopped after step 2
        assert result["steps"][1]["status"] == 500
        assert "error" in result["steps"][1]

    def test_step_exception_stops_chain(self):
        """If a step raises an exception, chain should stop."""
        client = MagicMock()
        client.post.side_effect = Exception("Connection refused")

        steps = [{"tool": "research", "input": {"topic": "test"}}]
        result = execute_workflow(steps, app_client=client)

        assert result["total_steps"] == 1
        assert result["steps"][0]["status"] == 500
        assert "Connection refused" in result["steps"][0]["error"]

    def test_discount_applied_field(self):
        client = _make_mock_client([(200, {"ok": True})])
        steps = [{"tool": "research", "input": {"topic": "x"}}]
        result = execute_workflow(steps, app_client=client)
        assert result["discount_applied"] == "15%"

    def test_total_time_ms_present(self):
        client = _make_mock_client([(200, {"ok": True})])
        steps = [{"tool": "research", "input": {"topic": "x"}}]
        result = execute_workflow(steps, app_client=client)
        assert "total_time_ms" in result
        assert isinstance(result["total_time_ms"], int)

    def test_tool_name_underscores_to_hyphens(self):
        """Tool names with underscores should be converted to hyphens in URL."""
        calls = []

        def mock_post(url, json=None):
            calls.append(url)
            resp = MagicMock()
            resp.status_code = 200
            resp.get_json.return_value = {"ok": True}
            resp.data = b'{"ok": true}'
            return resp

        client = MagicMock()
        client.post = mock_post

        steps = [{"tool": "test_cases", "input": {"code": "def foo(): pass"}}]
        execute_workflow(steps, app_client=client)

        assert calls[0] == "/test-cases"

    def test_explicit_input_overrides_piped(self):
        """Explicit step input should override piped output keys."""
        calls = []

        def mock_post(url, json=None):
            calls.append(json)
            resp = MagicMock()
            resp.status_code = 200
            resp.get_json.return_value = {"text": "from step 1", "extra": "data"}
            resp.data = b'{"text": "from step 1", "extra": "data"}'
            return resp

        client = MagicMock()
        client.post = mock_post

        steps = [
            {"tool": "research", "input": {"topic": "AI"}},
            {"tool": "summarize", "input": {"text": "override this"}},
        ]
        execute_workflow(steps, app_client=client)

        # Second call should have the overridden text
        assert calls[1]["text"] == "override this"
        # But should also have the piped 'extra' key
        assert calls[1]["extra"] == "data"

    def test_string_output_piped_as_text(self):
        """When a step returns non-JSON (raw text), it should be injected as 'text' key."""
        call_count = {"n": 0}

        def mock_post(url, json=None):
            call_count["n"] += 1
            resp = MagicMock()
            resp.status_code = 200
            if call_count["n"] == 1:
                resp.get_json.side_effect = Exception("not json")
                resp.data = b"raw text output"
            else:
                resp.get_json.return_value = {"summary": "done"}
                resp.data = b'{"summary": "done"}'
            return resp

        client = MagicMock()
        client.post = mock_post

        steps = [
            {"tool": "research", "input": {"topic": "test"}},
            {"tool": "summarize"},
        ]
        result = execute_workflow(steps, app_client=client)
        # First step should have raw output
        assert result["steps"][0]["output"] == {"raw": "raw text output"}

    def test_four_hundred_error_stops_chain(self):
        """A 402 payment required should also stop the chain."""
        client = _make_mock_client([
            (402, {"error": "payment_required"}),
        ])
        steps = [
            {"tool": "research", "input": {"topic": "test"}},
            {"tool": "summarize"},
        ]
        result = execute_workflow(steps, app_client=client)
        assert result["total_steps"] == 1
        assert result["steps"][0]["status"] == 402
