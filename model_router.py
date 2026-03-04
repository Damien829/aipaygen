"""Multi-model router — registry, resolution, cost calculation, unified call_model.

Includes circuit breaker per provider: breaks after 3 consecutive failures for 5 min.
Fallback chains: anthropic↔openai, deepseek↔together, google→anthropic.
"""

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
}

# Map provider to a cheap default model for fallback
_PROVIDER_DEFAULT: dict[str, str] = {
    "anthropic": "claude-haiku",
    "openai": "gpt-4o-mini",
    "google": "gemini-2.5-flash",
    "deepseek": "deepseek-v3",
    "together": "llama-3.3-70b",
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
# Public helpers
# ---------------------------------------------------------------------------

def resolve_model_name(name: str) -> str:
    """Resolve an alias or canonical name. Raises ModelNotFoundError if unknown."""
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
        _anthropic_client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _openai_client


def _get_google_client():
    global _google_client
    if _google_client is None:
        from google import genai
        _google_client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
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
            os.environ["DEEPSEEK_API_KEY"],
            model_id, messages, system, tok_limit, temperature,
        )
    elif provider == "together":
        return _call_openai_compatible(
            "https://api.together.xyz/v1/chat/completions",
            os.environ["TOGETHER_API_KEY"],
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
) -> dict:
    """Call any supported model with circuit breaker + fallback.

    Returns {text, model, model_id, provider, input_tokens, output_tokens, cost_usd}.
    """
    cfg = get_model_config(model)
    canonical = cfg["canonical_name"]
    provider = cfg["provider"]
    tok_limit = max_tokens or cfg["max_tokens"]

    # Check circuit breaker — if provider is down, try fallback immediately
    if not _check_circuit(provider):
        fallback = _get_fallback_model(canonical)
        if fallback:
            cfg = get_model_config(fallback)
            canonical = cfg["canonical_name"]
            provider = cfg["provider"]
            tok_limit = max_tokens or cfg["max_tokens"]

    try:
        result = _dispatch(cfg, messages, system, tok_limit, temperature)
        _record_success(provider)
    except Exception as exc:
        _log.warning("Provider %s failed for %s: %s", provider, canonical, type(exc).__name__)
        _record_failure(provider)
        # Try fallback
        fallback = _get_fallback_model(canonical)
        if fallback:
            fb_cfg = get_model_config(fallback)
            fb_provider = fb_cfg["provider"]
            fb_tok_limit = max_tokens or fb_cfg["max_tokens"]
            result = _dispatch(fb_cfg, messages, system, fb_tok_limit, temperature)
            _record_success(fb_provider)
            canonical = fb_cfg["canonical_name"]
            provider = fb_provider
            cfg = fb_cfg
        else:
            raise

    cost = calculate_cost(canonical, result["input_tokens"], result["output_tokens"])
    return {
        "text": result["text"],
        "model": canonical,
        "model_id": cfg["model_id"],
        "provider": provider,
        "input_tokens": result["input_tokens"],
        "output_tokens": result["output_tokens"],
        "cost_usd": cost,
    }

# ---------------------------------------------------------------------------
# Provider implementations
# ---------------------------------------------------------------------------

def _call_anthropic(model_id, messages, system, max_tokens, temperature):
    client = _get_anthropic_client()
    kwargs = dict(model=model_id, messages=messages, max_tokens=max_tokens, temperature=temperature)
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
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
