import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from model_router import CostTracker

def test_cost_tracker_basic():
    ct = CostTracker()
    assert ct.total == 0.0
    ct.add(0.01)
    ct.add(0.02)
    assert abs(ct.total - 0.03) < 1e-9

def test_cost_tracker_can_afford():
    ct = CostTracker()
    ct.add(0.90)
    assert ct.can_afford(0.05, budget=1.00) is True
    assert ct.can_afford(0.15, budget=1.00) is False

def test_cost_tracker_remaining():
    ct = CostTracker()
    ct.add(0.25)
    assert abs(ct.remaining(1.00) - 0.75) < 1e-9

def test_cost_tracker_no_budget():
    ct = CostTracker()
    ct.add(5.00)
    assert ct.can_afford(1.00, budget=None) is True
    assert ct.remaining(None) == float("inf")


from model_router import auto_select_model, _classify_task, MODEL_REGISTRY

def test_classify_task_returns_valid_structure():
    result = _classify_task("What is 2+2?")
    assert "complexity" in result
    assert result["complexity"] in (1, 2, 3, 4, 5)
    assert "needs_vision" in result
    assert "needs_reasoning" in result

def test_classify_simple_task():
    result = _classify_task("Summarize this text")
    assert result["complexity"] <= 2

def test_classify_complex_task():
    result = _classify_task("Write a recursive algorithm to solve the traveling salesman problem with dynamic programming and prove its time complexity")
    assert result["complexity"] >= 3

def test_auto_select_simple():
    model = auto_select_model("Say hello")
    cfg = MODEL_REGISTRY[model["model"]]
    assert cfg["latency_tier"] == "fast"  # simple task should get fast model

def test_auto_select_complex():
    model = auto_select_model("Prove the Riemann hypothesis and explain your reasoning step by step")
    cfg = MODEL_REGISTRY[model["model"]]
    assert "reasoning" in cfg.get("strengths", []) or cfg["latency_tier"] in ("slow", "medium")

def test_auto_select_with_budget():
    model = auto_select_model("Complex analysis task", max_cost_usd=0.002)
    # Budget-constrained: should pick a cheap model
    cfg = MODEL_REGISTRY[model["model"]]
    assert cfg["input_cost_per_m"] < 5.0

def test_resolve_model_auto():
    from model_router import resolve_model_name
    result = resolve_model_name("auto")
    assert result == "auto"

def test_auto_select_vision():
    model = auto_select_model("Describe this image in detail", needs_vision=True)
    cfg = MODEL_REGISTRY[model["model"]]
    assert cfg["vision"] is True

def test_auto_select_returns_top3_in_reason():
    result = auto_select_model("Write a Python function to sort a list")
    assert "top3=" in result["reason"]

def test_auto_select_code_domain():
    result = auto_select_model("Debug this Python function and fix the recursive algorithm")
    assert result["classification"]["domain"] == "code"


# --- New model registry tests ---

def test_new_models_in_registry():
    assert "grok-3" in MODEL_REGISTRY
    assert "grok-3-mini" in MODEL_REGISTRY
    assert "mistral-large-direct" in MODEL_REGISTRY
    assert "mistral-small" in MODEL_REGISTRY

def test_latency_tier_on_all_models():
    for name, cfg in MODEL_REGISTRY.items():
        assert "latency_tier" in cfg, f"{name} missing latency_tier"
        assert cfg["latency_tier"] in ("fast", "medium", "slow"), f"{name} has invalid latency_tier"

def test_strengths_on_all_models():
    for name, cfg in MODEL_REGISTRY.items():
        assert "strengths" in cfg, f"{name} missing strengths"
        assert isinstance(cfg["strengths"], list), f"{name} strengths should be a list"
        assert len(cfg["strengths"]) > 0, f"{name} should have at least one strength"

def test_model_count():
    assert len(MODEL_REGISTRY) == 15  # 11 original + 4 new

def test_new_aliases():
    from model_router import resolve_model_name
    assert resolve_model_name("grok") == "grok-3"
    assert resolve_model_name("grok-mini") == "grok-3-mini"
    assert resolve_model_name("mistral-direct") == "mistral-large-direct"

def test_new_providers_in_fallback():
    from model_router import _FALLBACK_CHAINS, _PROVIDER_DEFAULT
    assert "xai" in _FALLBACK_CHAINS
    assert "mistral" in _FALLBACK_CHAINS
    assert "xai" in _PROVIDER_DEFAULT
    assert "mistral" in _PROVIDER_DEFAULT


# --- Performance tracking tests ---

def test_perf_tracking():
    from model_router import _record_perf, get_model_perf, _perf_stats
    # Use a unique model name to avoid cross-test pollution
    test_model = "_test_perf_model"
    _perf_stats.pop(test_model, None)

    _record_perf(test_model, 150.0, True)
    _record_perf(test_model, 200.0, True)
    _record_perf(test_model, 5000.0, False)
    perf = get_model_perf(test_model)
    assert perf["calls"] == 3
    assert perf["error_rate"] > 0
    assert perf["p50_ms"] is not None
    assert perf["p90_ms"] is not None

    # Cleanup
    _perf_stats.pop(test_model, None)

def test_perf_no_data():
    from model_router import get_model_perf
    perf = get_model_perf("_nonexistent_model")
    assert perf["calls"] == 0
    assert perf["p50_ms"] is None

