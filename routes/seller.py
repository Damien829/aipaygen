"""Blueprint for the API Seller Marketplace."""

import json
import os
import threading
import uuid
from datetime import datetime

import requests as _requests
import stripe
from flask import Blueprint, request, jsonify, render_template

from api_keys import validate_key
from helpers import log_payment, agent_response, require_api_key
from security import validate_url, SSRFError
from seller_marketplace import (
    register_seller_api, get_seller_api, list_seller_apis,
    update_seller_api, delete_seller_api, verify_seller_endpoint,
    get_seller_dashboard, match_route, process_payment, resolve_escrow,
    create_agent_wallet, get_agent_wallet, fund_agent_wallet,
    update_wallet_policy, get_wallet_transactions, list_agent_wallets,
    request_withdrawal,
)

seller_bp = Blueprint("seller", __name__)

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")

OUR_WALLET = os.getenv("WALLET_ADDRESS", "0x366D488a48de1B2773F3a21F1A6972715056Cb30")
PROXY_TIMEOUT = 30


def init_seller_bp():
    """Called from app.py to initialize."""
    pass  # No global state needed


# ── Seller Onboarding Page ────────────────────────────────────────────────────


@seller_bp.route("/sell", methods=["GET"])
def sell_page():
    """Visual seller onboarding page."""
    return render_template("seller.html")


# ── Auth helper ───────────────────────────────────────────────────────────────

def _require_api_key():
    """Extract and validate API key. Returns (api_key, key_data) or raises."""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not api_key.startswith("apk_"):
        return None, None
    key_data = validate_key(api_key)
    if not key_data:
        return api_key, None
    return api_key, key_data


def _auth_or_401():
    """Return (api_key, key_data) or abort with 401 response."""
    api_key, key_data = _require_api_key()
    if not api_key or not api_key.startswith("apk_"):
        return None, None, (jsonify({"error": "API key required (Bearer apk_xxx)"}), 401)
    if not key_data:
        return None, None, (jsonify({"error": "Invalid API key"}), 401)
    return api_key, key_data, None


# ── Seller Management ─────────────────────────────────────────────────────────


@seller_bp.route("/sell/register", methods=["POST"])
def sell_register():
    """Register a new seller API."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}
    for field in ("name", "slug", "base_url"):
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    # Validate base_url against SSRF
    try:
        validate_url(data["base_url"], allow_http=False)
    except SSRFError as e:
        return jsonify({"error": f"Blocked base_url: {e}"}), 403

    result = register_seller_api(
        seller_id=api_key,
        name=data["name"],
        slug=data["slug"],
        description=data.get("description", ""),
        base_url=data["base_url"],
        routes=data.get("routes", []),
        seller_wallet=data.get("seller_wallet", ""),
        preferred_chain=data.get("preferred_chain", "base"),
        category=data.get("category", "general"),
        escrow_enabled=bool(data.get("escrow_enabled", False)),
    )

    # Background verification
    if result and result.get("slug"):
        t = threading.Thread(
            target=verify_seller_endpoint,
            args=(result["slug"],),
            daemon=True,
        )
        t.start()

    log_payment("/sell/register", 0.0, request.remote_addr)
    return jsonify(agent_response(result, "/sell/register")), 201


@seller_bp.route("/sell/directory", methods=["GET"])
def sell_directory():
    """Browse all seller APIs."""
    category = request.args.get("category")
    page = int(request.args.get("page", 1))
    per_page = min(int(request.args.get("per_page", 20)), 100)

    apis, total = list_seller_apis(category=category, page=page, per_page=per_page)

    return jsonify({
        "apis": apis,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "_meta": {
            "endpoint": "/sell/directory",
            "ts": datetime.utcnow().isoformat() + "Z",
            "hint": "Use ANY /sell/<slug>/<path> to call a seller API",
        },
    })


@seller_bp.route("/sell/<slug>/docs", methods=["GET"])
def sell_docs(slug):
    """Auto-generate OpenAPI-style docs for a seller's API."""
    api = get_seller_api(slug)
    if not api:
        return jsonify({"error": "seller API not found"}), 404

    routes = api.get("routes", [])
    if isinstance(routes, str):
        try:
            routes = json.loads(routes)
        except (json.JSONDecodeError, TypeError):
            routes = []

    paths = {}
    for r in routes:
        path = r.get("path", "/")
        method = r.get("method", "GET").lower()
        price = r.get("price_usd", 0)
        desc = r.get("description", "")
        curl_example = (
            f'curl -X {method.upper()} "https://api.aipaygen.com/sell/{slug}{path}" '
            f'-H "X-Wallet-ID: <your-wallet-id>"'
        )
        paths[path] = paths.get(path, {})
        paths[path][method] = {
            "description": desc,
            "price_usd": price,
            "example_curl": curl_example,
        }

    doc = {
        "name": api.get("name"),
        "slug": slug,
        "description": api.get("description", ""),
        "base_proxy_url": f"https://api.aipaygen.com/sell/{slug}",
        "category": api.get("category", "general"),
        "escrow_enabled": api.get("escrow_enabled", False),
        "paths": paths,
        "_meta": {"generated_at": datetime.utcnow().isoformat() + "Z"},
    }
    return jsonify(doc)


