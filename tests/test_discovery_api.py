"""Tests for x402 discovery API endpoints."""
import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch


@pytest.fixture(scope="module")
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_discover_returns_categories(client):
    """GET /discover returns meta.py format (meta_bp shadows discovery_bp)."""
    r = client.get("/discover", headers={"Accept": "application/json"})
    assert r.status_code == 200
    data = r.get_json()
    assert "meta" in data
    assert "payment" in data
    assert "categories" in data
    assert "links" in data
    assert "categories" in data["meta"]
    assert data["meta"]["name"] == "AiPayGen"
    # Payment section has recommended, x402, mcp
    assert "recommended" in data["payment"]
    assert "x402" in data["payment"]


def test_discover_pricing(client):
    r = client.get("/discover/pricing")
    assert r.status_code == 200
    data = r.get_json()
    assert "total_endpoints" in data
    assert "min_price_usd" in data
    assert "max_price_usd" in data
    assert "avg_price_usd" in data
    assert "histogram" in data
    assert data["total_endpoints"] > 0
    assert data["min_price_usd"] > 0


def test_sell_estimate_post(client):
    r = client.post("/sell/estimate",
                    json={"price_per_call": 0.01, "daily_calls": 5000})
    assert r.status_code == 200
    data = r.get_json()
    assert "revenue" in data
    assert data["revenue"]["daily_net_usd"] > 0
    assert data["revenue"]["monthly_net_usd"] > 0
    # Verify 3% fee
    gross = 0.01 * 5000
    net = gross * 0.97
    assert abs(data["revenue"]["daily_net_usd"] - net) < 0.01


def test_sell_estimate_get(client):
    r = client.get("/sell/estimate?price_per_call=0.005&daily_calls=1000")
    assert r.status_code == 200
    data = r.get_json()
    assert "revenue" in data


def test_wallet_analytics_requires_id(client):
    r = client.get("/wallet/analytics")
    assert r.status_code == 400


def test_wallet_analytics_unknown_wallet(client):
    r = client.get("/wallet/analytics?wallet_id=nonexistent_wallet_xyz")
    assert r.status_code == 200
    data = r.get_json()
    assert data["total_transactions"] == 0


def test_discover_openapi(client):
    r = client.get("/discover/openapi")
    assert r.status_code == 200
    data = r.get_json()
    assert data["openapi"] == "3.1.0"
    assert "paths" in data
    assert len(data["paths"]) > 0
    assert "x-402" in data
    assert data["x-402"]["currency"] == "USDC"


def test_well_known_x402(client):
    r = client.get("/.well-known/x402")
    assert r.status_code == 200
    data = r.get_json()
    assert data["protocol"] == "x402"
    assert "chains" in data
    assert data["chains"][0]["network"] == "eip155:8453"
    assert "wallet" in data
    assert "facilitator" in data
    assert "discovery_endpoints" in data
    assert "seller_marketplace" in data
    assert "buyer" in data


def test_discover_compare(client):
    r = client.get("/discover/compare")
    assert r.status_code == 200
    data = r.get_json()
    assert "comparison" in data
    assert len(data["comparison"]) >= 2
    our = data["comparison"][0]
    assert our["platform"] == "AiPayGen"
    assert our["protocol"] == "x402"
