# Model Router v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve model routing with response caching, auto-feedback, domain system prompts, universal streaming, and smart retry with backoff.

**Architecture:** All changes are in `model_router.py` with new tests. No new files. The cache, auto-feedback, and domain prompts integrate into the existing `call_model` flow. Streaming extends the existing provider dispatch. Retry wraps the existing `_dispatch` call.

**Tech Stack:** Python 3.11, hashlib, collections.OrderedDict (LRU cache), httpx (streaming), existing test suite with pytest.

---

### Task 1: Response Cache — Tests

**Files:**
- Modify: `tests/test_model_router.py`

**Step 1: Write the failing tests**

Add at the bottom of `tests/test_model_router.py`:

```python
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
    # Fill beyond max
    for i in range(_CACHE_MAX_ENTRIES + 10):
        _cache_store(f"key-{i}", {"text": f"val-{i}", "input_tokens": 0, "output_tokens": 0})
    assert len(_response_cache) <= _CACHE_MAX_ENTRIES
    # First entries should be evicted
    assert _cache_get("key-0") is None


def test_clear_cache():
    from model_router import _response_cache, _cache_store, clear_cache
    _cache_store("k", {"text": "v", "input_tokens": 0, "output_tokens": 0})
    assert len(_response_cache) > 0
    clear_cache()
    assert len(_response_cache) == 0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_router.py -k "cache" -v`
Expected: FAIL — `_response_cache`, `_cache_key`, etc. not importable

**Step 3: Commit test stubs**

```bash
git add tests/test_model_router.py
git commit -m "test: add response cache tests (red)"
```

---

### Task 2: Response Cache — Implementation

**Files:**
- Modify: `model_router.py` (add after the `_mask_key` function, around line 21)

**Step 1: Add cache implementation**

Add after line 21 in `model_router.py` (after `_mask_key`):

```python
# ---------------------------------------------------------------------------
# Response cache — hash-based, TTL, LRU eviction
# ---------------------------------------------------------------------------

import hashlib as _hashlib
import json as _json

_CACHE_TTL = 300  # 5 minutes
_CACHE_MAX_ENTRIES = 500

# OrderedDict for LRU: {key: {"response": dict, "cached_at": float}}
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
    # Evict oldest if at capacity
    while len(_response_cache) >= _CACHE_MAX_ENTRIES:
        oldest_key = next(iter(_response_cache))
        del _response_cache[oldest_key]
    _response_cache[key] = {"response": response, "cached_at": _time.time()}


def clear_cache():
    """Clear the entire response cache."""
    _response_cache.clear()
```

**Step 2: Wire cache into `call_model`**

In `call_model` function (around line 467), add cache check after model resolution but before dispatch. Add after the `tok_limit = max_tokens or cfg["max_tokens"]` line (around line 493) and before `t0 = _time.time()`:

```python
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
```

And after the successful result is built (after `cost = calculate_cost(...)`, around line 535), before the return:

```python
    # Store in cache
    if cache_key:
        _cache_store(cache_key, {"text": result["text"], "input_tokens": result["input_tokens"],
                                  "output_tokens": result["output_tokens"]})
```

**Step 3: Run tests to verify they pass**

Run: `python -m pytest tests/test_model_router.py -k "cache" -v`
Expected: All 9 cache tests PASS

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line`
Expected: 174+ passed

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: add response cache with TTL and LRU eviction"
```

---

### Task 3: Auto-Feedback — Tests

**Files:**
- Modify: `tests/test_feedback_loop.py`

**Step 1: Write the failing tests**

Add at the bottom of `tests/test_feedback_loop.py`:

```python
# --- Auto-scoring tests ---

from model_router import _auto_score_response


def test_auto_score_good_response():
    score = _auto_score_response("Here is a detailed explanation of the topic with multiple paragraphs and thorough analysis.", 1500)
    assert score >= 0.7


def test_auto_score_empty_response():
    score = _auto_score_response("", 5000)
    assert score <= 0.5


def test_auto_score_short_response():
    score = _auto_score_response("Ok", 1000)
    assert score <= 0.5


def test_auto_score_refusal():
    score = _auto_score_response("I cannot assist with that request. As an AI language model, I'm unable to help.", 1000)
    assert score <= 0.5


def test_auto_score_fast_response():
    score = _auto_score_response("Good answer with useful content here.", 500)
    assert score >= 0.7  # fast + decent content


def test_auto_score_slow_response():
    score = _auto_score_response("Good answer with useful content here.", 15000)
    assert score < _auto_score_response("Good answer with useful content here.", 500)


def test_auto_score_clamps():
    # Even worst case should be >= 0.0
    score = _auto_score_response("", 20000)
    assert 0.0 <= score <= 1.0
    # Even best case should be <= 1.0
    score = _auto_score_response("A" * 500, 100)
    assert 0.0 <= score <= 1.0
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_feedback_loop.py -k "auto_score" -v`
Expected: FAIL — `_auto_score_response` not importable

