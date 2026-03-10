"""Crypto deposit routes — deposit info, claim, history, landing page."""

import base64
import io
import json
import logging
import os
import subprocess
import threading

import qrcode
from flask import Blueprint, request, jsonify, render_template_string

from api_keys import topup_key, validate_key
from crypto_deposits import (
    CRYPTO_MIN_DEPOSIT_USD as MIN_DEPOSIT_USD,
    CRYPTO_MAX_DEPOSIT_USD as MAX_DEPOSIT_USD,
    CRYPTO_FEE_PERCENT,
    USDC_BASE,
    USDC_SOL_MINT,
    record_deposit,
    get_deposit_by_tx,
    get_deposits_for_key,
    is_tx_claimed,
    mark_deposit_credited,
    create_pending_deposit,
    get_pending_for_address,
    create_deposit_address,
    get_deposit_address,
)
from crypto_verify import verify_base_tx, verify_solana_tx
from crypto_wallet import get_main_wallet, derive_deposit_address
from helpers import check_identity_rate_limit, get_client_ip
from funnel_tracker import log_event

logger = logging.getLogger(__name__)

crypto_bp = Blueprint("crypto", __name__)

SUPPORTED_NETWORKS = {
    "base": {
        "name": "Base",
        "chain_id": 8453,
        "token": "USDC",
        "contract": USDC_BASE,
        "decimals": 6,
        "explorer": "https://basescan.org/tx/",
    },
    "solana": {
        "name": "Solana",
        "token": "USDC",
        "mint": USDC_SOL_MINT,
        "decimals": 6,
        "explorer": "https://solscan.io/tx/",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_qr_base64(data: str) -> str:
    """Generate a QR code PNG and return as base64 string."""
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")


def _notify_deposit(amount: float, network: str, api_key: str):
    """Best-effort wall notification + log."""
    masked = api_key[:8] + "..." if len(api_key) > 8 else api_key
    msg = f"Crypto deposit: ${amount:.2f} via {network} for {masked}"
    logger.info(msg)
    try:
        subprocess.run(["wall", msg], capture_output=True, timeout=5)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# GET /crypto/deposit — deposit info
# ---------------------------------------------------------------------------

@crypto_bp.route("/crypto/deposit", methods=["GET"])
def crypto_deposit_info():
    """Return wallet address, supported networks, QR code, and instructions."""
    wallet = get_main_wallet()
    qr = _generate_qr_base64(wallet)
    return jsonify({
        "wallet_address": wallet,
        "networks": SUPPORTED_NETWORKS,
        "qr_code": qr,
        "min_deposit_usd": MIN_DEPOSIT_USD,
        "max_deposit_usd": MAX_DEPOSIT_USD,
        "fee_percent": CRYPTO_FEE_PERCENT,
        "instructions": (
            "Send USDC to the wallet address above on Base (chain 8453) or Solana. "
            f"Minimum deposit: ${MIN_DEPOSIT_USD:.2f}. Maximum: ${MAX_DEPOSIT_USD:.2f}. "
            "After sending, call POST /crypto/claim with your tx_hash to credit your account."
        ),
    })


# ---------------------------------------------------------------------------
# POST /crypto/deposit — create deposit intent
# ---------------------------------------------------------------------------

@crypto_bp.route("/crypto/deposit", methods=["POST"])
def crypto_deposit_create():
    """Create a deposit intent — returns unique address, QR, instructions."""
    data = request.get_json(force=True, silent=True) or {}
    api_key = data.get("api_key", "").strip()
    network = data.get("network", "base").strip().lower()
    amount = data.get("amount")

    if not api_key:
        return jsonify({"error": "api_key required"}), 400

    key_info = validate_key(api_key)
    if not key_info:
        return jsonify({"error": "invalid or inactive api_key"}), 401

    if network not in SUPPORTED_NETWORKS:
        return jsonify({"error": f"unsupported network, choose: {list(SUPPORTED_NETWORKS.keys())}"}), 400

    if amount is not None:
        try:
            amount = float(amount)
        except (ValueError, TypeError):
            return jsonify({"error": "amount must be a number"}), 400
        if amount < MIN_DEPOSIT_USD or amount > MAX_DEPOSIT_USD:
            return jsonify({"error": f"amount must be between ${MIN_DEPOSIT_USD} and ${MAX_DEPOSIT_USD}"}), 400

    # Get or create unique deposit address
    derived = derive_deposit_address(api_key)
    deposit_addr = derived["address"]

    # Persist address mapping
    existing = get_deposit_address(api_key)
    if not existing:
        create_deposit_address(
            api_key=api_key,
            evm_address=deposit_addr,
            evm_index=derived.get("index", 0),
        )

    # Create pending deposit
    pending = create_pending_deposit(
        api_key=api_key,
        network=network,
        deposit_address=deposit_addr,
        expected_amount=amount,
    )

    qr = _generate_qr_base64(deposit_addr)

    ip = get_client_ip()
    log_event("crypto_deposit_intent", "/crypto/deposit", ip,
              json.dumps({"network": network, "amount": amount}))

    return jsonify({
        "deposit_address": deposit_addr,
        "network": network,
        "expected_amount": amount,
        "qr_code": qr,
        "min_deposit_usd": MIN_DEPOSIT_USD,
        "max_deposit_usd": MAX_DEPOSIT_USD,
        "expires_at": pending["expires_at"],
        "instructions": (
            f"Send {f'${amount:.2f} ' if amount else ''}USDC to {deposit_addr} on {network}. "
            "After confirmation, call POST /crypto/claim with your tx_hash."
        ),
    })


# ---------------------------------------------------------------------------
# POST /crypto/claim — verify tx and credit account
# ---------------------------------------------------------------------------

@crypto_bp.route("/crypto/claim", methods=["POST"])
def crypto_claim():
    """Verify an onchain tx and credit the user's balance."""
    ip = get_client_ip()
    if not check_identity_rate_limit(ip):
        return jsonify({"error": "rate limited, try again later"}), 429

    data = request.get_json(force=True, silent=True) or {}
    api_key = data.get("api_key", "").strip()
    tx_hash = data.get("tx_hash", "").strip()
    network = data.get("network", "base").strip().lower()

    if not api_key or not tx_hash:
        return jsonify({"error": "api_key and tx_hash required"}), 400

    if network not in SUPPORTED_NETWORKS:
        return jsonify({"error": f"unsupported network: {network}"}), 400

    key_info = validate_key(api_key)
    if not key_info:
        return jsonify({"error": "invalid or inactive api_key"}), 401

    # Check not already claimed
    if is_tx_claimed(tx_hash):
        return jsonify({"error": "transaction already claimed"}), 409

    # Get expected recipient
    addr_rec = get_deposit_address(api_key)
    wallet = addr_rec["evm_address"] if addr_rec else get_main_wallet()

    # Verify onchain
    if network == "base":
        result = verify_base_tx(tx_hash, wallet)
    elif network == "solana":
        result = verify_solana_tx(tx_hash, wallet)
    else:
        return jsonify({"error": "unsupported network"}), 400

    if not result.get("valid"):
        return jsonify({"error": result.get("error", "verification failed"), "valid": False}), 400

    amount_usdc = result["amount_usdc"]

    # Check min/max
    if amount_usdc < MIN_DEPOSIT_USD:
        return jsonify({"error": f"deposit below minimum (${MIN_DEPOSIT_USD})"}), 400
    if amount_usdc > MAX_DEPOSIT_USD:
        return jsonify({"error": f"deposit above maximum (${MAX_DEPOSIT_USD})"}), 400

    # Calculate fee
    fee_usd = round(amount_usdc * CRYPTO_FEE_PERCENT / 100, 6)
    credit_amount = round(amount_usdc - fee_usd, 6)

    # Record deposit
    rec = record_deposit(
        api_key=api_key,
        tx_hash=tx_hash,
        network=network,
        amount_token=amount_usdc,
        amount_usd=credit_amount,
        sender_address=result.get("sender", ""),
        deposit_address=wallet,
        block_number=result.get("block_number") or result.get("slot", 0),
        confirmations=result.get("confirmations", 0),
    )

    if rec["status"] == "already_claimed":
        return jsonify({"error": "transaction already claimed"}), 409

    # Credit balance
    topup_result = topup_key(api_key, credit_amount)

    # Mark credited
    mark_deposit_credited(tx_hash)

    # Notify
    threading.Thread(
        target=_notify_deposit, args=(credit_amount, network, api_key), daemon=True
    ).start()

    log_event("crypto_deposit_credited", "/crypto/claim", ip,
              json.dumps({"amount": credit_amount, "network": network, "tx_hash": tx_hash}))

    # Try email notification (best effort)
    try:
        from email_service import send_deposit_confirmation
        send_deposit_confirmation(api_key, credit_amount, network, tx_hash)
    except Exception:
        pass

    return jsonify({
        "status": "credited",
        "amount_usd": credit_amount,
        "fee_usd": fee_usd,
        "network": network,
        "tx_hash": tx_hash,
        "new_balance": topup_result.get("balance_usd", 0),
    })


# ---------------------------------------------------------------------------
# GET /crypto/deposits — deposit history
# ---------------------------------------------------------------------------

@crypto_bp.route("/crypto/deposits", methods=["GET"])
def crypto_deposits_history():
    """Return deposit history for an API key."""
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "api_key required"}), 400

    key_info = validate_key(api_key)
    if not key_info:
        return jsonify({"error": "invalid or inactive api_key"}), 401

    deposits = get_deposits_for_key(api_key)
    return jsonify({"deposits": deposits, "count": len(deposits)})