@seller_bp.route("/sell/dashboard", methods=["GET"])
def sell_dashboard():
    """Seller analytics dashboard."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    dashboard = get_seller_dashboard(seller_id=api_key)
    return jsonify(agent_response(dashboard, "/sell/dashboard"))


@seller_bp.route("/sell/withdraw", methods=["POST"])
def sell_withdraw():
    """Request withdrawal of seller earnings."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}
    amount_usd = data.get("amount_usd")  # None means withdraw all

    result = request_withdrawal(seller_id=api_key, amount_usd=amount_usd)
    return jsonify(agent_response(result, "/sell/withdraw"))


@seller_bp.route("/sell/<api_id>", methods=["PATCH"])
def sell_update(api_id):
    """Update a seller API."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}

    # Validate base_url if being updated
    if data.get("base_url"):
        try:
            validate_url(data["base_url"], allow_http=False)
        except SSRFError as e:
            return jsonify({"error": f"Blocked base_url: {e}"}), 403

    result = update_seller_api(api_id=api_id, seller_id=api_key, updates=data)
    if not result:
        return jsonify({"error": "seller API not found or unauthorized"}), 404

    return jsonify(agent_response(result, f"/sell/{api_id}"))


@seller_bp.route("/sell/<api_id>", methods=["DELETE"])
def sell_delete(api_id):
    """Delete a seller API."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    result = delete_seller_api(api_id=api_id, seller_id=api_key)
    if not result:
        return jsonify({"error": "seller API not found or unauthorized"}), 404

    return jsonify(agent_response(result, f"/sell/{api_id}"))


# ── Proxied API Calls ─────────────────────────────────────────────────────────