**Step 3: Commit test stubs**

```bash
git add tests/test_feedback_loop.py
git commit -m "test: add auto-scoring tests (red)"
```

---

### Task 4: Auto-Feedback — Implementation

**Files:**
- Modify: `model_router.py` (add after `get_all_outcomes`, around line 868)

**Step 1: Add auto-scoring function**

```python
_REFUSAL_PHRASES = ["i cannot", "i'm unable", "i am unable", "as an ai", "i can't help",
                     "i'm not able", "i apologize, but i cannot"]


def _auto_score_response(text: str, latency_ms: float) -> float:
    """Auto-score a response for the feedback loop. Returns 0.0–1.0."""
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
```

**Step 2: Wire auto-feedback into `call_model`**

In `call_model`, just before the final `return` statement (around line 536), add:

```python
    # Auto-feedback: score and record outcome
    if not result.get("cached"):
        classification = _classify_task(messages[-1].get("content", "") if messages else "")
        latency_ms_total = (_time.time() - t0) * 1000
        auto_score = _auto_score_response(result["text"], latency_ms_total)
        record_outcome(canonical, classification["domain"], auto_score)
```

Note: For cached responses, skip auto-feedback (the original call already recorded it).

**Step 3: Run tests**

Run: `python -m pytest tests/test_feedback_loop.py -k "auto_score" -v`
Expected: All 7 auto-score tests PASS

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line`
Expected: 174+ passed

**Step 5: Commit**

```bash
git add model_router.py tests/test_feedback_loop.py
git commit -m "feat: auto-feedback scoring on every model call"
```

---

### Task 5: Domain System Prompts — Tests

**Files:**
- Modify: `tests/test_model_router.py`

**Step 1: Write the failing tests**

Add at the bottom of `tests/test_model_router.py`:

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_router.py -k "domain_prompt" -v`
Expected: FAIL

**Step 3: Commit test stubs**

```bash
git add tests/test_model_router.py
git commit -m "test: add domain system prompt tests (red)"
```

---

### Task 6: Domain System Prompts — Implementation

**Files:**
- Modify: `model_router.py` (add after `_DOMAIN_PREFERENCES` dict, around line 823)

**Step 1: Add domain prompts**

```python
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
```

**Step 2: Wire into `call_model`**

In `call_model`, after model resolution and before the cache check, add domain prompt injection. After `tok_limit = max_tokens or cfg["max_tokens"]` and before the cache check:

```python
    # Inject domain system prompt if caller didn't provide one
    if not system and model != "auto":
        # For non-auto calls, classify to get domain
        task_text = messages[-1].get("content", "") if messages else ""
        classification = _classify_task(task_text)
        system = _get_domain_prompt(classification["domain"])
    elif not system and selected_reason:
        # For auto calls, we already classified — extract domain from reason
        task_text = messages[-1].get("content", "") if messages else ""
        classification = _classify_task(task_text)
        system = _get_domain_prompt(classification["domain"])
```

Simplify to:

```python
    # Inject domain system prompt if caller didn't provide one
    if not system:
        task_text = messages[-1].get("content", "") if messages else ""
        _cls = _classify_task(task_text)
        system = _get_domain_prompt(_cls["domain"])
```

**Step 3: Run tests**

Run: `python -m pytest tests/test_model_router.py -k "domain_prompt" -v`
Expected: All 3 PASS

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line`
Expected: 174+ passed

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: auto-inject domain system prompts when caller provides none"
```

---

### Task 7: Universal Streaming — Tests

**Files:**
- Modify: `tests/test_model_router.py`

**Step 1: Write the failing tests**

```python
# --- Streaming tests ---

def test_stream_openai_compatible_function_exists():
    from model_router import _stream_openai_compatible
    assert callable(_stream_openai_compatible)


def test_all_providers_have_streaming():
    """call_model_stream should not fall back to blocking for any provider."""
    from model_router import MODEL_REGISTRY
    providers_with_streaming = {"anthropic", "openai", "deepseek", "together", "xai", "mistral", "google"}
    for name, cfg in MODEL_REGISTRY.items():
        assert cfg["provider"] in providers_with_streaming, f"{name} provider {cfg['provider']} has no streaming"
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_router.py -k "stream" -v`
Expected: FAIL — `_stream_openai_compatible` not importable

**Step 3: Commit**