def test_get_all_perf():
    from model_router import get_all_perf, _record_perf, _perf_stats
    test_model = "_test_all_perf"
    _perf_stats.pop(test_model, None)
    _record_perf(test_model, 100.0, True)
    result = get_all_perf()
    assert isinstance(result, dict)
    assert test_model in result
    _perf_stats.pop(test_model, None)


# --- Response cache tests ---

def test_cache_hit():
    from model_router import _response_cache, _cache_key, _CACHE_TTL
    _response_cache.clear()
    key = _cache_key("claude-haiku", [{"role": "user", "content": "hello"}], "system", 0.7)
    assert isinstance(key, str)
    assert len(key) == 64  # sha256 hex digest


def test_cache_key_deterministic():
    from model_router import _cache_key
    k1 = _cache_key("claude-haiku", [{"role": "user", "content": "test"}], "", 0.7)
    k2 = _cache_key("claude-haiku", [{"role": "user", "content": "test"}], "", 0.7)
    assert k1 == k2


def test_cache_key_differs_on_input():
    from model_router import _cache_key
    k1 = _cache_key("claude-haiku", [{"role": "user", "content": "hello"}], "", 0.7)
    k2 = _cache_key("claude-haiku", [{"role": "user", "content": "world"}], "", 0.7)
    assert k1 != k2


def test_cache_key_differs_on_model():
    from model_router import _cache_key
    k1 = _cache_key("claude-haiku", [{"role": "user", "content": "test"}], "", 0.7)
    k2 = _cache_key("gpt-4o-mini", [{"role": "user", "content": "test"}], "", 0.7)
    assert k1 != k2


def test_cache_key_differs_on_temperature():
    from model_router import _cache_key
    k1 = _cache_key("claude-haiku", [{"role": "user", "content": "test"}], "", 0.7)
    k2 = _cache_key("claude-haiku", [{"role": "user", "content": "test"}], "", 0.0)
    assert k1 != k2


def test_cache_store_and_retrieve():
    from model_router import _response_cache, _cache_key, _cache_store, _cache_get
    _response_cache.clear()
    key = _cache_key("test-model", [{"role": "user", "content": "cached"}], "", 0.7)
    response = {"text": "cached response", "input_tokens": 10, "output_tokens": 20}
    _cache_store(key, response)
    hit = _cache_get(key)
    assert hit is not None
    assert hit["text"] == "cached response"


def test_cache_miss():
    from model_router import _response_cache, _cache_get
    _response_cache.clear()
    assert _cache_get("nonexistent-key") is None


def test_cache_eviction():
    from model_router import _response_cache, _cache_store, _cache_get, _CACHE_MAX_ENTRIES
    _response_cache.clear()
    for i in range(_CACHE_MAX_ENTRIES + 10):
        _cache_store(f"key-{i}", {"text": f"val-{i}", "input_tokens": 0, "output_tokens": 0})
    assert len(_response_cache) <= _CACHE_MAX_ENTRIES
    assert _cache_get("key-0") is None


def test_clear_cache():
    from model_router import _response_cache, _cache_store, clear_cache
    _cache_store("k", {"text": "v", "input_tokens": 0, "output_tokens": 0})
    assert len(_response_cache) > 0
    clear_cache()
    assert len(_response_cache) == 0


# --- Domain system prompt tests ---

def test_domain_prompts_exist():
    from model_router import _DOMAIN_SYSTEM_PROMPTS
    assert "code" in _DOMAIN_SYSTEM_PROMPTS
    assert "research" in _DOMAIN_SYSTEM_PROMPTS
    assert "creative" in _DOMAIN_SYSTEM_PROMPTS
    assert "data" in _DOMAIN_SYSTEM_PROMPTS
    assert "general" in _DOMAIN_SYSTEM_PROMPTS


def test_domain_prompts_are_strings():
    from model_router import _DOMAIN_SYSTEM_PROMPTS
    for domain, prompt in _DOMAIN_SYSTEM_PROMPTS.items():
        assert isinstance(prompt, str), f"{domain} prompt should be a string"
        assert len(prompt) > 10, f"{domain} prompt should be non-trivial"


def test_get_domain_prompt():
    from model_router import _get_domain_prompt
    assert "code" in _get_domain_prompt("code").lower() or "coding" in _get_domain_prompt("code").lower()
    assert _get_domain_prompt("nonexistent") == _get_domain_prompt("general")


# --- Streaming tests ---

def test_stream_openai_compatible_function_exists():
    from model_router import _stream_openai_compatible
    assert callable(_stream_openai_compatible)


def test_all_providers_have_streaming():
    from model_router import MODEL_REGISTRY
    providers_with_streaming = {"anthropic", "openai", "deepseek", "together", "xai", "mistral", "google"}
    for name, cfg in MODEL_REGISTRY.items():
        assert cfg["provider"] in providers_with_streaming, f"{name} provider {cfg['provider']} has no streaming"


# --- Retry / rate limit tests ---

def test_rate_limit_error_class():
    from model_router import RateLimitError
    e = RateLimitError("rate limited", retry_after=2.0)
    assert e.retry_after == 2.0
    assert "rate limited" in str(e)


def test_rate_limit_error_no_retry_after():
    from model_router import RateLimitError
    e = RateLimitError("rate limited")
    assert e.retry_after is None


def test_retry_config_exists():
    from model_router import _RETRY_MAX_ATTEMPTS, _RETRY_BASE_DELAY
    assert _RETRY_MAX_ATTEMPTS == 2
    assert _RETRY_BASE_DELAY == 1.0
