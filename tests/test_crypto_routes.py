"""Tests for crypto deposit routes."""

import pytest
from unittest.mock import patch


@pytest.fixture(scope="module")
def client():
    from app import app
    from routes.crypto import crypto_bp
    from crypto_deposits import init_crypto_db

    # Register only if not already registered
    if "crypto" not in [bp.name for bp in app.iter_blueprints()]:
        init_crypto_db()
        app.register_blueprint(crypto_bp)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _generate_key(client):
    """Helper: generate an API key via the auth endpoint."""
    from api_keys import generate_key
    result = generate_key(initial_balance=0.0, label="test-crypto")
    return result["key"]


def test_crypto_deposit_info(client):
    """GET /crypto/deposit returns 200 with wallet_address and networks."""
    resp = client.get("/crypto/deposit")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "wallet_address" in data
    assert "networks" in data
    assert "base" in data["networks"]
    assert "solana" in data["networks"]
    assert "qr_code" in data


def test_crypto_deposit_post_creates_intent(client):
    """POST /crypto/deposit with valid key creates deposit intent."""
    api_key = _generate_key(client)
    resp = client.post("/crypto/deposit", json={
        "api_key": api_key,
        "network": "base",
        "amount": 5.0,
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert "deposit_address" in data
    assert "qr_code" in data
    assert data["network"] == "base"
    assert data["expected_amount"] == 5.0


def test_crypto_claim_missing_fields(client):
    """POST /crypto/claim with empty body returns 400."""
    resp = client.post("/crypto/claim", json={})
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data


@patch("routes.crypto.topup_key")
@patch("routes.crypto.verify_base_tx")
def test_crypto_claim_valid(mock_verify, mock_topup, client):
    """POST /crypto/claim with valid tx returns credited."""
    import uuid
    tx_hash = f"0x{uuid.uuid4().hex}"
    mock_verify.return_value = {
        "valid": True,
        "amount_usdc": 10.0,
        "sender": "0xSENDER",
        "recipient": "0xRECIPIENT",
        "block_number": 500,
        "confirmations": 10,
        "network": "base",
    }
    mock_topup.return_value = {"key": "test", "balance_usd": 10.0, "topped_up": 10.0}

    api_key = _generate_key(client)
    resp = client.post("/crypto/claim", json={
        "api_key": api_key,
        "tx_hash": tx_hash,
        "network": "base",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "credited"
    assert data["amount_usd"] == 10.0
    assert data["network"] == "base"
    assert data["tx_hash"] == tx_hash
    mock_verify.assert_called_once()
    mock_topup.assert_called_once()


@patch("routes.crypto.verify_base_tx")
def test_crypto_claim_invalid_tx(mock_verify, client):
    """POST /crypto/claim with invalid tx returns 400."""
    mock_verify.return_value = {
        "valid": False,
        "error": "Transaction failed (status=0)",
    }
    api_key = _generate_key(client)
    resp = client.post("/crypto/claim", json={
        "api_key": api_key,
        "tx_hash": "0xbad_tx_invalid_test",
        "network": "base",
    })
    assert resp.status_code == 400
    data = resp.get_json()
    assert "error" in data
    assert data.get("valid") is False


def test_crypto_deposits_history(client):
    """GET /crypto/deposits returns deposit list."""
    api_key = _generate_key(client)
    resp = client.get(f"/crypto/deposits?api_key={api_key}")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "deposits" in data
    assert isinstance(data["deposits"], list)


def test_crypto_landing_page(client):
    """GET /crypto returns HTML page with USDC info."""
    resp = client.get("/crypto")
    assert resp.status_code == 200
    assert b"USDC" in resp.data
