"""x402 outbound payment client — lets our agent pay other x402 services."""
import os
from datetime import datetime

MAX_SPEND_PER_CALL = float(os.getenv("X402_MAX_PER_CALL", "0.10"))
DAILY_BUDGET = float(os.getenv("X402_DAILY_BUDGET", "1.00"))

_daily_spend = {"date": "", "total": 0.0}


def _check_budget(cost: float) -> bool:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    if _daily_spend["date"] != today:
        _daily_spend["date"] = today
        _daily_spend["total"] = 0.0
    if cost > MAX_SPEND_PER_CALL:
        return False
    return _daily_spend["total"] + cost <= DAILY_BUDGET


def _record_spend(cost: float):
    _daily_spend["total"] += cost


def get_x402_session():
    """Create a requests session wrapped with x402 auto-payment. Returns (session, error)."""
    private_key = os.getenv("AGENT_PRIVATE_KEY")
    if not private_key:
        return None, "AGENT_PRIVATE_KEY not set in .env"
    try:
        import requests
        from eth_account import Account
        from x402 import x402ClientSync
        from x402.mechanisms.evm.exact import register_exact_evm_client
        from x402.mechanisms.evm.signers import EthAccountSigner
        from x402.http.clients.requests import wrapRequestsWithPayment

        account = Account.from_key(private_key)
        signer = EthAccountSigner(account)
        client = x402ClientSync()
        register_exact_evm_client(client, signer)
        session = wrapRequestsWithPayment(requests.Session(), client)
        return session, None
    except Exception as e:
        return None, str(e)


def call_x402_api(url: str, method: str = "GET", data: dict = None,
                  max_cost: float = 0.05) -> dict:
    """Call an x402-gated API with automatic payment."""
    if not _check_budget(max_cost):
        return {"error": "budget_exceeded", "daily_spend": _daily_spend["total"],
                "daily_budget": DAILY_BUDGET}

    session, err = get_x402_session()
    if not session:
        return {"error": f"x402 client unavailable: {err}"}

    try:
        if method.upper() == "POST":
            resp = session.post(url, json=data, timeout=30)
        else:
            resp = session.get(url, timeout=30)

        actual_cost = 0.0
        if resp.headers.get("X-Payment-Amount"):
            try:
                actual_cost = float(resp.headers["X-Payment-Amount"])
            except ValueError:
                pass
        _record_spend(actual_cost)

        return {
            "status": resp.status_code,
            "body": resp.text[:5000],
            "cost_usd": actual_cost,
            "daily_spend": _daily_spend["total"],
        }
    except Exception as e:
        return {"error": str(e)}


def get_spend_stats() -> dict:
    """Return current daily spend stats."""
    return {
        "date": _daily_spend["date"],
        "spent_today": _daily_spend["total"],
        "budget": DAILY_BUDGET,
        "remaining": max(0, DAILY_BUDGET - _daily_spend["total"]),
        "max_per_call": MAX_SPEND_PER_CALL,
    }