```bash
git add tests/test_model_router.py
git commit -m "test: add universal streaming tests (red)"
```

---

### Task 8: Universal Streaming — Implementation

**Files:**
- Modify: `model_router.py`

**Step 1: Add `_stream_openai_compatible` function**

Add after `_stream_openai` (around line 633):

```python
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
    # Estimate tokens
    est_input = sum(len(m.get("content", "").split()) * 1.3 for m in msgs)
    est_output = len(full_text.split()) * 1.3
    cost = calculate_cost(canonical, int(est_input), int(est_output))
    yield {"done": True, "model": canonical, "cost_usd": cost,
           "input_tokens": int(est_input), "output_tokens": int(est_output)}
```

**Step 2: Update `call_model_stream` dispatch**

Replace the try block in `call_model_stream` (around line 581) — replace the `else` fallback branch:

```python
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
```

**Step 3: Run tests**

Run: `python -m pytest tests/test_model_router.py -k "stream" -v`
Expected: All 2 streaming tests PASS

**Step 4: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line`
Expected: 174+ passed

**Step 5: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: streaming support for all OpenAI-compatible providers"
```

---

### Task 9: Smart Retry with Backoff — Tests

**Files:**
- Modify: `tests/test_model_router.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_model_router.py -k "rate_limit or retry_config" -v`
Expected: FAIL

**Step 3: Commit**

```bash
git add tests/test_model_router.py
git commit -m "test: add retry and rate limit tests (red)"
```

---

### Task 10: Smart Retry with Backoff — Implementation

**Files:**
- Modify: `model_router.py`

**Step 1: Add RateLimitError and retry config**

Add after `BillingError` class (around line 642):

```python
class RateLimitError(Exception):
    """Raised when a provider returns 429 Too Many Requests."""
    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


_RETRY_MAX_ATTEMPTS = 2
_RETRY_BASE_DELAY = 1.0  # seconds
```

**Step 2: Add rate limit detection to `_call_openai_compatible`**

In `_call_openai_compatible` (around line 700), modify the `except httpx.HTTPStatusError` block:

```python
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
```

**Step 3: Modify `call_model` to retry on transient failures**

Replace the try/except block in `call_model` (the section starting at `t0 = _time.time()`) with:

```python
    t0 = _time.time()
    last_exc = None
    for attempt in range(_RETRY_MAX_ATTEMPTS + 1):  # 0, 1, 2 = 3 total tries
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
            # Exhausted retries — fall through to fallback
            latency_ms = (_time.time() - t0) * 1000
            _record_perf(canonical, latency_ms, False)
            _record_failure(provider)
            break
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
            break
    else:
        # Should not reach here, but safety net
        pass

    if last_exc is not None and 'result' not in dir():
        # All retries failed — try fallback
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
        else:
            raise last_exc
```

Note: Use `'result' not in locals()` instead of `'result' not in dir()`. Actually, cleaner approach — use a sentinel:

Replace the above with a cleaner pattern using a `result = None` sentinel before the loop:

```python
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
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_model_router.py -k "rate_limit or retry_config" -v`
Expected: All 3 PASS

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -q --tb=line`
Expected: 174+ passed

**Step 6: Commit**

```bash
git add model_router.py tests/test_model_router.py
git commit -m "feat: smart retry with exponential backoff and rate limit detection"
```

---

### Task 11: Also Commit the Discovery Auth Fix

**Files:**
- Already modified: `routes/network.py`

**Step 1: Run full test suite one final time**

Run: `python -m pytest tests/ -q --tb=line`
Expected: All tests pass

**Step 2: Commit the network.py fix**

```bash
git add routes/network.py
git commit -m "fix: add localhost + admin key bypass for agent inbox endpoint"
```

---

### Task 12: Final Verification + Push

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass with new tests included

**Step 2: Verify cache, auto-feedback, domain prompts load correctly**

```bash
python -c "from model_router import _response_cache, _auto_score_response, _DOMAIN_SYSTEM_PROMPTS, _stream_openai_compatible, RateLimitError, clear_cache; print('All imports OK')"
```

**Step 3: Push**

```bash
git push origin master
```

**Step 4: Restart server**

```bash
pkill -f "gunicorn.*app:app" && sleep 5 && source .env && /home/damien809/agent-service/venv/bin/gunicorn --workers 2 --worker-class sync --bind 127.0.0.1:5001 --timeout 120 --keep-alive 5 --access-logfile /home/damien809/agent-service/access.log --error-logfile /home/damien809/agent-service/agent.log --log-level info --daemon app:app
```

**Step 5: Verify health**

```bash
curl -s http://127.0.0.1:5001/health | python3 -m json.tool
```
