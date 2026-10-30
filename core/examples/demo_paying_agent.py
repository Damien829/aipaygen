#!/usr/bin/env python3
"""
AiPayGen Demo — Paying Agent (x402 Automatic Crypto Payments)

This script demonstrates how an AI agent can call AiPayGen's x402-gated
APIs and pay automatically with USDC on Base (L2).

Prerequisites:
    pip install x402 eth-account requests

Usage:
    export AGENT_PRIVATE_KEY="0xYOUR_PRIVATE_KEY_HERE"
    export AIPAYGEN_API_URL="https://api.aipaygen.com"  # optional
    python demo_paying_agent.py

The agent's wallet needs USDC on Base (chain 8453). Even a few dollars
is enough to run dozens of API calls at micro-payment prices.
"""

import json
import os
import sys

import requests
from eth_account import Account
from x402.clients.requests import wrapRequestsWithPayment
from x402.crypto.ethereum import EthAccountSigner
from x402.x402_client import x402ClientSync, register_exact_evm_client

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

API_BASE = os.environ.get("AIPAYGEN_API_URL", "https://api.aipaygen.com")
PRIVATE_KEY = os.environ.get("AGENT_PRIVATE_KEY", "")

if not PRIVATE_KEY:
    print("ERROR: Set AGENT_PRIVATE_KEY environment variable.")
    print("       export AGENT_PRIVATE_KEY=\"0x...\"")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Session setup
# ---------------------------------------------------------------------------

def setup_x402_session() -> requests.Session:
    """Create a requests session that auto-pays x402 invoices with USDC."""
    account = Account.from_key(PRIVATE_KEY)
    signer = EthAccountSigner(account)
    client = x402ClientSync(signer)
    register_exact_evm_client(client, chain_id=8453)  # Base Mainnet

    session = wrapRequestsWithPayment(requests.Session(), client)

    print("=" * 60)
    print("  AiPayGen Demo — Paying Agent")
    print("=" * 60)
    print(f"  Wallet : {account.address}")
    print(f"  API    : {API_BASE}")
    print(f"  Chain  : Base (8453) — USDC")
    print("=" * 60)
    print()

    return session


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

def call_api(session, endpoint, data, label=""):
    """
    POST to an AiPayGen endpoint. Returns (result_dict, cost_str).

    Prints status, cost, and a preview of the response.
    """
    url = f"{API_BASE}{endpoint}"
    tag = label or endpoint

    print(f"--- {tag} ---")
    print(f"  POST {url}")

    try:
        resp = session.post(url, json=data, timeout=60)
    except Exception as exc:
        print(f"  ERROR: {exc}")
        return None, "0"

    cost = resp.headers.get("X-Payment-Amount", "0")

    if resp.status_code == 200:
        result = resp.json()
        preview = json.dumps(result, indent=2)[:300]
        print(f"  Status : 200 OK")
        print(f"  Cost   : {cost} USDC")
        print(f"  Result : {preview}")
        if len(json.dumps(result, indent=2)) > 300:
            print("  ... (truncated)")
        print()
        return result, cost

    elif resp.status_code == 402:
        print(f"  Status : 402 Payment Required")
        print(f"  Detail : {resp.text[:200]}")
        print("  (The x402 client should handle this automatically.)")
        print()
        return None, "0"

    else:
        print(f"  Status : {resp.status_code}")
        print(f"  Body   : {resp.text[:200]}")
        print()
        return None, "0"


# ---------------------------------------------------------------------------
# Demo 1 — Individual API calls
# ---------------------------------------------------------------------------

def demo_single_calls(session):
    """Call three different endpoints and track total cost."""
    print()
    print("=" * 60)
    print("  DEMO 1 — Single API Calls")
    print("=" * 60)
    print()

    total = 0.0

    # 1. Research
    result, cost = call_api(session, "/research", {
        "topic": "x402 payment protocol adoption 2026",
        "depth": "medium",
    }, label="Research")
    total += float(cost)

    # 2. Summarize
    text = ""
    if result and "result" in result:
        text = result["result"] if isinstance(result["result"], str) else json.dumps(result["result"])
    if not text:
        text = "x402 is a payment protocol that enables machine-to-machine payments."

    result, cost = call_api(session, "/summarize", {
        "text": text,
        "format": "bullet_points",
    }, label="Summarize")
    total += float(cost)

    # 3. Translate
    summary = ""
    if result and "result" in result:
        summary = result["result"] if isinstance(result["result"], str) else json.dumps(result["result"])
    if not summary:
        summary = "x402 enables automatic micropayments for AI agents."

    result, cost = call_api(session, "/translate", {
        "text": summary,
        "target": "French",
    }, label="Translate")
    total += float(cost)

    print(f"  Total cost for single calls: {total:.6f} USDC")
    print()
    return total


# ---------------------------------------------------------------------------
# Demo 2 — Chained workflow (15% discount)
# ---------------------------------------------------------------------------

def demo_workflow(session):
    """Run a multi-step workflow — research, summarize, translate — in one call."""
    print()
    print("=" * 60)
    print("  DEMO 2 — Chained Workflow (15% discount)")
    print("=" * 60)
    print()

    result, cost = call_api(session, "/workflow/run", {
        "steps": [
            {
                "tool": "research",
                "input": {"topic": "x402 payment protocol adoption 2026", "depth": "medium"},
            },
            {
                "tool": "summarize",
                "input": {"format": "bullet_points"},
                "use_previous": True,
            },
            {
                "tool": "translate",
                "input": {"target": "French"},
                "use_previous": True,
            },
        ]
    }, label="Workflow (research -> summarize -> translate)")

    total = float(cost)
    print(f"  Total cost for workflow: {total:.6f} USDC")
    print("  (Workflows get a 15% volume discount vs individual calls)")
    print()
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    session = setup_x402_session()

    cost_single = demo_single_calls(session)
    cost_workflow = demo_workflow(session)

    grand_total = cost_single + cost_workflow

    print("=" * 60)
    print(f"  Grand total: {grand_total:.6f} USDC")
    print("=" * 60)
    print()
    print("Done. Your agent just paid for AI services with crypto.")


if __name__ == "__main__":
    main()
