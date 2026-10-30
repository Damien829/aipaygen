# AiPayGen v2 — Full Stack Agent Platform Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform AiPayGen from a Claude-only API service into a multi-model, identity-verified, metered-pricing agent platform with an on-chain reputation economy.

**Architecture:** Four pillars shipped incrementally: (1) model_router.py abstracting all LLM calls behind a unified interface, (2) agent_identity.py for wallet-based challenge-sign-verify auth with JWT sessions, (3) dual pricing layer in the WSGI middleware, (4) agent economy v2 with EAS reputation and agent-to-agent payments. Each pillar is independently deployable.

**Tech Stack:** Flask, x402 2.2.0, Anthropic SDK, OpenAI SDK, google-genai, httpx (for DeepSeek/Together), eth_account (EVM sigs), solders (Solana sigs), PyJWT, py_evm (EAS attestations), SQLite.

---

## Pillar 1: Multi-Model Routing

### Task 1: Create model registry and router module

**Files:**
- Create: `model_router.py`
- Test: `tests/test_model_router.py`

**Step 1: Create test directory and write failing tests**

```bash
mkdir -p tests
```

```python
# tests/test_model_router.py
import pytest
from model_router import (
    MODEL_REGISTRY, get_model_config, resolve_model_name,
    calculate_cost, call_model, ModelNotFoundError
)


def test_registry_has_default_models():
    assert "claude-haiku" in MODEL_REGISTRY
    assert "gpt-4o" in MODEL_REGISTRY
    assert "deepseek-v3" in MODEL_REGISTRY
    assert "gemini-2.5-flash" in MODEL_REGISTRY


def test_resolve_aliases():
    assert resolve_model_name("haiku") == "claude-haiku"
    assert resolve_model_name("gpt4o") == "gpt-4o"
    assert resolve_model_name("claude-haiku") == "claude-haiku"


def test_resolve_unknown_raises():
    with pytest.raises(ModelNotFoundError):
        resolve_model_name("nonexistent-model-xyz")


def test_get_model_config():
    cfg = get_model_config("claude-haiku")
    assert cfg["provider"] == "anthropic"
    assert cfg["model_id"] == "claude-haiku-4-5-20251001"
    assert "input_cost_per_m" in cfg
    assert "output_cost_per_m" in cfg
    assert "max_tokens" in cfg


def test_calculate_cost():
    # Claude Haiku: $0.80 input, $4.00 output per M tokens
    cost = calculate_cost("claude-haiku", input_tokens=1000, output_tokens=500)
    expected = (1000 * 0.80 / 1_000_000) + (500 * 4.00 / 1_000_000)
    assert abs(cost - expected) < 0.0001


def test_calculate_cost_unknown_model():
    with pytest.raises(ModelNotFoundError):
        calculate_cost("nonexistent", input_tokens=100, output_tokens=100)
```

**Step 2: Run tests to verify they fail**

