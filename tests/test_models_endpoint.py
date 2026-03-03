import pytest
from model_router import list_models, resolve_model_name

def test_list_models_returns_all():
    models = list_models()
    assert len(models) >= 11
    names = [m["canonical_name"] for m in models]
    assert "claude-haiku" in names
    assert "gpt-4o" in names
    assert "deepseek-v3" in names

def test_resolve_default_is_haiku():
    assert resolve_model_name("default") == "claude-haiku"
