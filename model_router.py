"""Multi-model router — registry, resolution, cost calculation, unified call_model.

Includes circuit breaker per provider: breaks after 3 consecutive failures for 5 min.
Fallback chains: anthropic↔openai, deepseek↔together, google→anthropic, xai→openai, mistral→together.
"""

import collections as _collections
import hashlib as _hashlib
import json as _json
import logging
import os
import time as _time
import httpx

_log = logging.getLogger("model_router")


def _mask_key(key: str) -> str:
    """Mask API key for safe logging: show first 4 and last 4 chars only."""
    if not key or len(key) < 12:
        return "***"
    return f"{key[:4]}...{key[-4:]}"

# ---------------------------------------------------------------------------
# Response cache — hash-based, TTL, LRU eviction
# ---------------------------------------------------------------------------

_CACHE_TTL = 300  # 5 minutes
_CACHE_MAX_ENTRIES = 500

# {key: {"response": dict, "cached_at": float}}
_response_cache: dict[str, dict] = {}


def _cache_key(model: str, messages: list[dict], system: str, temperature: float) -> str:
    """Generate deterministic cache key from call parameters."""
    payload = _json.dumps({"m": model, "msgs": messages, "s": system, "t": temperature}, sort_keys=True)
    return _hashlib.sha256(payload.encode()).hexdigest()


def _cache_get(key: str) -> dict | None:
    """Return cached response or None if miss/expired."""
    entry = _response_cache.get(key)
    if entry is None:
        return None
    if (_time.time() - entry["cached_at"]) > _CACHE_TTL:
        _response_cache.pop(key, None)
        return None
    return entry["response"]


def _cache_store(key: str, response: dict):
    """Store response in cache with LRU eviction."""
    while len(_response_cache) >= _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_response_cache))
        del _response_cache[oldest_key]
    _response_cache[key] = {"response": response, "cached_at": _time.time()}


def clear_cache():
    """Clear the entire response cache."""
    _response_cache.clear()


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODEL_REGISTRY = {
    "claude-haiku": {
        "canonical_name": "claude-haiku",
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "input_cost_per_m": 0.80,
        "output_cost_per_m": 4.00,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["general", "code", "creative"],
    },
    "claude-sonnet": {
        "canonical_name": "claude-sonnet",
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6-20260320",
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["reasoning", "code", "creative", "general"],
    },
    "claude-opus": {
        "canonical_name": "claude-opus",
        "provider": "anthropic",
        "model_id": "claude-opus-4-6-20260320",
        "input_cost_per_m": 15.00,
        "output_cost_per_m": 75.00,
        "max_tokens": 4096,
        "vision": True,
        "streaming": True,
        "latency_tier": "slow",
        "strengths": ["reasoning", "creative"],
    },
    "gpt-4o": {
        "canonical_name": "gpt-4o",
        "provider": "openai",
        "model_id": "gpt-4o",
        "input_cost_per_m": 2.50,
        "output_cost_per_m": 10.00,
        "max_tokens": 4096,
        "vision": True,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["general", "code", "creative", "reasoning"],
    },
    "gpt-4o-mini": {
        "canonical_name": "gpt-4o-mini",
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "input_cost_per_m": 0.15,
        "output_cost_per_m": 0.60,
        "max_tokens": 4096,
        "vision": True,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["general", "code"],
    },
    "gemini-2.5-pro": {
        "canonical_name": "gemini-2.5-pro",
        "provider": "google",
        "model_id": "gemini-2.5-pro-preview-03-25",
        "input_cost_per_m": 1.25,
        "output_cost_per_m": 10.00,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["reasoning", "code", "general"],
    },
    "gemini-2.5-flash": {
        "canonical_name": "gemini-2.5-flash",
        "provider": "google",
        "model_id": "gemini-2.5-flash-preview-04-17",
        "input_cost_per_m": 0.15,
        "output_cost_per_m": 0.60,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["general", "code"],
    },
    "deepseek-v3": {
        "canonical_name": "deepseek-v3",
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "input_cost_per_m": 0.27,
        "output_cost_per_m": 1.10,
        "max_tokens": 4096,
        "vision": False,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["code", "general"],
    },
    "deepseek-r1": {
        "canonical_name": "deepseek-r1",
        "provider": "deepseek",
        "model_id": "deepseek-reasoner",
        "input_cost_per_m": 0.55,
        "output_cost_per_m": 2.19,
        "max_tokens": 4096,
        "vision": False,
        "streaming": True,
        "latency_tier": "slow",
        "strengths": ["reasoning", "code"],
    },
    "llama-3.3-70b": {
        "canonical_name": "llama-3.3-70b",
        "provider": "together",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "input_cost_per_m": 0.88,
        "output_cost_per_m": 0.88,
        "max_tokens": 4096,
        "vision": False,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["general", "code"],
    },
    "mistral-large": {
        "canonical_name": "mistral-large",
        "provider": "together",
        "model_id": "mistralai/Mistral-Large-Instruct-2407",
        "input_cost_per_m": 1.00,
        "output_cost_per_m": 1.00,
        "max_tokens": 4096,
        "vision": False,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["code", "general"],
    },
    "grok-3": {
        "canonical_name": "grok-3",
        "provider": "xai",
        "model_id": "grok-3",
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["general", "reasoning", "creative"],
    },
    "grok-3-mini": {
        "canonical_name": "grok-3-mini",
        "provider": "xai",
        "model_id": "grok-3-mini",
        "input_cost_per_m": 0.30,
        "output_cost_per_m": 0.50,
        "max_tokens": 8192,
        "vision": True,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["general", "code"],
    },
    "mistral-large-direct": {
        "canonical_name": "mistral-large-direct",
        "provider": "mistral",
        "model_id": "mistral-large-latest",
        "input_cost_per_m": 2.00,
        "output_cost_per_m": 6.00,
        "max_tokens": 8192,
        "vision": False,
        "streaming": True,
        "latency_tier": "medium",
        "strengths": ["code", "reasoning", "general"],
    },
    "mistral-small": {
        "canonical_name": "mistral-small",
        "provider": "mistral",
        "model_id": "mistral-small-latest",
        "input_cost_per_m": 0.10,
        "output_cost_per_m": 0.30,
        "max_tokens": 8192,
        "vision": False,
        "streaming": True,
        "latency_tier": "fast",
        "strengths": ["general", "code"],
    },
}