@seller_bp.route("/sell/<slug>/<path:subpath>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def sell_proxy(slug, subpath):
    """Proxy a request to a seller's API with x402 payment."""
    # 1. Look up seller API
    api = get_seller_api(slug)
    if not api:
        return jsonify({"error": "seller API not found"}), 404

    if not api.get("is_active"):
        return jsonify({"error": "seller API is inactive"}), 410

    # 2. Match route to get price
    method = request.method
    matched = match_route(api, method, f"/{subpath}")
    if not matched:
        return jsonify({"error": "route not found", "hint": f"GET /sell/{slug}/docs for available routes"}), 404

    price_usd = matched.get("price_usd", 0)

    # 3. Check for agent wallet
    wallet_id = request.headers.get("X-Wallet-ID") or request.args.get("wallet_id")

    if not wallet_id:
        # Return 402 with payment info
        return jsonify({
            "error": "payment_required",
            "price_usd": price_usd,
            "pay_to": OUR_WALLET,
            "chain": api.get("preferred_chain", "base"),
            "currency": "USDC",
            "hint": "Create a wallet via POST /wallet/create, fund it, then pass X-Wallet-ID header",
            "docs": f"https://api.aipaygen.com/sell/{slug}/docs",
        }), 402

    # 4. Get wallet and check balance + policy enforcement
    wallet = get_agent_wallet(wallet_id)
    if not wallet:
        return jsonify({"error": "wallet not found"}), 404

    # Vendor allowlist enforcement (get_agent_wallet already returns a parsed list)
    allowlist = wallet.get("vendor_allowlist", [])
    if isinstance(allowlist, str):
        logger.warning("vendor_allowlist returned as string for wallet %s, expected list", wallet.get("id"))
        allowlist = []
    if allowlist and "*" not in allowlist and slug not in allowlist:
        return jsonify({
            "error": "vendor_blocked",
            "message": f"Seller '{slug}' not in wallet vendor allowlist",
            "allowlist": allowlist,
            "hint": "Update allowlist via PATCH /wallet/policy",
        }), 403

    # Daily budget enforcement
    daily_budget = wallet.get("daily_budget", 10.0)
    spent_today = wallet.get("spent_today", 0.0)
    if spent_today + price_usd > daily_budget:
        return jsonify({
            "error": "daily_budget_exceeded",
            "daily_budget_usd": daily_budget,
            "spent_today_usd": spent_today,
            "price_usd": price_usd,
            "hint": "Increase daily budget via PATCH /wallet/policy or wait until tomorrow",
        }), 403

    if wallet.get("balance_usd", 0) < price_usd:
        return jsonify({
            "error": "insufficient_balance",
            "balance_usd": wallet.get("balance_usd", 0),
            "price_usd": price_usd,
            "hint": "Fund your wallet via POST /wallet/fund",
        }), 402

    # 5. Process payment
    escrow_enabled = api.get("escrow_enabled", False)
    payment = process_payment(
        agent_wallet_id=wallet_id,
        seller_slug=slug,
        route_path=f"/{subpath}",
        amount_usd=price_usd,
        escrow=escrow_enabled,
    )

    if not payment or payment.get("error"):
        return jsonify({"error": payment.get("error", "payment_failed")}), 402

    # 6. Proxy the request to seller
    seller_url = api["base_url"].rstrip("/") + "/" + subpath.lstrip("/")

    # SSRF protection
    try:
        validate_url(seller_url, allow_http=False)
    except SSRFError as e:
        # Refund if escrow
        if escrow_enabled and payment.get("escrow_id"):
            resolve_escrow(payment["escrow_id"], action="refund")
        return jsonify({"error": f"Blocked URL: {e}"}), 403

    try:
        # Forward query params (excluding wallet_id)
        params = {k: v for k, v in request.args.items() if k != "wallet_id"}

        # Forward request body
        proxy_kwargs = {
            "method": method,
            "url": seller_url,
            "params": params,
            "timeout": PROXY_TIMEOUT,
            "headers": {"User-Agent": "AiPayGen-Seller-Proxy/1.0"},
        }

        if method in ("POST", "PUT", "PATCH"):
            content_type = request.content_type or ""
            if "application/json" in content_type:
                proxy_kwargs["json"] = request.get_json(silent=True)
            else:
                proxy_kwargs["data"] = request.get_data()

        resp = _requests.request(**proxy_kwargs)

        # Escrow resolution
        if escrow_enabled and payment.get("escrow_id"):
            if 200 <= resp.status_code < 300:
                resolve_escrow(payment["escrow_id"], action="release")
            elif resp.status_code >= 500:
                resolve_escrow(payment["escrow_id"], action="refund")

        # Build response
        is_json = resp.headers.get("Content-Type", "").startswith("application/json")
        if is_json:
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:5000]
        else:
            body = resp.text[:5000]

        result = {
            "status_code": resp.status_code,
            "data": body,
            "_billing": {
                "price_usd": price_usd,
                "wallet_id": wallet_id,
                "seller": slug,
                "escrow": escrow_enabled,
                "escrow_id": payment.get("escrow_id"),
                "tx_id": payment.get("tx_id"),
            },
        }

        log_payment(f"/sell/{slug}/{subpath}", price_usd, request.remote_addr)

        response = jsonify(result)
        # Forward content-type hint
        if not is_json:
            response.headers["X-Seller-Content-Type"] = resp.headers.get("Content-Type", "")
        return response, resp.status_code

    except _requests.Timeout:
        if escrow_enabled and payment.get("escrow_id"):
            resolve_escrow(payment["escrow_id"], action="refund")
        return jsonify({"error": "seller_timeout", "message": "Seller API did not respond in time"}), 504
    except Exception as e:
        if escrow_enabled and payment.get("escrow_id"):
            resolve_escrow(payment["escrow_id"], action="refund")
        return jsonify({"error": "proxy_failed", "message": str(e)}), 502


# ── Agent Wallet Endpoints ────────────────────────────────────────────────────


@seller_bp.route("/wallet/create", methods=["POST"])
def wallet_create():
    """Create an agent wallet."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}
    result = create_agent_wallet(
        owner_api_key=api_key,
        label=data.get("label", "default"),
        daily_budget=data.get("daily_budget"),
        monthly_budget=data.get("monthly_budget"),
    )

    log_payment("/wallet/create", 0.0, request.remote_addr)
    return jsonify(agent_response(result, "/wallet/create")), 201


@seller_bp.route("/wallet/balance", methods=["GET"])
def wallet_balance():
    """Get wallet balance."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err
    wallet_id = request.headers.get("X-Wallet-ID") or request.args.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "X-Wallet-ID header or wallet_id query param required"}), 400

    wallet = get_agent_wallet(wallet_id)
    if not wallet:
        return jsonify({"error": "wallet not found"}), 404
    if wallet.get("owner_api_key") != api_key:
        return jsonify({"error": "not your wallet"}), 403

    return jsonify(agent_response(wallet, "/wallet/balance"))