# ---------------------------------------------------------------------------
# GET /crypto/address — get or create deposit address
# ---------------------------------------------------------------------------

@crypto_bp.route("/crypto/address", methods=["GET"])
def crypto_address():
    """Return or create a unique deposit address for the API key."""
    api_key = request.args.get("api_key", "").strip()
    if not api_key:
        return jsonify({"error": "api_key required"}), 400

    key_info = validate_key(api_key)
    if not key_info:
        return jsonify({"error": "invalid or inactive api_key"}), 401

    existing = get_deposit_address(api_key)
    if existing:
        return jsonify({
            "deposit_address": existing["evm_address"],
            "solana_address": existing.get("solana_address"),
        })

    derived = derive_deposit_address(api_key)
    create_deposit_address(
        api_key=api_key,
        evm_address=derived["address"],
        evm_index=derived.get("index", 0),
    )
    return jsonify({
        "deposit_address": derived["address"],
        "solana_address": None,
    })


# ---------------------------------------------------------------------------
# GET /crypto — HTML landing page
# ---------------------------------------------------------------------------

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crypto Deposits — AiPayGen</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: #0a0a0a; color: #e0e0e0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; line-height: 1.6; }
  .container { max-width: 720px; margin: 0 auto; padding: 2rem 1rem; }
  h1 { color: #fff; margin-bottom: 0.5rem; }
  h2 { color: #ccc; margin: 1.5rem 0 0.5rem; font-size: 1.2rem; }
  .subtitle { color: #888; margin-bottom: 2rem; }
  .wallet-box { background: #151515; border: 1px solid #333; border-radius: 8px; padding: 1rem; margin: 1rem 0; display: flex; align-items: center; gap: 0.5rem; }
  .wallet-addr { font-family: monospace; font-size: 0.85rem; word-break: break-all; flex: 1; color: #4fc3f7; }
  .copy-btn { background: #333; color: #fff; border: none; padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer; font-size: 0.85rem; }
  .copy-btn:hover { background: #555; }
  .badge { display: inline-block; padding: 0.25rem 0.75rem; border-radius: 12px; font-size: 0.8rem; font-weight: 600; margin-right: 0.5rem; }
  .badge-base { background: #1652f0; color: #fff; }
  .badge-solana { background: #9945ff; color: #fff; }
  .qr-wrap { text-align: center; margin: 1.5rem 0; }
  .qr-wrap img { border-radius: 8px; border: 4px solid #fff; }
  .steps { list-style: none; counter-reset: step; }
  .steps li { counter-increment: step; margin: 0.75rem 0; padding-left: 2rem; position: relative; }
  .steps li::before { content: counter(step); position: absolute; left: 0; background: #333; color: #4fc3f7; width: 1.5rem; height: 1.5rem; border-radius: 50%; text-align: center; line-height: 1.5rem; font-size: 0.8rem; }
  pre { background: #151515; border: 1px solid #333; border-radius: 6px; padding: 1rem; overflow-x: auto; font-size: 0.8rem; margin: 0.5rem 0; }
  code { color: #4fc3f7; }
  .contract { font-family: monospace; font-size: 0.8rem; color: #aaa; word-break: break-all; }
  nav { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid #222; }
  nav a { color: #4fc3f7; text-decoration: none; margin-right: 1.5rem; }
  nav a:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <h1>Crypto Deposits</h1>
  <p class="subtitle">Fund your AiPayGen account with USDC — no Stripe needed.</p>

  <h2>Wallet Address</h2>
  <div class="wallet-box">
    <span class="wallet-addr" id="wallet">{{ wallet }}</span>
    <button class="copy-btn" onclick="navigator.clipboard.writeText(document.getElementById('wallet').textContent).then(()=>this.textContent='Copied!')">Copy</button>
  </div>

  <div class="qr-wrap">
    <img src="data:image/png;base64,{{ qr }}" alt="QR Code" width="200" height="200">
  </div>

  <h2>Supported Networks</h2>
  <p>
    <span class="badge badge-base">Base (Chain 8453)</span>
    <span class="badge badge-solana">Solana</span>
  </p>

  <h2>USDC Contract Addresses</h2>
  <p><strong>Base:</strong> <span class="contract">0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913</span></p>
  <p><strong>Solana Mint:</strong> <span class="contract">EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v</span></p>

  <h2>How It Works</h2>
  <ol class="steps">
    <li>Send USDC to the wallet address above on Base or Solana.</li>
    <li>Wait for transaction confirmation (5 blocks on Base).</li>
    <li>Call <code>POST /crypto/claim</code> with your <code>tx_hash</code> and <code>api_key</code>.</li>
    <li>Your account balance is credited instantly.</li>
  </ol>

  <h2>Claim Example</h2>
  <pre>curl -X POST https://api.aipaygen.com/crypto/claim \\
  -H "Content-Type: application/json" \\
  -d '{
    "api_key": "apk_YOUR_KEY",
    "tx_hash": "0xYOUR_TX_HASH",
    "network": "base"
  }'</pre>

  <nav>
    <a href="/">Home</a>
    <a href="/docs">Docs</a>
    <a href="/buy-credits">Buy Credits</a>
    <a href="/try">Try</a>
    <a href="/builder">Build Agent</a>
  </nav>
</div>
</body>
</html>"""


@crypto_bp.route("/crypto", methods=["GET"])
def crypto_landing():
    """Render the crypto deposit landing page."""
    wallet = get_main_wallet()
    qr = _generate_qr_base64(wallet)
    return render_template_string(_LANDING_HTML, wallet=wallet, qr=qr)