_ALIASES = {
    "haiku": "claude-haiku",
    "sonnet": "claude-sonnet",
    "opus": "claude-opus",
    "gpt4o": "gpt-4o",
    "gpt4o-mini": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
    "gemini-pro": "gemini-2.5-pro",
    "deepseek": "deepseek-v3",
    "llama": "llama-3.3-70b",
    "mistral": "mistral-large",
    "grok": "grok-3",
    "grok-mini": "grok-3-mini",
    "mistral-direct": "mistral-large-direct",
    "default": "claude-haiku",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ModelNotFoundError(Exception):
    """Raised when a model name cannot be resolved."""

# ---------------------------------------------------------------------------
# Circuit breaker — per-provider failure tracking
# ---------------------------------------------------------------------------

_CIRCUIT_MAX_FAILURES = 3
_CIRCUIT_RESET_SECONDS = 300  # 5 minutes

# {provider: {"failures": int, "opened_at": float|None}}
_circuit_state: dict[str, dict] = {}

_FALLBACK_CHAINS: dict[str, str] = {
    "anthropic": "openai",
    "openai": "anthropic",
    "deepseek": "together",
    "together": "deepseek",
    "google": "anthropic",
    "xai": "openai",
    "mistral": "together",
}

# Map provider to a cheap default model for fallback
_PROVIDER_DEFAULT: dict[str, str] = {
    "anthropic": "claude-haiku",
    "openai": "gpt-4o-mini",
    "google": "gemini-2.5-flash",
    "deepseek": "deepseek-v3",
    "together": "llama-3.3-70b",
    "xai": "grok-3-mini",
    "mistral": "mistral-small",
}


def _check_circuit(provider: str) -> bool:
    """Returns True if provider is available (circuit closed or half-open)."""
    state = _circuit_state.get(provider)
    if not state or state["failures"] < _CIRCUIT_MAX_FAILURES:
        return True
    # Circuit is open — check if reset period has elapsed
    if state.get("opened_at") and (_time.time() - state["opened_at"]) >= _CIRCUIT_RESET_SECONDS:
        # Half-open: allow one attempt
        state["failures"] = 0
        state["opened_at"] = None
        return True
    return False


def _record_failure(provider: str):
    """Record a provider failure. Opens circuit after threshold."""
    state = _circuit_state.setdefault(provider, {"failures": 0, "opened_at": None})
    state["failures"] += 1
    if state["failures"] >= _CIRCUIT_MAX_FAILURES and state["opened_at"] is None:
        state["opened_at"] = _time.time()


def _record_success(provider: str):
    """Reset failure count on success."""
    if provider in _circuit_state:
        _circuit_state[provider] = {"failures": 0, "opened_at": None}


def _get_fallback_model(original_model: str) -> str | None:
    """Find a fallback model from a different provider."""
    cfg = MODEL_REGISTRY.get(original_model)
    if not cfg:
        return None
    provider = cfg["provider"]
    fallback_provider = _FALLBACK_CHAINS.get(provider)
    if fallback_provider and _check_circuit(fallback_provider):
        return _PROVIDER_DEFAULT.get(fallback_provider)
    return None


# ---------------------------------------------------------------------------
# Runtime performance tracking — latency + error rates per model
# ---------------------------------------------------------------------------

_PERF_WINDOW = 50  # track last N calls per model

# {model_name: {"latencies": deque(maxlen=50), "errors": int, "successes": int}}
_perf_stats: dict[str, dict] = {}


def _record_perf(model_name: str, latency_ms: float, success: bool):
    """Record a call's performance metrics."""
    if model_name not in _perf_stats:
        _perf_stats[model_name] = {
            "latencies": _collections.deque(maxlen=_PERF_WINDOW),
            "errors": 0,
            "successes": 0,
        }
    stats = _perf_stats[model_name]
    stats["latencies"].append(latency_ms)
    if success:
        stats["successes"] += 1
    else:
        stats["errors"] += 1


def get_model_perf(model_name: str) -> dict:
    """Return p50/p90 latency and error rate for a model."""
    stats = _perf_stats.get(model_name)
    if not stats or not stats["latencies"]:
        return {"p50_ms": None, "p90_ms": None, "error_rate": 0.0, "calls": 0}
    latencies = sorted(stats["latencies"])
    n = len(latencies)
    total_calls = stats["successes"] + stats["errors"]
    return {
        "p50_ms": latencies[n // 2],
        "p90_ms": latencies[int(n * 0.9)],
        "error_rate": stats["errors"] / total_calls if total_calls else 0.0,
        "calls": total_calls,
    }


def get_all_perf() -> dict:
    """Return perf stats for all models (for /health endpoint)."""
    return {m: get_model_perf(m) for m in _perf_stats}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def resolve_model_name(name: str) -> str:
    """Resolve an alias or canonical name. Raises ModelNotFoundError if unknown."""
    if name == "auto":
        return "auto"
    if name in MODEL_REGISTRY:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    raise ModelNotFoundError(f"Unknown model: {name}")


def get_model_config(name: str) -> dict:
    """Return full config dict for a model (accepts aliases)."""
    canonical = resolve_model_name(name)
    return MODEL_REGISTRY[canonical]


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Return USD cost for the given token counts."""
    cfg = get_model_config(model_name)
    return (input_tokens / 1_000_000) * cfg["input_cost_per_m"] + \
           (output_tokens / 1_000_000) * cfg["output_cost_per_m"]


def list_models() -> list[dict]:
    """Return list of all model configs (for API response)."""
    return list(MODEL_REGISTRY.values())

# ---------------------------------------------------------------------------
# Lazy-initialized provider clients
# ---------------------------------------------------------------------------

_anthropic_client = None
_openai_client = None
_google_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ModelNotFoundError("ANTHROPIC_API_KEY not configured")
        _anthropic_client = anthropic.Anthropic(api_key=key)
    return _anthropic_client


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ModelNotFoundError("OPENAI_API_KEY not configured")
        _openai_client = OpenAI(api_key=key)
    return _openai_client


def _get_google_client():
    global _google_client
    if _google_client is None:
        from google import genai
        key = os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            raise ModelNotFoundError("GOOGLE_API_KEY not configured")
        _google_client = genai.Client(api_key=key)
    return _google_client

# ---------------------------------------------------------------------------
# Unified call_model
# ---------------------------------------------------------------------------

def _dispatch(cfg: dict, messages: list[dict], system: str, tok_limit: int, temperature: float) -> dict:
    """Dispatch to the right provider. Raises on failure."""
    provider = cfg["provider"]
    model_id = cfg["model_id"]
    if provider == "anthropic":
        return _call_anthropic(model_id, messages, system, tok_limit, temperature)
    elif provider == "openai":
        return _call_openai(model_id, messages, system, tok_limit, temperature)
    elif provider == "google":
        return _call_google(model_id, messages, system, tok_limit, temperature)
    elif provider == "deepseek":
        return _call_openai_compatible(
            "https://api.deepseek.com/chat/completions",
            os.environ.get("DEEPSEEK_API_KEY", ""),
            model_id, messages, system, tok_limit, temperature,
        )
    elif provider == "together":
        return _call_openai_compatible(
            "https://api.together.xyz/v1/chat/completions",
            os.environ.get("TOGETHER_API_KEY", ""),
            model_id, messages, system, tok_limit, temperature,
        )
    elif provider == "xai":
        return _call_openai_compatible(
            "https://api.x.ai/v1/chat/completions",
            os.environ.get("XAI_API_KEY", ""),
            model_id, messages, system, tok_limit, temperature,
        )
    elif provider == "mistral":
        return _call_openai_compatible(
            "https://api.mistral.ai/v1/chat/completions",
            os.environ.get("MISTRAL_API_KEY", ""),
            model_id, messages, system, tok_limit, temperature,
        )
    else:
        raise ModelNotFoundError(f"Unknown provider: {provider}")


def call_model(
    model: str,
    messages: list[dict],
    system: str = "",
    max_tokens: int | None = None,
    temperature: float = 0.7,
    max_cost_usd: float | None = None,
) -> dict:
    """Call any supported model with circuit breaker + fallback.

    Returns {text, model, model_id, provider, input_tokens, output_tokens, cost_usd, selected_reason}.
    """
    selected_reason = None
    if model == "auto":
        task_text = ""
        for m in messages:
            if m.get("role") == "user":
                task_text = m.get("content", "")
                break
        selection = auto_select_model(task_text, max_cost_usd=max_cost_usd)
        model = selection["model"]
        selected_reason = selection["reason"]

    cfg = get_model_config(model)
    canonical = cfg["canonical_name"]
    provider = cfg["provider"]
    tok_limit = max_tokens or cfg["max_tokens"]

    # Inject domain system prompt if caller didn't provide one
    if not system:
        task_text = messages[-1].get("content", "") if messages else ""
        _cls = _classify_task(task_text)
        system = _get_domain_prompt(_cls["domain"])

    # Check circuit breaker — if provider is down, try fallback immediately
    if not _check_circuit(provider):
        fallback = _get_fallback_model(canonical)
        if fallback:
            cfg = get_model_config(fallback)
            canonical = cfg["canonical_name"]
            provider = cfg["provider"]
            tok_limit = max_tokens or cfg["max_tokens"]

    # Check cache (skip for high-temperature creative calls)
    cache_key = None
    if temperature <= 0.9:
        cache_key = _cache_key(canonical, messages, system, temperature)
        cached = _cache_get(cache_key)
        if cached is not None:
            cost = calculate_cost(canonical, cached["input_tokens"], cached["output_tokens"])
            return {**cached, "model": canonical, "model_id": cfg["model_id"],
                    "provider": provider, "cost_usd": cost, "cached": True,
                    "selected_reason": selected_reason}

    t0 = _time.time()
    result = None
    last_exc = None
    for attempt in range(_RETRY_MAX_ATTEMPTS + 1):
        try:
            result = _dispatch(cfg, messages, system, tok_limit, temperature)
            latency_ms = (_time.time() - t0) * 1000
            _record_perf(canonical, latency_ms, True)
            _record_success(provider)
            break
        except BillingError:
            raise
        except RateLimitError as exc:
            last_exc = exc
            if attempt < _RETRY_MAX_ATTEMPTS:
                delay = exc.retry_after or (_RETRY_BASE_DELAY * (2 ** attempt))
                _log.info("Rate limited on %s attempt %d, retrying in %.1fs", canonical, attempt + 1, delay)
                _time.sleep(delay)
                continue
            latency_ms = (_time.time() - t0) * 1000
            _record_perf(canonical, latency_ms, False)
            _record_failure(provider)
        except Exception as exc:
            last_exc = exc
            if attempt < _RETRY_MAX_ATTEMPTS:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                _log.info("Transient error on %s attempt %d, retrying in %.1fs", canonical, attempt + 1, delay)
                _time.sleep(delay)
                continue
            latency_ms = (_time.time() - t0) * 1000
            _record_perf(canonical, latency_ms, False)
            _log.warning("Provider %s failed for %s after %d attempts: %s", provider, canonical, attempt + 1, type(exc).__name__)
            _record_failure(provider)

    # Fallback if all retries failed
    if result is None:
        fallback = _get_fallback_model(canonical)
        if fallback:
            fb_cfg = get_model_config(fallback)
            fb_provider = fb_cfg["provider"]
            fb_tok_limit = max_tokens or fb_cfg["max_tokens"]
            fb_t0 = _time.time()
            result = _dispatch(fb_cfg, messages, system, fb_tok_limit, temperature)
            fb_latency = (_time.time() - fb_t0) * 1000
            _record_perf(fb_cfg["canonical_name"], fb_latency, True)
            _record_success(fb_provider)
            canonical = fb_cfg["canonical_name"]
            provider = fb_provider
            cfg = fb_cfg
        elif last_exc:
            raise last_exc

    # Store in cache
    if cache_key and result:
        _cache_store(cache_key, {"text": result["text"], "input_tokens": result["input_tokens"],
                                  "output_tokens": result["output_tokens"]})

    cost = calculate_cost(canonical, result["input_tokens"], result["output_tokens"])

    # Auto-feedback: score and record outcome
    classification = _classify_task(messages[-1].get("content", "") if messages else "")
    latency_ms_total = (_time.time() - t0) * 1000
    auto_score = _auto_score_response(result["text"], latency_ms_total)
    record_outcome(canonical, classification["domain"], auto_score)

    return {
        "text": result["text"],
        "model": canonical,
        "model_id": cfg["model_id"],
        "provider": provider,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cost_usd": cost,
        "selected_reason": selected_reason,
    }

def call_model_stream(
    model: str,
    messages: list[dict],
    system: str = "",
    max_tokens: int | None = None,
    temperature: float = 0.7,
):
    """Stream tokens from any supported model. Yields dicts:
    - {"text": "chunk"} for each text chunk
    - {"done": True, "model": ..., "cost_usd": ..., "input_tokens": ..., "output_tokens": ...} at the end
    Falls back to blocking call_model() for providers without streaming support.
    """
    if model == "auto":
        task_text = ""
        for m in messages:
            if m.get("role") == "user":
                task_text = m.get("content", "")
                break
        selection = auto_select_model(task_text)
        model = selection["model"]

    cfg = get_model_config(model)
    canonical = cfg["canonical_name"]
    provider = cfg["provider"]
    tok_limit = max_tokens or cfg["max_tokens"]

    if not _check_circuit(provider):
        fallback = _get_fallback_model(canonical)
        if fallback:
            cfg = get_model_config(fallback)
            canonical = cfg["canonical_name"]
            provider = cfg["provider"]
            tok_limit = max_tokens or cfg["max_tokens"]

    try:
        if provider == "anthropic":
            yield from _stream_anthropic(cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        elif provider == "openai":
            yield from _stream_openai(cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        elif provider == "google":
            # Google genai doesn't support SSE streaming — blocking fallback
            result = call_model(model, messages, system=system, max_tokens=max_tokens, temperature=temperature)
            yield {"text": result["text"]}
            yield {"done": True, "model": canonical, "cost_usd": result["cost_usd"],
                   "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"]}
        elif provider == "deepseek":
            yield from _stream_openai_compatible(
                "https://api.deepseek.com/chat/completions",
                os.environ.get("DEEPSEEK_API_KEY", ""),
                cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        elif provider == "together":
            yield from _stream_openai_compatible(
                "https://api.together.xyz/v1/chat/completions",
                os.environ.get("TOGETHER_API_KEY", ""),
                cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        elif provider == "xai":
            yield from _stream_openai_compatible(
                "https://api.x.ai/v1/chat/completions",
                os.environ.get("XAI_API_KEY", ""),
                cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        elif provider == "mistral":
            yield from _stream_openai_compatible(
                "https://api.mistral.ai/v1/chat/completions",
                os.environ.get("MISTRAL_API_KEY", ""),
                cfg["model_id"], messages, system, tok_limit, temperature, canonical)
        else:
            result = call_model(model, messages, system=system, max_tokens=max_tokens, temperature=temperature)
            yield {"text": result["text"]}
            yield {"done": True, "model": canonical, "cost_usd": result["cost_usd"],
                   "input_tokens": result["input_tokens"], "output_tokens": result["output_tokens"]}
        _record_success(provider)
    except Exception as exc:
        _log.warning("Stream failed for %s/%s: %s", provider, canonical, exc)
        _record_failure(provider)
        raise


def _stream_anthropic(model_id, messages, system, max_tokens, temperature, canonical):
    client = _get_anthropic_client()
    kwargs = dict(model=model_id, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if system:
        kwargs["system"] = system
    with client.messages.stream(**kwargs) as stream:
        for text in stream.text_stream:
            yield {"text": text}
        resp = stream.get_final_message()
    cost = calculate_cost(canonical, resp.usage.input_tokens, resp.usage.output_tokens)
    yield {"done": True, "model": canonical, "cost_usd": cost,
           "input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}


def _stream_openai(model_id, messages, system, max_tokens, temperature, canonical):
    client = _get_openai_client()
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    stream = client.chat.completions.create(
        model=model_id, messages=msgs, max_tokens=max_tokens, temperature=temperature, stream=True,
    )
    full_text = ""
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            text = chunk.choices[0].delta.content
            full_text += text
            yield {"text": text}
    # Estimate tokens (OpenAI streaming doesn't give exact counts in every chunk)
    est_input = sum(len(m.get("content", "").split()) * 1.3 for m in msgs)
    est_output = len(full_text.split()) * 1.3
    cost = calculate_cost(canonical, int(est_input), int(est_output))
    yield {"done": True, "model": canonical, "cost_usd": cost,
           "input_tokens": int(est_input), "output_tokens": int(est_output)}


def _stream_openai_compatible(base_url, api_key, model_id, messages, system, max_tokens, temperature, canonical):
    """Stream from any OpenAI-compatible API (DeepSeek, Together, xAI, Mistral)."""
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    full_text = ""
    with httpx.stream(
        "POST", base_url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model_id, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature, "stream": True},
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break
            try:
                chunk = _json.loads(data_str)
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                content = delta.get("content", "")
                if content:
                    full_text += content
                    yield {"text": content}
            except (_json.JSONDecodeError, IndexError, KeyError):
                continue
    est_input = sum(len(m.get("content", "").split()) * 1.3 for m in msgs)
    est_output = len(full_text.split()) * 1.3
    cost = calculate_cost(canonical, int(est_input), int(est_output))
    yield {"done": True, "model": canonical, "cost_usd": cost,
           "input_tokens": int(est_input), "output_tokens": int(est_output)}


# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

class BillingError(Exception):
    """Raised when the provider rejects a request due to billing/credit issues."""
    pass


class RateLimitError(Exception):
    """Raised when a provider returns 429 Too Many Requests."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_RETRY_MAX_ATTEMPTS = 2
_RETRY_BASE_DELAY = 1.0  # seconds


def _call_anthropic(model_id, messages, system, max_tokens, temperature):
    client = _get_anthropic_client()
    kwargs = dict(model=model_id, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if system:
        kwargs["system"] = system
    try:
        resp = client.messages.create(**kwargs)
    except Exception as exc:
        msg = str(exc).lower()
        if "credit balance" in msg or "billing" in msg or "purchase credits" in msg:
            raise BillingError(f"Anthropic billing error: {exc}") from exc
        raise
    return {
        "text": resp.content[0].text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
    }


def _call_openai(model_id, messages, system, max_tokens, temperature):
    client = _get_openai_client()
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    resp = client.chat.completions.create(
        model=model_id, messages=msgs, max_tokens=max_tokens, temperature=temperature,
    )
    choice = resp.choices[0]
    return {
        "text": choice.message.content,
        "input_tokens": resp.usage.prompt_tokens,
        "output_tokens": resp.usage.completion_tokens,
    }


def _call_google(model_id, messages, system, max_tokens, temperature):
    client = _get_google_client()
    contents = []
    for m in messages:
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})
    config = {"max_output_tokens": max_tokens, "temperature": temperature}
    if system:
        config["system_instruction"] = system
    resp = client.models.generate_content(
        model=model_id, contents=contents, config=config,
    )
    return {
        "text": resp.text,
        "input_tokens": resp.usage_metadata.prompt_token_count,
        "output_tokens": resp.usage_metadata.candidates_token_count,
    }


def _call_openai_compatible(base_url, api_key, model_id, messages, system, max_tokens, temperature):
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.extend(messages)
    try:
        resp = httpx.post(
            base_url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model_id, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature},
            timeout=120,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            retry_after = None
            ra_header = e.response.headers.get("retry-after")
            if ra_header:
                try:
                    retry_after = float(ra_header)
                except ValueError:
                    pass
            raise RateLimitError(f"Rate limited by {base_url}", retry_after=retry_after) from e
        _log.error("API error from %s model=%s status=%s key=%s", base_url, model_id, e.response.status_code, _mask_key(api_key))
        raise
    except Exception as e:
        _log.error("Request failed to %s model=%s key=%s: %s", base_url, model_id, _mask_key(api_key), type(e).__name__)
        raise
    data = resp.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})
    return {
        "text": choice["message"]["content"],
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


# ---------------------------------------------------------------------------
# Cost Tracker — cumulative cost tracking for multi-step agent sessions
# ---------------------------------------------------------------------------

class CostTracker:
    """Tracks cumulative cost across multiple model calls in a session."""

    def __init__(self):
        self.total = 0.0
        self.steps: list[dict] = []

    def add(self, cost: float, step_info: dict | None = None):
        self.total += cost
        if step_info:
            self.steps.append({**step_info, "cost": cost, "cumulative": self.total})

    def can_afford(self, estimated_cost: float, budget: float | None) -> bool:
        if budget is None:
            return True
        return (self.total + estimated_cost) <= budget

    def remaining(self, budget: float | None) -> float:
        if budget is None:
            return float("inf")
        return max(0.0, budget - self.total)


# ---------------------------------------------------------------------------
# Smart Model Selection — classify task and pick optimal model
# ---------------------------------------------------------------------------

import re as _re

_COMPLEX_KEYWORDS = {
    5: ["prove", "theorem", "formal verification", "mathematical proof"],
    4: ["algorithm", "dynamic programming", "recursive", "optimize", "architecture", "design system",
        "security audit", "vulnerability", "machine learning model"],
    3: ["analyze", "compare multiple", "step by step", "detailed", "comprehensive",
        "debug", "refactor", "review code", "explain why"],
}

_REASONING_KEYWORDS = ["why", "prove", "reason", "logic", "deduce", "infer", "step by step",
                        "think through", "algorithm", "mathematical"]

_VISION_KEYWORDS = ["image", "photo", "picture", "screenshot", "diagram", "chart", "visual",
                     "describe what you see", "look at"]


def _classify_task(task_text: str) -> dict:
    text_lower = task_text.lower()
    word_count = len(task_text.split())
    complexity = 1
    if word_count > 100:
        complexity = max(complexity, 3)
    elif word_count > 50:
        complexity = max(complexity, 2)
    for level, keywords in _COMPLEX_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            complexity = max(complexity, level)
            break
    needs_vision = any(kw in text_lower for kw in _VISION_KEYWORDS)
    needs_reasoning = any(kw in text_lower for kw in _REASONING_KEYWORDS)
    if needs_reasoning and complexity < 3:
        complexity = 3
    domain = "general"
    domain_map = {
        "code": ["code", "function", "class", "bug", "python", "javascript", "api", "sql", "debug"],
        "research": ["research", "study", "paper", "literature", "survey", "findings"],
        "creative": ["write", "story", "poem", "creative", "blog", "article", "essay"],
        "data": ["data", "csv", "json", "parse", "transform", "pipeline", "etl"],
        "finance": ["stock", "financial", "investment", "portfolio", "revenue", "pricing"],
    }
    for d, keywords in domain_map.items():
        if any(kw in text_lower for kw in keywords):
            domain = d
            break
    return {"complexity": min(complexity, 5), "needs_vision": needs_vision, "needs_reasoning": needs_reasoning, "domain": domain}


_MODEL_TIERS = {
    "low": ["claude-haiku", "gpt-4o-mini", "gemini-2.5-flash", "deepseek-v3", "grok-3-mini", "mistral-small"],
    "mid": ["claude-sonnet", "gpt-4o", "gemini-2.5-pro", "grok-3", "mistral-large-direct"],
    "high": ["claude-opus", "deepseek-r1"],
}

# Domain-specific model preferences (model -> bonus score for that domain)
_DOMAIN_PREFERENCES: dict[str, dict[str, float]] = {
    "code": {"deepseek-v3": 0.3, "deepseek-r1": 0.2, "claude-sonnet": 0.15, "gpt-4o": 0.1},
    "reasoning": {"claude-opus": 0.3, "deepseek-r1": 0.25, "claude-sonnet": 0.15, "gemini-2.5-pro": 0.1},
    "creative": {"claude-sonnet": 0.2, "claude-opus": 0.15, "gpt-4o": 0.15, "grok-3": 0.1},
    "research": {"gemini-2.5-pro": 0.2, "claude-sonnet": 0.15, "gpt-4o": 0.1},
    "data": {"deepseek-v3": 0.2, "gpt-4o-mini": 0.1},
    "finance": {"claude-sonnet": 0.15, "gpt-4o": 0.15},
    "general": {},
}

# ---------------------------------------------------------------------------
# Domain-specific system prompts — applied when caller provides no system prompt
# ---------------------------------------------------------------------------

_DOMAIN_SYSTEM_PROMPTS = {
    "code": "You are a precise coding assistant. Return code directly. Use comments only where logic is non-obvious. No preambles.",
    "research": "You are a thorough research assistant. Cite sources when available. Be comprehensive but concise.",
    "creative": "You are a creative writing assistant. Be vivid, original, and engaging. Match the requested tone.",
    "data": "You are a data processing assistant. Return structured output (JSON/CSV) when appropriate. Be exact with numbers.",
    "finance": "You are a financial analysis assistant. Be precise with numbers. Note assumptions and risks.",
    "general": "You are a helpful AI assistant. Be concise and direct.",
}


def _get_domain_prompt(domain: str) -> str:
    """Return the system prompt for a domain, falling back to general."""
    return _DOMAIN_SYSTEM_PROMPTS.get(domain, _DOMAIN_SYSTEM_PROMPTS["general"])


# ---------------------------------------------------------------------------
# Outcome-based feedback loop — adjusts domain preferences dynamically
# ---------------------------------------------------------------------------

from collections import deque as _deque

_OUTCOME_WINDOW = 20  # rolling window size per model+domain
_outcome_stats: dict[str, dict[str, _deque]] = {}  # {model: {domain: deque([scores])}}


def record_outcome(model: str, domain: str, quality_score: float) -> None:
    """Record a quality outcome (0.0–1.0) for a model+domain pair.
    0.0 = failure, 0.5 = neutral, 1.0 = excellent."""
    quality_score = max(0.0, min(1.0, quality_score))
    if model not in _outcome_stats:
        _outcome_stats[model] = {}
    if domain not in _outcome_stats[model]:
        _outcome_stats[model][domain] = _deque(maxlen=_OUTCOME_WINDOW)
    _outcome_stats[model][domain].append(quality_score)


def get_outcome_adjustment(model: str, domain: str) -> float:
    """Get dynamic score adjustment based on recorded outcomes.
    Returns a value in [-0.1, +0.1] to add to the auto_select score."""
    stats = _outcome_stats.get(model, {}).get(domain)
    if not stats or len(stats) < 3:
        return 0.0
    avg = sum(stats) / len(stats)
    return (avg - 0.5) * 0.2  # maps [0,1] -> [-0.1, +0.1]


def get_all_outcomes() -> dict:
    """Return all outcome stats for debugging/display."""
    result = {}
    for model, domains in _outcome_stats.items():
        result[model] = {}
        for domain, scores in domains.items():
            s = list(scores)
            result[model][domain] = {
                "count": len(s),
                "avg": round(sum(s) / len(s), 3) if s else 0,
                "recent": [round(x, 3) for x in s[-5:]],
            }
    return result


# ---------------------------------------------------------------------------
# Auto-scoring — heuristic quality scoring for the feedback loop
# ---------------------------------------------------------------------------

_REFUSAL_PHRASES = ["i cannot", "i'm unable", "i am unable", "as an ai", "i can't help",
                     "i'm not able", "i apologize, but i cannot"]


def _auto_score_response(text: str, latency_ms: float) -> float:
    """Auto-score a response for the feedback loop. Returns 0.0-1.0."""
    score = 0.7  # neutral-positive baseline
    text_lower = text.lower().strip()

    # Penalize empty/very short
    if len(text_lower) < 10:
        score -= 0.3
    # Penalize refusals
    if any(phrase in text_lower for phrase in _REFUSAL_PHRASES):
        score -= 0.2
    # Penalize slow responses
    if latency_ms > 10000:
        score -= 0.1
    # Reward fast responses
    if latency_ms < 2000:
        score += 0.1
    # Reward substantial output
    if len(text.split()) > 50:
        score += 0.1

    return max(0.0, min(1.0, score))


def auto_select_model(task_text: str, max_cost_usd: float | None = None,
                      needs_vision: bool | None = None, prefer_fast: bool = False) -> dict:
    """Score all eligible models and pick the best one."""
    classification = _classify_task(task_text)
    if needs_vision is not None:
        classification["needs_vision"] = needs_vision

    c = classification["complexity"]
    domain = classification["domain"]
    candidates = []

    for name, cfg in MODEL_REGISTRY.items():
        if classification["needs_vision"] and not cfg.get("vision"):
            continue
        if max_cost_usd is not None:
            est = calculate_cost(name, 500, 500)
            if est > max_cost_usd:
                continue

        score = 0.0
        tier = cfg.get("latency_tier", "medium")

        # 1. Complexity-tier match (0 to 1.0)
        if c <= 2:
            score += {"fast": 1.0, "medium": 0.4, "slow": 0.1}[tier]
        elif c <= 3:
            score += {"fast": 0.4, "medium": 1.0, "slow": 0.6}[tier]
        else:
            score += {"fast": 0.1, "medium": 0.5, "slow": 1.0}[tier]

        # 2. Domain preference bonus (0 to 0.3) + dynamic feedback adjustment
        domain_prefs = _DOMAIN_PREFERENCES.get(domain, {})
        score += domain_prefs.get(name, 0.0)
        score += get_outcome_adjustment(name, domain)

        # 3. Strength match bonus (0 to 0.2)
        strengths = cfg.get("strengths", [])
        if domain in strengths:
            score += 0.2
        if classification["needs_reasoning"] and "reasoning" in strengths:
            score += 0.15

        # 4. Cost efficiency (0 to 0.3) — cheaper is better for equal capability
        cost_per_1k = (cfg["input_cost_per_m"] + cfg["output_cost_per_m"]) / 2000
        max_cost_per_1k = 45.0
        cost_score = 0.3 * (1 - min(cost_per_1k / max_cost_per_1k, 1.0))
        score += cost_score

        # 5. Latency preference (for prefer_fast or simple tasks)
        if prefer_fast or c <= 1:
            latency_scores = {"fast": 1.0, "medium": 0.6, "slow": 0.3}
            score += latency_scores.get(tier, 0.5) * 0.3

        # 6. Runtime performance bonus (if we have data)
        perf = get_model_perf(name)
        if perf["calls"] >= 5:
            score -= perf["error_rate"] * 0.5
            if perf["p50_ms"] and perf["p50_ms"] < 2000:
                score += 0.1

        candidates.append((name, score))

    if not candidates:
        candidates = [("claude-haiku", 0.0)]

    candidates.sort(key=lambda x: -x[1])
    selected = candidates[0][0]
    top3 = [(n, round(s, 3)) for n, s in candidates[:3]]

    reason = f"complexity={c}/5, domain={domain}, top3={top3}"
    return {"model": selected, "reason": reason, "classification": classification}