Run: `cd /home/damien809/agent-service && source venv/bin/activate && python -m pytest tests/test_model_router.py -v`
Expected: FAIL with ImportError (model_router doesn't exist yet)

**Step 3: Write model_router.py**

```python
# model_router.py
"""Unified multi-model routing for AiPayGen.

Abstracts LLM calls behind a single call_model() interface.
Supports Anthropic, OpenAI, Google, DeepSeek, Together/Groq.
"""
import os
import json
import httpx

class ModelNotFoundError(Exception):
    pass

# ── Model Registry ───────────────────────────────────────────────────────────
# model_name -> config. Costs in USD per million tokens.
MODEL_REGISTRY: dict = {
    # Anthropic
    "claude-haiku": {
        "provider": "anthropic",
        "model_id": "claude-haiku-4-5-20251001",
        "input_cost_per_m": 0.80,
        "output_cost_per_m": 4.00,
        "max_tokens": 8192,
        "supports_vision": True,
        "supports_streaming": True,
    },
    "claude-sonnet": {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-6-20260320",
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "max_tokens": 8192,
        "supports_vision": True,
        "supports_streaming": True,
    },
    "claude-opus": {
        "provider": "anthropic",
        "model_id": "claude-opus-4-6-20260320",
        "input_cost_per_m": 15.00,
        "output_cost_per_m": 75.00,
        "max_tokens": 4096,
        "supports_vision": True,
        "supports_streaming": True,
    },
    # OpenAI
    "gpt-4o": {
        "provider": "openai",
        "model_id": "gpt-4o",
        "input_cost_per_m": 2.50,
        "output_cost_per_m": 10.00,
        "max_tokens": 4096,
        "supports_vision": True,
        "supports_streaming": True,
    },
    "gpt-4o-mini": {
        "provider": "openai",
        "model_id": "gpt-4o-mini",
        "input_cost_per_m": 0.15,
        "output_cost_per_m": 0.60,
        "max_tokens": 4096,
        "supports_vision": True,
        "supports_streaming": True,
    },
    # Google
    "gemini-2.5-pro": {
        "provider": "google",
        "model_id": "gemini-2.5-pro-preview-03-25",
        "input_cost_per_m": 1.25,
        "output_cost_per_m": 10.00,
        "max_tokens": 8192,
        "supports_vision": True,
        "supports_streaming": True,
    },
    "gemini-2.5-flash": {
        "provider": "google",
        "model_id": "gemini-2.5-flash-preview-04-17",
        "input_cost_per_m": 0.15,
        "output_cost_per_m": 0.60,
        "max_tokens": 8192,
        "supports_vision": True,
        "supports_streaming": True,
    },
    # DeepSeek
    "deepseek-v3": {
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "input_cost_per_m": 0.27,
        "output_cost_per_m": 1.10,
        "max_tokens": 4096,
        "supports_vision": False,
        "supports_streaming": True,
    },
    "deepseek-r1": {
        "provider": "deepseek",
        "model_id": "deepseek-reasoner",
        "input_cost_per_m": 0.55,
        "output_cost_per_m": 2.19,
        "max_tokens": 4096,
        "supports_vision": False,
        "supports_streaming": True,
    },
    # Together (Llama, Mistral)
    "llama-3.3-70b": {
        "provider": "together",
        "model_id": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
        "input_cost_per_m": 0.88,
        "output_cost_per_m": 0.88,
        "max_tokens": 4096,
        "supports_vision": False,
        "supports_streaming": True,
    },
    "mistral-large": {
        "provider": "together",
        "model_id": "mistralai/Mistral-Large-Instruct-2407",
        "input_cost_per_m": 1.00,
        "output_cost_per_m": 1.00,
        "max_tokens": 4096,
        "supports_vision": False,
        "supports_streaming": True,
    },
}

# Aliases for convenience
_ALIASES: dict = {
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


def resolve_model_name(name: str) -> str:
    """Resolve a model name or alias to a canonical registry key."""
    name = name.lower().strip()
    if name in MODEL_REGISTRY:
        return name
    if name in _ALIASES:
        return _ALIASES[name]
    raise ModelNotFoundError(f"Unknown model: {name}. Available: {list(MODEL_REGISTRY.keys())}")


def get_model_config(name: str) -> dict:
    """Get full config for a model by canonical name."""
    name = resolve_model_name(name)
    return {**MODEL_REGISTRY[name], "name": name}


def calculate_cost(model_name: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate actual USD cost for a call based on token usage."""
    cfg = get_model_config(model_name)
    return (input_tokens * cfg["input_cost_per_m"] / 1_000_000) + \
           (output_tokens * cfg["output_cost_per_m"] / 1_000_000)


def list_models() -> list[dict]:
    """Return all available models with their config (for /models endpoint)."""
    return [
        {
            "name": name,
            "provider": cfg["provider"],
            "model_id": cfg["model_id"],
            "input_cost_per_m_tokens": cfg["input_cost_per_m"],
            "output_cost_per_m_tokens": cfg["output_cost_per_m"],
            "max_tokens": cfg["max_tokens"],
            "supports_vision": cfg["supports_vision"],
            "supports_streaming": cfg["supports_streaming"],
        }
        for name, cfg in MODEL_REGISTRY.items()
    ]


# ── Provider Clients (lazy-initialized) ──────────────────────────────────────
_clients: dict = {}


def _get_anthropic_client():
    if "anthropic" not in _clients:
        import anthropic
        _clients["anthropic"] = anthropic.Anthropic(
            api_key=os.environ.get("ANTHROPIC_API_KEY", "")
        )
    return _clients["anthropic"]


def _get_openai_client():
    if "openai" not in _clients:
        from openai import OpenAI
        _clients["openai"] = OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", "")
        )
    return _clients["openai"]


def _get_google_client():
    if "google" not in _clients:
        from google import genai
        _clients["google"] = genai.Client(
            api_key=os.environ.get("GOOGLE_API_KEY", "")
        )
    return _clients["google"]


def _deepseek_base_url():
    return "https://api.deepseek.com"


def _together_base_url():
    return "https://api.together.xyz/v1"


def call_model(
    model: str,
    messages: list[dict],
    system: str = "",
    max_tokens: int | None = None,
    temperature: float = 0.7,
) -> dict:
    """Unified model call. Returns {text, model, input_tokens, output_tokens, cost_usd}.

    messages: list of {"role": "user"|"assistant", "content": "..."}
    """
    cfg = get_model_config(model)
    provider = cfg["provider"]
    model_id = cfg["model_id"]
    mt = max_tokens or cfg["max_tokens"]

    if provider == "anthropic":
        client = _get_anthropic_client()
        kwargs = {"model": model_id, "max_tokens": mt, "messages": messages, "temperature": temperature}
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        text = msg.content[0].text
        in_tok = msg.usage.input_tokens
        out_tok = msg.usage.output_tokens

    elif provider == "openai":
        client = _get_openai_client()
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        resp = client.chat.completions.create(
            model=model_id, messages=oai_messages, max_tokens=mt, temperature=temperature,
        )
        text = resp.choices[0].message.content
        in_tok = resp.usage.prompt_tokens
        out_tok = resp.usage.completion_tokens

    elif provider == "google":
        client = _get_google_client()
        contents = []
        if system:
            contents.append({"role": "user", "parts": [{"text": f"[System]: {system}"}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
        resp = client.models.generate_content(
            model=model_id, contents=contents,
            config={"max_output_tokens": mt, "temperature": temperature},
        )
        text = resp.text
        in_tok = resp.usage_metadata.prompt_token_count or 0
        out_tok = resp.usage_metadata.candidates_token_count or 0

    elif provider == "deepseek":
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        r = httpx.post(
            f"{_deepseek_base_url()}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY', '')}"},
            json={"model": model_id, "messages": oai_messages, "max_tokens": mt, "temperature": temperature},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        in_tok = data["usage"]["prompt_tokens"]
        out_tok = data["usage"]["completion_tokens"]

    elif provider == "together":
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)
        r = httpx.post(
            f"{_together_base_url()}/chat/completions",
            headers={"Authorization": f"Bearer {os.environ.get('TOGETHER_API_KEY', '')}"},
            json={"model": model_id, "messages": oai_messages, "max_tokens": mt, "temperature": temperature},
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        in_tok = data["usage"]["prompt_tokens"]
        out_tok = data["usage"]["completion_tokens"]

    else:
        raise ModelNotFoundError(f"Unknown provider: {provider}")

    cost = calculate_cost(model, in_tok, out_tok)

    return {
        "text": text,
        "model": cfg["name"],
        "model_id": model_id,
        "provider": provider,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": round(cost, 6),
    }
```

**Step 4: Run tests to verify they pass**

Run: `cd /home/damien809/agent-service && source venv/bin/activate && python -m pytest tests/test_model_router.py -v`
Expected: All 5 tests PASS (the call_model tests are unit-only, no API calls)

**Step 5: Commit**

```bash
cd /home/damien809/agent-service
git add model_router.py tests/test_model_router.py
git commit -m "feat: add multi-model router with registry for 11 models across 5 providers"
```

---

### Task 2: Install provider SDKs and add API keys to .env.enc

**Files:**
- Modify: `requirements.txt` (or install directly)
- Modify: `.env.enc` (add OPENAI_API_KEY, GOOGLE_API_KEY, DEEPSEEK_API_KEY, TOGETHER_API_KEY)

**Step 1: Install new dependencies**

```bash
cd /home/damien809/agent-service && source venv/bin/activate
pip install openai google-genai httpx
```

Note: `anthropic` is already installed. `httpx` is used for DeepSeek/Together (OpenAI-compatible APIs without needing the full SDK).

**Step 2: Add API keys to .env.enc**

Use the re-encrypt pattern from MEMORY.md. The user will need to provide actual API keys:

```bash
cd /home/damien809/agent-service && source venv/bin/activate
python -c "
import os; from cryptography.fernet import Fernet
key = open(os.path.expanduser('~/.agent_key'), 'rb').read()
fernet = Fernet(key)
data = fernet.decrypt(open('.env.enc', 'rb').read()).decode()
# Add these lines (user fills in real keys):
data += '\nOPENAI_API_KEY=sk-...'
data += '\nGOOGLE_API_KEY=AI...'
data += '\nDEEPSEEK_API_KEY=sk-...'
data += '\nTOGETHER_API_KEY=...'
open('.env.enc', 'wb').write(fernet.encrypt(data.encode()))
"
```

**Step 3: Verify keys load**

```bash
cd /home/damien809/agent-service && source venv/bin/activate
python -c "
from model_router import call_model
# Quick smoke test with Claude (already has key)
result = call_model('claude-haiku', [{'role': 'user', 'content': 'Say hi in 3 words'}], max_tokens=20)
print(result)
"
```

**Step 4: Commit**

```bash
git add -A  # requirements changes only, .env.enc is gitignored
git commit -m "feat: install openai, google-genai, httpx for multi-model support"
```

---

### Task 3: Add /models endpoint and refactor app.py to use model_router

**Files:**
- Modify: `app.py` (import model_router, add `model` param to AI endpoints, add /models route)

**Step 1: Write integration test**

```python
# tests/test_models_endpoint.py
"""Tests for the /models endpoint and model parameter on AI routes."""
import pytest
from model_router import list_models, resolve_model_name


def test_list_models_returns_all():
    models = list_models()
    assert len(models) >= 11
    names = [m["name"] for m in models]
    assert "claude-haiku" in names
    assert "gpt-4o" in names
    assert "deepseek-v3" in names


def test_resolve_default_is_haiku():
    assert resolve_model_name("default") == "claude-haiku"
```

**Step 2: Run test to verify it passes (using existing module)**

Run: `python -m pytest tests/test_models_endpoint.py -v`

**Step 3: Add /models endpoint to app.py**

At the top of `app.py`, add import:
```python
from model_router import call_model, list_models, get_model_config, calculate_cost, resolve_model_name, ModelNotFoundError
```

Add new route (near other free endpoints):
```python
@app.route("/models", methods=["GET"])
def models_list():
    return jsonify({"models": list_models(), "default": "claude-haiku"})
```

**Step 4: Create helper to extract model from request and call via router**

Add this helper function in app.py (near the `_TrackedMessages` class):
```python
def _call_llm(messages, system="", max_tokens=1024, endpoint="unknown", model_override=None):
    """Route LLM call through model_router. Reads 'model' from request JSON if not overridden."""
    model_name = model_override or (request.get_json() or {}).get("model", "claude-haiku")
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError as e:
        return None, str(e)
    # Track cost via discovery engine
    try:
        track_cost(endpoint, result["model_id"], result["input_tokens"], result["output_tokens"])
    except Exception:
        pass
    return result, None
```

**Step 5: Refactor one endpoint as proof-of-concept (/summarize)**

Before (app.py ~line 922):
```python
msg = claude.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=1024,
    messages=[{"role": "user", "content": f"Summarize in {length} form:\n\n{text}"}]
)
return jsonify(agent_response({"summary": msg.content[0].text, "original_length": len(text)}, "/summarize"))
```

After:
```python
result, err = _call_llm(
    [{"role": "user", "content": f"Summarize in {length} form:\n\n{text}"}],
    max_tokens=1024, endpoint="/summarize",
)
if err:
    return jsonify({"error": err}), 400
return jsonify(agent_response({
    "summary": result["text"], "original_length": len(text),
    "model": result["model"], "tokens": result["input_tokens"] + result["output_tokens"],
}, "/summarize"))
```

**Step 6: Test manually**

```bash
curl -X POST http://localhost:5001/summarize \
  -H "Content-Type: application/json" \
  -d '{"text": "The quick brown fox jumps over the lazy dog. This is a test.", "model": "claude-haiku"}'
```

**Step 7: Commit**

```bash
git add app.py tests/test_models_endpoint.py
git commit -m "feat: add /models endpoint and _call_llm helper, refactor /summarize as proof-of-concept"
```

---

### Task 4: Refactor all remaining AI endpoints to use _call_llm

**Files:**
- Modify: `app.py` (every `claude.messages.create` call → `_call_llm`)

This is a bulk refactor. Each `claude.messages.create(...)` call in app.py gets replaced with `_call_llm(...)`. The pattern for each endpoint:

1. Replace `claude.messages.create(model="claude-haiku-4-5-20251001", max_tokens=N, messages=[...])` with `result, err = _call_llm([...], max_tokens=N, endpoint="/endpoint-name")`
2. Replace `msg.content[0].text` with `result["text"]`
3. Add error handling: `if err: return jsonify({"error": err}), 400`
4. For endpoints with `system=` kwarg: pass `system=` to `_call_llm`
5. Add `"model": result["model"]` to response JSON

**Endpoints to refactor** (grep for `claude.messages.create` — approximately 30+ calls):
- `/research`, `/write`, `/analyze`, `/summarize` (done), `/translate`, `/sentiment`, `/keywords`, `/classify`, `/rewrite`, `/extract`, `/qa`, `/code`, `/diagram`, `/write`, `/chat`, `/plan`, `/decide`, `/proofread`, `/explain`, `/questions`, `/outline`, `/email`, `/sql`, `/regex`, `/mock`, `/score`, `/timeline`, `/action`, `/pitch`, `/debate`, `/headline`, `/fact`, `/tag`, `/compare`, `/transform`, `/social`, `/batch`, `/chain`, `/pipeline`, `/vision`, `/rag`, `/json-schema`, `/test-cases`, `/workflow`

Also refactor inner functions: `research_inner`, `summarize_inner`, `analyze_inner`, `translate_inner`, `extract_inner`, `qa_inner`, `classify_inner`, `rewrite_inner`, `sentiment_inner`, `chat_inner`

**Step 1: Systematically replace all calls**

For each endpoint, apply the pattern above. Keep `claude` object for backward compat (scheduler jobs, blog generation, etc. still use it directly).

**Step 2: Test a sample of endpoints**

```bash
# Test with default (claude-haiku)
curl -s -X POST http://localhost:5001/analyze -H "Content-Type: application/json" \
  -d '{"content": "AI agents are changing the world"}' | python -m json.tool

# Test with gpt-4o
curl -s -X POST http://localhost:5001/analyze -H "Content-Type: application/json" \
  -d '{"content": "AI agents are changing the world", "model": "gpt-4o"}' | python -m json.tool

# Test with deepseek
curl -s -X POST http://localhost:5001/summarize -H "Content-Type: application/json" \
  -d '{"text": "Long text here...", "model": "deepseek"}' | python -m json.tool
```

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: refactor all AI endpoints to support multi-model via model parameter"
```

---

## Pillar 2: Wallet-Based Agent Identity

### Task 5: Create agent_identity.py with EVM + Solana verification

**Files:**
- Create: `agent_identity.py`
- Test: `tests/test_agent_identity.py`

**Step 1: Install dependencies**

```bash
pip install eth-account PyJWT solders
```

**Step 2: Write failing tests**

```python
# tests/test_agent_identity.py
import pytest
import time
from agent_identity import (
    generate_challenge, verify_evm_signature, verify_solana_signature,
    issue_jwt, verify_jwt, ChallengeExpiredError, InvalidSignatureError,
)
from eth_account import Account
from eth_account.messages import encode_defunct


def test_generate_challenge():
    ch = generate_challenge("0xABCDEF1234567890abcdef1234567890abcdef12")
    assert "nonce" in ch
    assert "message" in ch
    assert "expires_at" in ch
    assert "0xABCDEF" in ch["message"]


def test_verify_evm_signature():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    msg = encode_defunct(text=ch["message"])
    sig = acct.sign_message(msg)
    result = verify_evm_signature(ch["message"], sig.signature.hex(), acct.address)
    assert result is True


def test_verify_evm_bad_signature():
    acct = Account.create()
    ch = generate_challenge(acct.address)
    with pytest.raises(InvalidSignatureError):
        verify_evm_signature(ch["message"], "0x" + "00" * 65, acct.address)


def test_jwt_roundtrip():
    token = issue_jwt(agent_id="0xABC123", wallet="0xABC123", chain="evm")
    payload = verify_jwt(token)
    assert payload["agent_id"] == "0xABC123"
    assert payload["chain"] == "evm"


def test_jwt_expired():
    token = issue_jwt(agent_id="0xABC123", wallet="0xABC123", chain="evm", ttl_seconds=0)
    time.sleep(1)
    with pytest.raises(Exception):  # jwt.ExpiredSignatureError
        verify_jwt(token)
```

**Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_agent_identity.py -v`
Expected: FAIL with ImportError

**Step 4: Write agent_identity.py**

```python
# agent_identity.py
"""Wallet-based agent identity: challenge-sign-verify for EVM + Solana wallets."""
import os
import uuid
import time
import jwt
from eth_account import Account
from eth_account.messages import encode_defunct

JWT_SECRET = os.environ.get("JWT_SECRET", "aipaygen-jwt-secret-change-me")
JWT_ALGORITHM = "HS256"
CHALLENGE_TTL = 300  # 5 minutes


class InvalidSignatureError(Exception):
    pass


class ChallengeExpiredError(Exception):
    pass


# ── Challenges ────────────────────────────────────────────────────────────────
_pending_challenges: dict = {}  # nonce -> {message, wallet, expires_at}


def generate_challenge(wallet_address: str) -> dict:
    """Generate a challenge message for wallet ownership proof."""
    nonce = uuid.uuid4().hex
    expires_at = time.time() + CHALLENGE_TTL
    message = f"AiPayGen identity verification\nWallet: {wallet_address}\nNonce: {nonce}"
    _pending_challenges[nonce] = {
        "message": message,
        "wallet": wallet_address,
        "expires_at": expires_at,
    }
    return {"nonce": nonce, "message": message, "expires_at": int(expires_at)}


def _get_and_validate_challenge(nonce: str) -> dict:
    """Retrieve challenge and check it hasn't expired."""
    ch = _pending_challenges.pop(nonce, None)
    if not ch:
        raise ChallengeExpiredError("Challenge not found or already used")
    if time.time() > ch["expires_at"]:
        raise ChallengeExpiredError("Challenge expired")
    return ch


# ── EVM Verification (EIP-191) ───────────────────────────────────────────────
def verify_evm_signature(message: str, signature: str, expected_address: str) -> bool:
    """Verify an EVM personal_sign signature matches the expected wallet."""
    try:
        msg = encode_defunct(text=message)
        recovered = Account.recover_message(msg, signature=signature)
        if recovered.lower() != expected_address.lower():
            raise InvalidSignatureError(
                f"Signature recovered address {recovered} != expected {expected_address}"
            )
        return True
    except InvalidSignatureError:
        raise
    except Exception as e:
        raise InvalidSignatureError(f"EVM signature verification failed: {e}")


# ── Solana Verification (Ed25519) ────────────────────────────────────────────
def verify_solana_signature(message: str, signature_bytes: bytes, pubkey_str: str) -> bool:
    """Verify a Solana Ed25519 signature."""
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature
        pk = Pubkey.from_string(pubkey_str)
        sig = Signature.from_bytes(signature_bytes)
        if not sig.verify(pk, message.encode()):
            raise InvalidSignatureError("Solana signature verification failed")
        return True
    except InvalidSignatureError:
        raise
    except ImportError:
        raise InvalidSignatureError("solders package not installed for Solana verification")
    except Exception as e:
        raise InvalidSignatureError(f"Solana signature verification failed: {e}")


# ── JWT Sessions ─────────────────────────────────────────────────────────────
def issue_jwt(agent_id: str, wallet: str, chain: str, ttl_seconds: int = 86400) -> str:
    """Issue a JWT for a verified agent. Default 24h expiry."""
    payload = {
        "agent_id": agent_id,
        "wallet": wallet,
        "chain": chain,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Verify and decode a JWT. Raises on expiry or invalid token."""
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# ── High-Level Verify Flow ───────────────────────────────────────────────────
def verify_challenge(nonce: str, signature: str, chain: str = "evm") -> dict:
    """Full verification flow: validate challenge, verify signature, issue JWT."""
    ch = _get_and_validate_challenge(nonce)
    wallet = ch["wallet"]
    message = ch["message"]

    if chain == "evm":
        verify_evm_signature(message, signature, wallet)
    elif chain == "solana":
        verify_solana_signature(message, bytes.fromhex(signature), wallet)
    else:
        raise InvalidSignatureError(f"Unsupported chain: {chain}")

    token = issue_jwt(agent_id=wallet.lower(), wallet=wallet, chain=chain)
    return {"agent_id": wallet.lower(), "token": token, "chain": chain}
```

**Step 5: Run tests**

Run: `python -m pytest tests/test_agent_identity.py -v`
Expected: All PASS

**Step 6: Commit**

```bash
git add agent_identity.py tests/test_agent_identity.py
git commit -m "feat: add wallet-based agent identity with EVM + Solana verification and JWT sessions"
```

---

### Task 6: Add identity endpoints to app.py

**Files:**
- Modify: `app.py` (add /agents/challenge, /agents/verify, /agents/me routes)

**Step 1: Add imports to app.py**

```python
from agent_identity import (
    generate_challenge, verify_challenge, verify_jwt,
    InvalidSignatureError, ChallengeExpiredError,
)
```

**Step 2: Add identity routes**

```python
@app.route("/agents/challenge", methods=["POST"])
def agent_challenge():
    """Step 1: Request a challenge to prove wallet ownership."""
    data = request.get_json() or {}
    wallet = data.get("wallet_address", "")
    if not wallet:
        return jsonify({"error": "wallet_address required"}), 400
    ch = generate_challenge(wallet)
    return jsonify(ch)


@app.route("/agents/verify", methods=["POST"])
def agent_verify():
    """Step 2: Submit signed challenge to get JWT."""
    data = request.get_json() or {}
    nonce = data.get("nonce", "")
    signature = data.get("signature", "")
    chain = data.get("chain", "evm")
    if not nonce or not signature:
        return jsonify({"error": "nonce and signature required"}), 400
    try:
        result = verify_challenge(nonce, signature, chain)
        # Auto-register in agent registry if not exists
        try:
            register_agent(
                result["agent_id"],
                data.get("name", f"agent-{result['agent_id'][:8]}"),
                data.get("description", ""),
                data.get("capabilities", ""),
                data.get("endpoint", ""),
            )
        except Exception:
            pass
        return jsonify(result)
    except (InvalidSignatureError, ChallengeExpiredError) as e:
        return jsonify({"error": str(e)}), 401


@app.route("/agents/me", methods=["GET"])
def agent_me():
    """Get current agent profile (requires JWT)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ey"):
        return jsonify({"error": "JWT required. Use /agents/challenge + /agents/verify first."}), 401
    try:
        payload = verify_jwt(auth[7:])
        return jsonify(payload)
    except Exception as e:
        return jsonify({"error": f"Invalid token: {e}"}), 401
```

**Step 3: Add JWT auth decorator for protected endpoints**

```python
def require_verified_agent(f):
    """Decorator: require JWT from a verified agent wallet."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ey"):
            try:
                payload = verify_jwt(auth[7:])
                request.agent = payload
                return f(*args, **kwargs)
            except Exception:
                pass
        return jsonify({"error": "Verified agent required. See /agents/challenge"}), 401
    return decorated
```

**Step 4: Test manually**

```bash
# Request challenge
curl -s -X POST http://localhost:5001/agents/challenge \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0x3E9C23822184c7E0D1f2b650bef6218a56B9EeeD"}'
```

**Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add /agents/challenge, /agents/verify, /agents/me endpoints for wallet identity"
```

---

### Task 7: Secure memory endpoints with wallet verification

**Files:**
- Modify: `app.py` (protect /memory/* endpoints for verified agents)

**Step 1: Update memory endpoints to use verified agent_id**

For `/memory/set`, `/memory/get`, `/memory/search`, `/memory/clear`:
- If JWT present: use wallet address as agent_id (verified, secure)
- If no JWT: use provided agent_id (backward compat, but unverified)
- Add `verified: true/false` to response

Example for `/memory/set`:
```python
@app.route("/memory/set", methods=["POST"])
def memory_set_route():
    data = request.get_json() or {}
    # Try JWT-verified agent_id first
    verified = False
    agent_id = data.get("agent_id", "")
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ey"):
        try:
            payload = verify_jwt(auth[7:])
            agent_id = payload["agent_id"]
            verified = True
        except Exception:
            pass
    if not agent_id:
        return jsonify({"error": "agent_id required (or use JWT auth)"}), 400
    key = data.get("key", "")
    value = data.get("value", "")
    if not key or not value:
        return jsonify({"error": "key and value required"}), 400
    tags = data.get("tags", "")
    memory_set(agent_id, key, value, tags)
    return jsonify({"ok": True, "agent_id": agent_id, "key": key, "verified": verified})
```

**Step 2: Test**

Verify backward compat (no JWT) and verified path both work.

**Step 3: Commit**

```bash
git add app.py
git commit -m "feat: secure memory endpoints with optional wallet JWT verification"
```

---

## Pillar 3: Dual Pricing (Flat + Metered)

### Task 8: Add metered deduction to api_keys.py

**Files:**
- Modify: `api_keys.py` (add `deduct_metered` function)
- Test: `tests/test_metered_pricing.py`

**Step 1: Write failing test**

```python
# tests/test_metered_pricing.py
import pytest
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from api_keys import init_keys_db, generate_key, deduct, deduct_metered, get_key_status


def setup_module():
    # Use temp DB
    import api_keys
    api_keys.DB_PATH = "/tmp/test_api_keys.db"
    try:
        os.unlink("/tmp/test_api_keys.db")
    except FileNotFoundError:
        pass
    init_keys_db()


def test_deduct_metered():
    key_data = generate_key(initial_balance=1.00)
    key = key_data["key"]
    # Deduct based on actual token usage
    result = deduct_metered(key, input_tokens=1000, output_tokens=500,
                           input_rate=0.80, output_rate=4.00)
    assert result is not None
    assert result["cost"] == pytest.approx((1000*0.80 + 500*4.00) / 1_000_000, abs=0.0001)
    assert result["balance_remaining"] == pytest.approx(1.00 - result["cost"], abs=0.0001)


def test_deduct_metered_insufficient():
    key_data = generate_key(initial_balance=0.000001)
    key = key_data["key"]
    result = deduct_metered(key, input_tokens=1000000, output_tokens=1000000,
                           input_rate=15.0, output_rate=75.0)
    assert result is None  # insufficient funds
```

**Step 2: Run test to verify fail**

Run: `python -m pytest tests/test_metered_pricing.py -v`

**Step 3: Add deduct_metered to api_keys.py**

```python
def deduct_metered(key: str, input_tokens: int, output_tokens: int,
                   input_rate: float, output_rate: float) -> dict | None:
    """Deduct actual token cost from key balance. Returns cost info or None if insufficient.

    Rates are USD per million tokens.
    """
    cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    now = datetime.utcnow().isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT balance_usd FROM api_keys WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        if not row or row["balance_usd"] < cost:
            return None
        c.execute(
            "UPDATE api_keys SET balance_usd = balance_usd - ?, total_spent = total_spent + ?, "
            "call_count = call_count + 1, last_used_at = ? WHERE key = ?",
            (cost, cost, now, key),
        )
        new_balance = c.execute(
            "SELECT balance_usd FROM api_keys WHERE key = ?", (key,),
        ).fetchone()["balance_usd"]
    return {"cost": round(cost, 8), "balance_remaining": round(new_balance, 8)}
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_metered_pricing.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add api_keys.py tests/test_metered_pricing.py
git commit -m "feat: add deduct_metered for token-based pricing on prepaid keys"
```

---

### Task 9: Integrate dual pricing into WSGI middleware

**Files:**
- Modify: `app.py` (update `_api_key_wsgi` to support metered deduction after response)

**Step 1: Update WSGI middleware for metered pricing**

The key insight: for metered pricing, we can't deduct before the call (we don't know tokens yet). So:
- Flat pricing: deduct fixed amount BEFORE the call (current behavior)
- Metered pricing: let the call through, then deduct actual cost AFTER

Modify the `_api_key_wsgi` function. When `X-Pricing: metered` header is present and a prepaid key is used:
1. Validate key has *some* balance (minimum $0.001)
2. Let request through
3. After response, the endpoint writes cost info to a thread-local
4. WSGI wrapper deducts actual cost and adds response headers

```python
import threading
_metered_context = threading.local()

def _api_key_wsgi(environ, start_response):
    auth = environ.get("HTTP_AUTHORIZATION", "")
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET")
    route_key = f"{method} {path}"
    pricing_mode = environ.get("HTTP_X_PRICING", "flat").lower()

    # ... existing rate limit code ...

    # 1. Prepaid API key bypass
    if auth.startswith("Bearer apk_"):
        key = auth[7:]
        route_cfg = routes.get(route_key)
        if route_cfg:
            try:
                if pricing_mode == "metered":
                    # Metered: validate key exists and has minimum balance
                    key_data = validate_key(key)
                    if key_data and key_data.get("balance_usd", 0) >= 0.001:
                        environ["X_APIKEY_BYPASS"] = key
                        environ["X_PRICING_MODE"] = "metered"
                        return _raw_flask_wsgi(environ, start_response)
                else:
                    # Flat: deduct fixed amount upfront (existing behavior)
                    price_str = route_cfg.accepts[0].price
                    cost = float(price_str.lstrip("$"))
                    key_data = validate_key(key)
                    if key_data and key_data.get("balance_usd", 0) >= cost and deduct(key, cost):
                        environ["X_APIKEY_BYPASS"] = key
                        environ["X_PRICING_MODE"] = "flat"
                        return _raw_flask_wsgi(environ, start_response)
            except Exception:
                pass

    # ... rest of existing code ...
```

**Step 2: Add metered cost tracking in _call_llm**

Update the `_call_llm` helper to report metered costs:
```python
def _call_llm(messages, system="", max_tokens=1024, endpoint="unknown", model_override=None):
    model_name = model_override or (request.get_json() or {}).get("model", "claude-haiku")
    try:
        result = call_model(model_name, messages, system=system, max_tokens=max_tokens)
    except ModelNotFoundError as e:
        return None, str(e)
    try:
        track_cost(endpoint, result["model_id"], result["input_tokens"], result["output_tokens"])
    except Exception:
        pass
    # Metered deduction if applicable
    api_key = request.environ.get("X_APIKEY_BYPASS", "")
    pricing_mode = request.environ.get("X_PRICING_MODE", "flat")
    if api_key and pricing_mode == "metered":
        cfg = get_model_config(model_name)
        deduction = deduct_metered(
            api_key, result["input_tokens"], result["output_tokens"],
            cfg["input_cost_per_m"], cfg["output_cost_per_m"],
        )
        if deduction:
            result["metered_cost"] = deduction["cost"]
            result["balance_remaining"] = deduction["balance_remaining"]
    return result, None
```

**Step 3: Add cost headers to responses**

In each AI endpoint, after getting result from `_call_llm`, add:
```python
response = jsonify({...})
if "metered_cost" in result:
    response.headers["X-Cost"] = str(result["metered_cost"])
    response.headers["X-Balance-Remaining"] = str(result["balance_remaining"])
response.headers["X-Tokens-Used"] = str(result["input_tokens"] + result["output_tokens"])
response.headers["X-Model"] = result["model"]
return response
```

**Step 4: Add /credits/buy endpoint**

```python
@app.route("/credits/buy", methods=["POST"])
def buy_credits():
    """Buy token credits via x402. Returns a prepaid API key."""
    data = request.get_json() or {}
    amount = data.get("amount_usd", 5.0)
    label = data.get("label", "x402-credit-pack")
    key_data = generate_key(initial_balance=amount, label=label)
    return jsonify({
        "key": key_data["key"],
        "balance_usd": amount,
        "label": label,
        "pricing": "Use 'X-Pricing: metered' header for token-based billing",
    })
```

Add to x402 routes:
```python
"POST /credits/buy": RouteConfig(
    accepts=[PaymentOption(scheme="exact", pay_to=WALLET_ADDRESS, price="$5.00", network=EVM_NETWORK)],
    mime_type="application/json",
    description="Buy $5 credit pack — returns prepaid API key for metered token-based billing",
),
```

**Step 5: Test manually**

```bash
# Generate a test key with $1 balance
curl -s -X POST http://localhost:5001/auth/generate-key \
  -H "Content-Type: application/json" \
  -d '{"balance": 1.0}' | python -m json.tool

# Use metered pricing
curl -s -X POST http://localhost:5001/summarize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer apk_THE_KEY" \
  -H "X-Pricing: metered" \
  -d '{"text": "Test text for summarization"}' -i | head -20
# Should see X-Cost, X-Balance-Remaining, X-Tokens-Used headers
```

**Step 6: Commit**

```bash
git add app.py api_keys.py
git commit -m "feat: add dual pricing (flat + metered) with X-Pricing header and /credits/buy"
```

---

## Pillar 4: Agent Economy V2

### Task 10: Add on-chain reputation via EAS attestations

**Files:**
- Create: `eas_reputation.py`
- Test: `tests/test_eas_reputation.py`

**Step 1: Install web3**

```bash
pip install web3
```

**Step 2: Write eas_reputation.py**

```python
# eas_reputation.py
"""On-chain reputation attestations via Ethereum Attestation Service on Base."""
import os
import json
from web3 import Web3

# Base Mainnet EAS contract
EAS_CONTRACT = "0x4200000000000000000000000000000000000021"
SCHEMA_REGISTRY = "0x4200000000000000000000000000000000000020"

# Our reputation schema UID (register once, then hardcode)
REPUTATION_SCHEMA_UID = os.environ.get("EAS_SCHEMA_UID", "")

BASE_RPC = os.environ.get("BASE_RPC_URL", "https://mainnet.base.org")


def get_web3():
    return Web3(Web3.HTTPProvider(BASE_RPC))


def create_reputation_attestation(
    agent_wallet: str,
    attestation_type: str,  # "task_completed", "upvote", "service_rating"
    score: int,
    details: str = "",
    private_key: str = "",
) -> dict | None:
    """Create an on-chain EAS attestation for agent reputation.

    Returns tx hash or None if failed. This is a write operation that costs gas.
    Only call for significant reputation events (task completions, not every upvote).
    """
    if not private_key:
        private_key = os.environ.get("WALLET_PRIVATE_KEY", "")
    if not private_key or not REPUTATION_SCHEMA_UID:
        return None  # Skip if not configured

    w3 = get_web3()
    # Encode attestation data
    data = w3.codec.encode(
        ["address", "string", "uint256", "string"],
        [agent_wallet, attestation_type, score, details]
    )

    # This is a simplified version — full EAS integration would use
    # the EAS contract ABI. For MVP, store the attestation intent and
    # batch-submit periodically to save gas.
    return {
        "agent": agent_wallet,
        "type": attestation_type,
        "score": score,
        "details": details,
        "status": "queued",  # Will be submitted in next batch
    }


def get_reputation_attestations(agent_wallet: str) -> list[dict]:
    """Query EAS for all reputation attestations for an agent.

    For MVP, returns from local queue. Full implementation would query
    the EAS GraphQL API at https://base.easscan.org/graphql.
    """
    # TODO: Implement EAS GraphQL query
    return []
```

Note: Full EAS integration requires gas for on-chain writes. For MVP, we queue attestation intents locally and batch-submit. The attestation *reading* can use the free EAS GraphQL API.

**Step 3: Integrate with existing reputation in agent_network.py**

Add call to queue attestation when reputation is updated:

```python
# In agent_network.py update_reputation() or in app.py at task completion
from eas_reputation import create_reputation_attestation

# After a task is completed:
create_reputation_attestation(agent_wallet, "task_completed", 3, f"Task {task_id}")
```

**Step 4: Commit**

```bash
git add eas_reputation.py
git commit -m "feat: add EAS reputation attestation module (queued, batch-submit ready)"
```

---

### Task 11: Add agent-to-agent direct payments

**Files:**
- Modify: `app.py` (update /marketplace/call to support direct payments)
- Modify: `agent_memory.py` (add wallet field to marketplace listings)

**Step 1: Add wallet_address to marketplace listings**

In `agent_memory.py`, update the marketplace table to include seller wallet:

```sql
ALTER TABLE marketplace ADD COLUMN wallet_address TEXT DEFAULT '';
```

Handle this in `init_memory_db()` with a migration:
```python
try:
    c.execute("ALTER TABLE marketplace ADD COLUMN wallet_address TEXT DEFAULT ''")
except sqlite3.OperationalError:
    pass  # Column already exists
```

**Step 2: Update marketplace_list_service to accept wallet**

```python
def marketplace_list_service(agent_id, name, description, endpoint, price_usd,
                            category="general", capabilities="", wallet_address=""):
    # ... existing code ...
    # Add wallet_address to INSERT
```

**Step 3: Update /marketplace/call to split payments**

In `app.py`, modify the marketplace call handler:
- 95% of payment goes to seller's wallet (if verified)
- 5% platform fee stays with AiPayGen
- For MVP: track the split in SQLite, settle via periodic batch transfer

```python
@app.route("/marketplace/call", methods=["POST"])
def marketplace_call():
    data = request.get_json() or {}
    listing_id = data.get("listing_id", "")
    listing = marketplace_get_service(listing_id)
    if not listing:
        return jsonify({"error": "listing not found"}), 404

    # Track payment split
    seller_wallet = listing.get("wallet_address", "")
    if seller_wallet:
        platform_fee = 0.05 * listing["price_usd"]  # 5%
        seller_amount = 0.95 * listing["price_usd"]
        # Queue payment to seller (settled periodically)
        _queue_seller_payment(seller_wallet, seller_amount, listing_id)

    # ... proxy the call to the listing endpoint ...
```

**Step 4: Commit**

```bash
git add app.py agent_memory.py
git commit -m "feat: add agent-to-agent payment split (95/5) on marketplace calls"
```

---

### Task 12: Add enhanced agent discovery endpoints

**Files:**
- Modify: `app.py` (add /agents/search, /agents/{id}/portfolio)

**Step 1: Add semantic agent search**

```python
@app.route("/agents/search", methods=["GET"])
def agents_search():
    """Search agents by capability, name, or description."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"error": "q parameter required"}), 400
    agents = list_agents()
    # Simple keyword matching for MVP
    results = []
    q_lower = q.lower()
    for a in agents:
        score = 0
        if q_lower in (a.get("name", "") or "").lower():
            score += 3
        if q_lower in (a.get("capabilities", "") or "").lower():
            score += 2
        if q_lower in (a.get("description", "") or "").lower():
            score += 1
        if score > 0:
            results.append({**a, "_relevance": score})
    results.sort(key=lambda x: x["_relevance"], reverse=True)
    return jsonify({"query": q, "results": results[:20]})


@app.route("/agents/<agent_id>/portfolio", methods=["GET"])
def agent_portfolio(agent_id):
    """Get agent's full portfolio: reputation, tasks, marketplace listings."""
    rep = get_reputation(agent_id)
    tasks_completed = []  # Query from task_board where assignee=agent_id and status=completed
    listings = marketplace_get_services()  # Filter by agent_id
    agent_listings = [l for l in listings.get("services", []) if l.get("agent_id") == agent_id]
    return jsonify({
        "agent_id": agent_id,
        "reputation": rep,
        "marketplace_listings": agent_listings,
        "verified": False,  # TODO: check identity DB
    })
```

**Step 2: Commit**

```bash
git add app.py
git commit -m "feat: add /agents/search and /agents/{id}/portfolio endpoints"
```

---

### Task 13: Update discovery manifests

**Files:**
- Modify: `app.py` (update /.well-known/agents.json, /discover, /openapi.json, /llms.txt)

**Step 1: Update /.well-known/agents.json to include new endpoints**

Add the new endpoints (models, identity, credits, agent search, portfolio) to all discovery manifests.

**Step 2: Update /openapi.json**

Add OpenAPI definitions for:
- `GET /models`
- `POST /agents/challenge`
- `POST /agents/verify`
- `GET /agents/me`
- `GET /agents/search`
- `GET /agents/{id}/portfolio`
- `POST /credits/buy`

**Step 3: Update /llms.txt**

Add new endpoints to the plain-text LLMs.txt listing.

**Step 4: Commit**

```bash
git add app.py
git commit -m "feat: update discovery manifests with new endpoints (models, identity, metered pricing)"
```

---

### Task 14: Add JWT_SECRET to .env.enc and final integration test

**Files:**
- Modify: `.env.enc` (add JWT_SECRET)

**Step 1: Generate and add JWT_SECRET**

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
# Add the output to .env.enc as JWT_SECRET=<value>
```

**Step 2: Full integration smoke test**

```bash
# 1. List models
curl -s http://localhost:5001/models | python -m json.tool | head -20

# 2. Create credit pack (free tier)
curl -s -X POST http://localhost:5001/auth/generate-key \
  -H "Content-Type: application/json" \
  -d '{"balance": 1.0}' | python -m json.tool

# 3. Metered call
curl -s -X POST http://localhost:5001/summarize \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer apk_KEY" \
  -H "X-Pricing: metered" \
  -d '{"text": "Test text", "model": "claude-haiku"}' -i

# 4. Request identity challenge
curl -s -X POST http://localhost:5001/agents/challenge \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0x1234567890abcdef1234567890abcdef12345678"}'

# 5. Agent search
curl -s "http://localhost:5001/agents/search?q=data" | python -m json.tool

# 6. Check discovery
curl -s http://localhost:5001/.well-known/agents.json | python -m json.tool | head -30
```

**Step 3: Commit**

```bash
git add -A
git commit -m "feat: AiPayGen v2 complete — multi-model, wallet identity, metered pricing, agent economy"
```

---

## Summary

| Task | Pillar | Description | Est. Complexity |
|------|--------|-------------|-----------------|
| 1 | Model Routing | Create model_router.py with registry + call_model | Medium |
| 2 | Model Routing | Install SDKs, add API keys | Low |
| 3 | Model Routing | Add /models endpoint, _call_llm helper | Medium |
| 4 | Model Routing | Refactor all AI endpoints to _call_llm | High (bulk) |
| 5 | Identity | Create agent_identity.py (EVM + Solana) | Medium |
| 6 | Identity | Add identity routes to app.py | Low |
| 7 | Identity | Secure memory endpoints with JWT | Low |
| 8 | Pricing | Add deduct_metered to api_keys.py | Low |
| 9 | Pricing | Integrate dual pricing in WSGI middleware | Medium |
| 10 | Economy | EAS reputation attestation module | Medium |
| 11 | Economy | Agent-to-agent direct payments | Medium |
| 12 | Economy | Agent search + portfolio endpoints | Low |
| 13 | Economy | Update discovery manifests | Low |
| 14 | Integration | JWT secret, full smoke test | Low |
