# Model Router v2 — Design Doc

**Date**: 2026-03-10
**Goal**: Improve model routing quality, performance, and reliability across all 5 dimensions.

## Current State

- 15 models across 7 providers (Anthropic, OpenAI, Google, DeepSeek, Together, xAI, Mistral)
- Circuit breaker + single fallback attempt per call
- `auto_select` uses keyword-based task classification + static domain preferences
- Feedback loop exists but is dead — `record_outcome` only called from manual `/feedback` endpoint and react_agent
- Zero response caching — identical calls always hit provider APIs
- Streaming only works for Anthropic + OpenAI (5 providers fall back to blocking)
- No per-tool system prompts — generic/empty prompts hurt quality

## Changes

### 1. Response Cache

**File**: `model_router.py` — new `_response_cache` dict

- Key: `sha256(model + sorted(messages) + system + temperature)`
- Value: `{"response": dict, "cached_at": float}`
- Default TTL: 300s (5 min)
- Max entries: 500 (LRU eviction)
- Skip cache for: streaming calls, temperature > 0.9
- Cache hit adds `"cached": True` to response dict
- New `clear_cache()` function exposed for admin endpoint

**Why 5 min TTL**: Balances freshness vs. cost. Most repeated calls happen within seconds (retry, UI refresh, multi-step workflows reusing same context).

### 2. Auto-Feedback on Every Call

**File**: `model_router.py` — add `_auto_score_response()` called at end of `call_model`

Scoring heuristic (0.0–1.0):
- Start at 0.7 (neutral-positive baseline)
- -0.3 if response text is empty or < 10 chars
- -0.2 if response contains refusal phrases ("I cannot", "I'm unable", "As an AI")
- -0.1 if latency > 10s
- +0.1 if latency < 2s
- +0.1 if output_tokens > 100 (substantial response)
- Clamp to [0.0, 1.0]

Calls `record_outcome(model, domain, score)` automatically. Domain derived from the same `_classify_task` used by auto_select.

**Why auto-score**: The feedback loop already exists and works — it just has no data. This gives it signal without requiring user action.

### 3. Domain System Prompts

**File**: `model_router.py` — new `_DOMAIN_SYSTEM_PROMPTS` dict

Map tool domains to optimized system prompts:
- `code`: "You are a precise coding assistant. Return code directly. Use comments only where logic is non-obvious. No preambles."
- `research`: "You are a thorough research assistant. Cite sources when available. Be comprehensive but concise."
- `creative`: "You are a creative writing assistant. Be vivid, original, and engaging. Match the requested tone."
- `data`: "You are a data processing assistant. Return structured output (JSON/CSV) when appropriate. Be exact with numbers."
- `general`: "You are a helpful AI assistant. Be concise and direct."

Applied in `call_model` only when no system prompt is provided by the caller. Callers can override by passing their own `system` param.

### 4. Streaming for All OpenAI-Compatible Providers

**File**: `model_router.py` — new `_stream_openai_compatible()` function

DeepSeek, Together, xAI, and Mistral all support SSE streaming via OpenAI-compatible endpoints. Reuse the same pattern as `_stream_openai` but with:
- Custom base URL + API key per provider
- httpx streaming client instead of openai SDK
- Same chunk format: `{"text": "chunk"}` + final `{"done": True, ...}`

Update `call_model_stream` to dispatch all 7 providers to their streaming implementations instead of falling back to blocking for 5 of them.

### 5. Smart Retry with Backoff

**File**: `model_router.py` — modify `call_model` and `call_model_stream`

Current flow: try → fail → one fallback → error
New flow: try → fail → wait 1s → retry same provider → fail → fallback → fail → error

Rate limit handling:
- Detect 429 status from httpx responses
- On 429: use `Retry-After` header if present, else exponential backoff (1s, 2s, 4s)
- Max 2 retries before fallback
- BillingError still skips all retries (unchanged)

Add `RateLimitError` exception class alongside `BillingError`.

## Files Modified

| File | Change |
|------|--------|
| `model_router.py` | Cache, auto-feedback, domain prompts, streaming, retry logic |
| `routes/ai_tools.py` | Pass domain hint to call_model where obvious |
| No new files | All changes in existing model_router.py |

## Testing

- Extend existing `tests/test_model_router.py` with cache hit/miss/eviction tests
- Extend `tests/test_feedback_loop.py` with auto-scoring tests
- Add streaming mock tests for openai-compatible providers
- Add retry/backoff tests with mocked failures

## What We're NOT Doing

- No new providers or models
- No persistent cache (disk/Redis) — in-memory is fine at current scale
- No user-facing feedback UI changes
- No prompt engineering per individual tool (155 tools × prompts = maintenance nightmare)
- No changes to circuit breaker thresholds (working fine)
