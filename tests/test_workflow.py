"""Tests for multi-step workflow engine."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from workflow_engine import validate_workflow


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