@seller_bp.route("/wallet/fund", methods=["POST"])
def wallet_fund():
    """Fund an agent wallet via Stripe checkout."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}
    wallet_id = data.get("wallet_id")
    amount_usd = data.get("amount_usd")

    if not wallet_id:
        return jsonify({"error": "wallet_id required"}), 400
    if not amount_usd or float(amount_usd) < 5:
        return jsonify({"error": "Minimum funding amount is $5"}), 400

    amount_usd = float(amount_usd)

    # Verify wallet belongs to caller
    wallet = get_agent_wallet(wallet_id)
    if not wallet:
        return jsonify({"error": "wallet not found"}), 404
    if wallet.get("owner_api_key") != api_key:
        return jsonify({"error": "unauthorized — wallet belongs to another key"}), 403

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": int(amount_usd * 100),
                    "product_data": {"name": f"Agent Wallet Top-up ({wallet_id})"},
                },
                "quantity": 1,
            }],
            success_url=f"https://api.aipaygen.com/wallet/funded?wallet_id={wallet_id}",
            cancel_url="https://api.aipaygen.com/sell/directory",
            metadata={"wallet_id": wallet_id, "type": "wallet_fund"},
        )
        return jsonify(agent_response({
            "checkout_url": session.url,
            "session_id": session.id,
            "amount_usd": amount_usd,
            "wallet_id": wallet_id,
        }, "/wallet/fund"))
    except Exception as e:
        return jsonify({"error": "stripe_error", "message": str(e)}), 500


@seller_bp.route("/wallet/policy", methods=["PATCH"])
def wallet_policy():
    """Update wallet budget policies."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    data = request.get_json() or {}
    wallet_id = data.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "wallet_id required"}), 400

    result = update_wallet_policy(
        wallet_id=wallet_id,
        owner_api_key=api_key,
        daily_budget=data.get("daily_budget"),
        monthly_budget=data.get("monthly_budget"),
        vendor_allowlist=data.get("vendor_allowlist"),
    )

    if not result:
        return jsonify({"error": "wallet not found or unauthorized"}), 404

    return jsonify(agent_response(result, "/wallet/policy"))


@seller_bp.route("/wallet/transactions", methods=["GET"])
def wallet_transactions():
    """Get wallet transaction history."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err
    wallet_id = request.headers.get("X-Wallet-ID") or request.args.get("wallet_id")
    if not wallet_id:
        return jsonify({"error": "X-Wallet-ID header or wallet_id query param required"}), 400

    wallet = get_agent_wallet(wallet_id)
    if not wallet:
        return jsonify({"error": "wallet not found"}), 404
    if wallet.get("owner_api_key") != api_key:
        return jsonify({"error": "not your wallet"}), 403

    transactions = get_wallet_transactions(wallet_id=wallet_id)
    return jsonify(agent_response({"wallet_id": wallet_id, "transactions": transactions}, "/wallet/transactions"))


@seller_bp.route("/wallet/list", methods=["GET"])
def wallet_list():
    """List all wallets for the authenticated user."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err

    wallets = list_agent_wallets(owner_api_key=api_key)
    return jsonify(agent_response({"wallets": wallets, "count": len(wallets)}, "/wallet/list"))


# ── Escrow ────────────────────────────────────────────────────────────────────


@seller_bp.route("/escrow/<escrow_id>", methods=["GET"])
def escrow_status(escrow_id):
    """Check escrow status."""
    api_key, key_data, err = _auth_or_401()
    if err:
        return err
    from seller_marketplace import get_escrow_hold
    hold = get_escrow_hold(escrow_id)
    if not hold:
        return jsonify({"error": "escrow not found"}), 404
    # Verify caller owns the wallet involved
    wallet = get_agent_wallet(hold.get("agent_wallet_id", ""))
    if not wallet or wallet.get("owner_api_key") != api_key:
        return jsonify({"error": "not authorized"}), 403
    return jsonify(agent_response(hold, f"/escrow/{escrow_id}"))
