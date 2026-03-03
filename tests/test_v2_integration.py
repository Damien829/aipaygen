"""Integration tests for AiPayGent v2 endpoints."""
import pytest
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from eth_account import Account
from eth_account.messages import encode_defunct


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# ── Models ────────────────────────────────────────────────────────────────────


def test_models_endpoint(client):
    r = client.get("/models")
    assert r.status_code == 200
    data = r.get_json()
    assert "models" in data
    assert len(data["models"]) >= 11
    assert data["default"] == "claude-haiku"


def test_models_have_required_fields(client):
    r = client.get("/models")
    data = r.get_json()
    for m in data["models"]:
        assert "canonical_name" in m
        assert "provider" in m


# ── Identity: /agents/challenge ───────────────────────────────────────────────


def test_challenge_returns_nonce_and_message(client):
    r = client.post("/agents/challenge", json={"wallet_address": "0xABCDEF1234567890abcdef1234567890abcdef12"})
    assert r.status_code == 200
    data = r.get_json()
    assert "nonce" in data
    assert "message" in data
    assert "expires_at" in data
    assert "0xABCDEF" in data["message"]


def test_challenge_missing_wallet(client):
    r = client.post("/agents/challenge", json={})
    assert r.status_code == 400
    assert "error" in r.get_json()


# ── Identity: /agents/verify ─────────────────────────────────────────────────


def test_verify_missing_fields(client):
    r = client.post("/agents/verify", json={})
    assert r.status_code == 400
    data = r.get_json()
    assert "error" in data


def test_verify_bad_nonce(client):
    r = client.post("/agents/verify", json={"nonce": "nonexistent", "signature": "0x" + "00" * 65})
    assert r.status_code == 401
    assert "error" in r.get_json()


# ── Identity: full EVM challenge-sign-verify flow ────────────────────────────


def test_full_evm_identity_flow(client):
    """End-to-end: challenge -> sign -> verify -> /agents/me with JWT."""
    acct = Account.create()

    # Step 1: get challenge
    r1 = client.post("/agents/challenge", json={"wallet_address": acct.address})
    assert r1.status_code == 200
    ch = r1.get_json()

    # Step 2: sign and verify
    msg = encode_defunct(text=ch["message"])
    sig = acct.sign_message(msg)
    r2 = client.post("/agents/verify", json={
        "nonce": ch["nonce"],
        "signature": sig.signature.hex(),
        "chain": "evm",
    })
    assert r2.status_code == 200
    verify_data = r2.get_json()
    assert verify_data["agent_id"] == acct.address.lower()
    assert "token" in verify_data
    assert verify_data["chain"] == "evm"

    # Step 3: use JWT on /agents/me
    token = verify_data["token"]
    r3 = client.get("/agents/me", headers={"Authorization": f"Bearer {token}"})
    assert r3.status_code == 200
    me = r3.get_json()
    assert me["agent_id"] == acct.address.lower()
    assert me["chain"] == "evm"
    assert me["wallet"] == acct.address


# ── Identity: /agents/me error cases ─────────────────────────────────────────


def test_agents_me_no_auth(client):
    r = client.get("/agents/me")
    assert r.status_code == 401
    assert "error" in r.get_json()


def test_agents_me_bad_token(client):
    r = client.get("/agents/me", headers={"Authorization": "Bearer eyINVALID.token.here"})
    assert r.status_code == 401
    assert "error" in r.get_json()


# ── Agent Search ──────────────────────────────────────────────────────────────


def test_agents_search(client):
    r = client.get("/agents/search?q=test")
    assert r.status_code == 200
    data = r.get_json()
    assert "query" in data
    assert data["query"] == "test"
    assert "results" in data
    assert isinstance(data["results"], list)


def test_agents_search_missing_q(client):
    r = client.get("/agents/search")
    assert r.status_code == 400
    assert "error" in r.get_json()


# ── Agent Portfolio ───────────────────────────────────────────────────────────


def test_agent_portfolio(client):
    r = client.get("/agents/test-agent-123/portfolio")
    assert r.status_code == 200
    data = r.get_json()
    assert data["agent_id"] == "test-agent-123"
    assert "reputation" in data
    assert "marketplace_listings" in data
    assert isinstance(data["marketplace_listings"], list)


# ── Credits / Metered Billing ─────────────────────────────────────────────────


def test_buy_credits_default(client):
    r = client.post("/credits/buy", json={})
    assert r.status_code == 200
    data = r.get_json()
    assert data["key"].startswith("apk_")
    assert data["balance_usd"] == 5.0
    assert data["label"] == "x402-credit-pack"
    assert "pricing" in data


def test_buy_credits_custom_amount(client):
    r = client.post("/credits/buy", json={"amount_usd": 10.0, "label": "my-pack"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["balance_usd"] == 10.0
    assert data["label"] == "my-pack"
    assert data["key"].startswith("apk_")
