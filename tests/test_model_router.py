"""Tests for model_router — registry, aliases, config, cost calculation."""

import pytest
from model_router import (
    MODEL_REGISTRY,
    ModelNotFoundError,
    resolve_model_name,
    get_model_config,
    calculate_cost,
    list_models,
)

EXPECTED_MODELS = [
    "claude-haiku",
    "claude-sonnet",
    "claude-opus",
    "gpt-4o",
    "gpt-4o-mini",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "deepseek-v3",
    "deepseek-r1",
    "llama-3.3-70b",
    "mistral-large",
]


def test_registry_has_default_models():
    for name in EXPECTED_MODELS:
        assert name in MODEL_REGISTRY, f"{name} missing from MODEL_REGISTRY"
    assert len(MODEL_REGISTRY) >= 11


def test_resolve_aliases():
    assert resolve_model_name("haiku") == "claude-haiku"
    assert resolve_model_name("sonnet") == "claude-sonnet"
    assert resolve_model_name("opus") == "claude-opus"
    assert resolve_model_name("gpt4o") == "gpt-4o"
    assert resolve_model_name("gpt4o-mini") == "gpt-4o-mini"
    assert resolve_model_name("gemini") == "gemini-2.5-flash"
    assert resolve_model_name("gemini-pro") == "gemini-2.5-pro"
    assert resolve_model_name("deepseek") == "deepseek-v3"
    assert resolve_model_name("llama") == "llama-3.3-70b"
    assert resolve_model_name("mistral") == "mistral-large"
    assert resolve_model_name("default") == "claude-haiku"


def test_resolve_canonical_names():
    for name in EXPECTED_MODELS:
        assert resolve_model_name(name) == name


def test_resolve_unknown_raises():
    with pytest.raises(ModelNotFoundError):
        resolve_model_name("nonexistent-model-xyz")


def test_get_model_config():
    cfg = get_model_config("claude-haiku")
    required_fields = [
        "canonical_name",
        "provider",
        "model_id",
        "input_cost_per_m",
        "output_cost_per_m",
        "max_tokens",
        "vision",
        "streaming",
    ]
    for field in required_fields:
        assert field in cfg, f"{field} missing from config"
    assert cfg["provider"] == "anthropic"
    assert cfg["model_id"] == "claude-haiku-4-5-20251001"
    assert cfg["input_cost_per_m"] == 0.80
    assert cfg["output_cost_per_m"] == 4.00
    assert cfg["max_tokens"] == 8192
    assert cfg["vision"] is True
    assert cfg["streaming"] is True


def test_get_model_config_via_alias():
    cfg = get_model_config("haiku")
    assert cfg["canonical_name"] == "claude-haiku"


def test_calculate_cost():
    # Claude Haiku: input $0.80/M, output $4.00/M
    # 1000 input tokens = 1000/1_000_000 * 0.80 = 0.0008
    # 500 output tokens = 500/1_000_000 * 4.00 = 0.002
    # total = 0.0028
    cost = calculate_cost("claude-haiku", input_tokens=1000, output_tokens=500)
    assert abs(cost - 0.0028) < 1e-9


def test_calculate_cost_unknown_model():
    with pytest.raises(ModelNotFoundError):
        calculate_cost("nonexistent-model", input_tokens=100, output_tokens=100)


def test_list_models():
    models = list_models()
    assert isinstance(models, list)
    assert len(models) >= 11
    names = [m["canonical_name"] for m in models]
    for expected in EXPECTED_MODELS:
        assert expected in names
