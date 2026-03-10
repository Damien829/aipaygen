"""Seller marketplace: third-party API registration, agent wallets with budget
policies, escrow holds, and settlement. Backed by SQLite."""
import os
import re
import sqlite3
import json
import uuid
from datetime import datetime
from contextlib import contextmanager

_DB_PATH = os.path.join(os.path.dirname(__file__), "seller_marketplace.db")

PLATFORM_FEE = 0.03  # 3%

SUPPORTED_CHAINS = {"base", "solana"}
# Solana addresses are base58, 32-44 chars
_SOLANA_ADDR_RE = re.compile(r'^[1-9A-HJ-NP-Za-km-z]{32,44}$')
# EVM addresses are 0x + 40 hex chars
_EVM_ADDR_RE = re.compile(r'^0x[0-9a-fA-F]{40}$')


@contextmanager
def _conn():
    uri = _DB_PATH.startswith("file:")
    c = sqlite3.connect(_DB_PATH, uri=uri)
    c.row_factory = sqlite3.Row
    if not uri:
        c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def init_seller_db():
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS seller_apis (
            id TEXT PRIMARY KEY,
            seller_id TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            base_url TEXT NOT NULL,
            routes TEXT DEFAULT '[]',
            seller_wallet TEXT DEFAULT '',
            preferred_chain TEXT DEFAULT 'base',
            category TEXT DEFAULT 'general',
            is_verified INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            escrow_enabled INTEGER DEFAULT 0,
            total_calls INTEGER DEFAULT 0,
            total_revenue_usd REAL DEFAULT 0.0,
            balance_usd REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS agent_wallets (
            id TEXT PRIMARY KEY,
            owner_api_key TEXT NOT NULL,
            label TEXT DEFAULT '',
            balance_usd REAL DEFAULT 0.0,
            daily_budget REAL DEFAULT 10.0,
            monthly_budget REAL DEFAULT 100.0,
            spent_today REAL DEFAULT 0.0,
            spent_month REAL DEFAULT 0.0,
            last_daily_reset TEXT DEFAULT '',
            last_monthly_reset TEXT DEFAULT '',
            vendor_allowlist TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS escrow_holds (
            id TEXT PRIMARY KEY,
            agent_wallet_id TEXT NOT NULL,
            seller_api_id TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            status TEXT DEFAULT 'held',
            tx_hash TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            resolved_at TEXT DEFAULT ''
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS seller_payouts (
            id TEXT PRIMARY KEY,
            seller_id TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            chain TEXT DEFAULT 'base',
            tx_hash TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )""")

        c.execute("""CREATE TABLE IF NOT EXISTS wallet_transactions (
            id TEXT PRIMARY KEY,
            wallet_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            seller_slug TEXT DEFAULT '',
            route TEXT DEFAULT '',
            escrow_id TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )""")

        # Indexes
        c.execute("CREATE INDEX IF NOT EXISTS idx_seller_apis_seller ON seller_apis(seller_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_seller_apis_category ON seller_apis(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wallets_owner ON agent_wallets(owner_api_key)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_escrow_wallet ON escrow_holds(agent_wallet_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_escrow_status ON escrow_holds(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wtx_wallet ON wallet_transactions(wallet_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_payouts_seller ON seller_payouts(seller_id)")

    # Set DB file permissions
    try:
        os.chmod(_DB_PATH, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Seller CRUD
# ---------------------------------------------------------------------------

def register_seller_api(seller_id, slug, name, description, base_url, routes,
                        seller_wallet="", preferred_chain="base", category="general",
                        escrow_enabled=False):
    """Register a new seller API. Returns the created record."""
    slug = slug.lower().strip()
    if not re.match(r'^[a-z0-9][a-z0-9-]{1,48}[a-z0-9]$', slug):
        return {"error": "Invalid slug. Use 3-50 chars: lowercase letters, numbers, hyphens."}

    preferred_chain = preferred_chain.lower().strip()
    if preferred_chain not in SUPPORTED_CHAINS:
        return {"error": f"Unsupported chain '{preferred_chain}'. Supported: {', '.join(sorted(SUPPORTED_CHAINS))}"}

    if seller_wallet:
        if preferred_chain == "solana" and not _SOLANA_ADDR_RE.match(seller_wallet):
            return {"error": "Invalid Solana wallet address"}
        if preferred_chain == "base" and not _EVM_ADDR_RE.match(seller_wallet):
            return {"error": "Invalid Base (EVM) wallet address"}

    api_id = str(uuid.uuid4())[:12]
    now = datetime.utcnow().isoformat() + "Z"

    with _conn() as c:
        existing = c.execute("SELECT id FROM seller_apis WHERE slug=?", (slug,)).fetchone()
        if existing:
            return {"error": f"Slug '{slug}' is already taken"}

        c.execute("""INSERT INTO seller_apis
            (id, seller_id, slug, name, description, base_url, routes, seller_wallet,
             preferred_chain, category, is_verified, is_active, escrow_enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)""",
            (api_id, seller_id, slug, name[:255], description[:500], base_url,
             json.dumps(routes), seller_wallet, preferred_chain, category,
             1 if escrow_enabled else 0, now))

    return {"id": api_id, "slug": slug, "name": name, "status": "registered",
            "verify_note": "We'll ping your endpoints to verify they respond."}


def get_seller_api(slug_or_id):
    """Get a seller API by slug or ID."""
    with _conn() as c:
        row = c.execute("SELECT * FROM seller_apis WHERE slug=? OR id=?",
                        (slug_or_id, slug_or_id)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["routes"] = json.loads(d["routes"])
        return d


def list_seller_apis(category=None, page=1, per_page=20):
    """List active seller APIs."""
    with _conn() as c:
        where = "WHERE is_active=1"
        params = []
        if category:
            where += " AND category=?"
            params.append(category)

        total = c.execute(f"SELECT COUNT(*) FROM seller_apis {where}", params).fetchone()[0]
        offset = (page - 1) * per_page
        rows = c.execute(
            f"SELECT * FROM seller_apis {where} ORDER BY total_calls DESC LIMIT ? OFFSET ?",
            params + [per_page, offset]
        ).fetchall()

        apis = []
        for r in rows:
            d = dict(r)
            d["routes"] = json.loads(d["routes"])
            apis.append(d)
        return apis, total


def update_seller_api(api_id, seller_id, updates):
    """Update a seller API. Only the owner can update."""
    allowed = {"name", "description", "base_url", "routes", "seller_wallet",
               "preferred_chain", "category", "escrow_enabled", "is_active"}
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return {"error": "No valid fields to update"}

    if "preferred_chain" in filtered:
        chain = filtered["preferred_chain"].lower().strip()
        if chain not in SUPPORTED_CHAINS:
            return {"error": f"Unsupported chain '{chain}'. Supported: {', '.join(sorted(SUPPORTED_CHAINS))}"}
        filtered["preferred_chain"] = chain

    wallet = filtered.get("seller_wallet")
    chain = filtered.get("preferred_chain")
    if wallet and chain:
        if chain == "solana" and not _SOLANA_ADDR_RE.match(wallet):
            return {"error": "Invalid Solana wallet address"}
        if chain == "base" and not _EVM_ADDR_RE.match(wallet):
            return {"error": "Invalid Base (EVM) wallet address"}

    with _conn() as c:
        row = c.execute("SELECT seller_id FROM seller_apis WHERE id=?", (api_id,)).fetchone()
        if not row:
            return {"error": "API not found"}
        if row["seller_id"] != seller_id:
            return {"error": "Not authorized — you don't own this API"}

        sets = []
        params = []
        for k, v in filtered.items():
            if k == "routes":
                v = json.dumps(v)
            sets.append(f"{k}=?")
            params.append(v)
        params.append(api_id)
        c.execute(f"UPDATE seller_apis SET {', '.join(sets)} WHERE id=?", params)

    return {"updated": list(filtered.keys()), "api_id": api_id}


def delete_seller_api(api_id, seller_id):
    """Delete a seller API. Only the owner can delete."""
    with _conn() as c:
        row = c.execute("SELECT seller_id FROM seller_apis WHERE id=?", (api_id,)).fetchone()
        if not row:
            return {"error": "API not found"}
        if row["seller_id"] != seller_id:
            return {"error": "Not authorized"}
        c.execute("DELETE FROM seller_apis WHERE id=?", (api_id,))
    return {"deleted": True, "api_id": api_id}


def verify_seller_endpoint(slug):
    """Ping seller endpoints to verify they're reachable. Sets is_verified."""
    import requests
    api = get_seller_api(slug)
    if not api:
        return {"error": "API not found"}

    status_code = None
    try:
        resp = requests.get(api["base_url"], timeout=10,
                            headers={"User-Agent": "AiPayGen-Verify/1.0"})
        verified = resp.status_code < 500
        status_code = resp.status_code
    except Exception:
        verified = False

    with _conn() as c:
        c.execute("UPDATE seller_apis SET is_verified=? WHERE slug=?",
                  (1 if verified else 0, slug))

    return {"slug": slug, "verified": verified, "status_code": status_code}


def get_seller_dashboard(seller_id):
    """Get seller analytics — calls, revenue, balance, payouts."""
    with _conn() as c:
        apis = c.execute("SELECT * FROM seller_apis WHERE seller_id=?", (seller_id,)).fetchall()
        payouts = c.execute(
            "SELECT * FROM seller_payouts WHERE seller_id=? ORDER BY created_at DESC LIMIT 20",
            (seller_id,)
        ).fetchall()

    api_list = []
    total_revenue = 0
    total_balance = 0
    total_calls = 0
    for a in apis:
        d = dict(a)
        d["routes"] = json.loads(d["routes"])
        api_list.append(d)
        total_revenue += d["total_revenue_usd"]
        total_balance += d["balance_usd"]
        total_calls += d["total_calls"]

    return {
        "seller_id": seller_id,
        "apis": api_list,
        "totals": {
            "revenue_usd": round(total_revenue, 6),
            "balance_usd": round(total_balance, 6),
            "total_calls": total_calls,
        },
        "payouts": [dict(p) for p in payouts],
    }


# ---------------------------------------------------------------------------
# Route matching & pricing
# ---------------------------------------------------------------------------

def match_route(api, method, path):
    """Match an incoming request to a seller's route config. Returns route dict or None."""
    routes = api.get("routes", [])
    for route in routes:
        r_method = route.get("method", "GET").upper()
        r_path = route.get("path", "/").rstrip("/")

        # Wildcard match: /api/* matches /api/anything
        if r_path.endswith("/*"):
            prefix = r_path[:-2]
            if path.startswith(prefix) and (r_method == method or r_method == "ANY"):
                return route
        # Exact match
        if r_path == path.rstrip("/") and (r_method == method or r_method == "ANY"):
            return route

    # Default: if no routes defined, use default pricing
    if not routes:
        return {"path": "/", "method": "ANY", "price_usd": 0.005, "description": "Default pricing"}
    return None


# ---------------------------------------------------------------------------
# Payment processing
# ---------------------------------------------------------------------------

def process_payment(agent_wallet_id, seller_slug, route_path, amount_usd, escrow=False):
    """Process a payment: deduct from agent wallet, credit seller (or hold in escrow)."""
    now = datetime.utcnow().isoformat() + "Z"

    with _conn() as c:
        wallet = c.execute("SELECT * FROM agent_wallets WHERE id=?", (agent_wallet_id,)).fetchone()
        if not wallet:
            return {"error": "Wallet not found"}
        wallet = dict(wallet)

        # Reset daily/monthly if needed
        today = datetime.utcnow().strftime("%Y-%m-%d")
        month = datetime.utcnow().strftime("%Y-%m")
        if wallet["last_daily_reset"] != today:
            c.execute("UPDATE agent_wallets SET spent_today=0, last_daily_reset=? WHERE id=?",
                      (today, agent_wallet_id))
            wallet["spent_today"] = 0
        if wallet["last_monthly_reset"] != month:
            c.execute("UPDATE agent_wallets SET spent_month=0, last_monthly_reset=? WHERE id=?",
                      (month, agent_wallet_id))
            wallet["spent_month"] = 0

        # Check balance
        if wallet["balance_usd"] < amount_usd:
            return {"error": "insufficient_balance", "balance": wallet["balance_usd"], "cost": amount_usd}

        # Check daily budget
        daily_budget = wallet["daily_budget"] or 0
        if daily_budget > 0 and wallet["spent_today"] + amount_usd > daily_budget:
            return {"error": "daily_budget_exceeded", "budget": daily_budget,
                    "spent": wallet["spent_today"], "cost": amount_usd}

        # Check monthly budget
        monthly_budget = wallet["monthly_budget"] or 0
        if monthly_budget > 0 and wallet["spent_month"] + amount_usd > monthly_budget:
            return {"error": "monthly_budget_exceeded", "budget": wallet["monthly_budget"],
                    "spent": wallet["spent_month"], "cost": amount_usd}

        # Check vendor allowlist
        allowlist = json.loads(wallet["vendor_allowlist"])
        if allowlist and seller_slug not in allowlist:
            return {"error": "vendor_not_allowed", "slug": seller_slug,
                    "allowlist": allowlist}

        # Deduct from agent wallet
        c.execute("""UPDATE agent_wallets SET
            balance_usd=balance_usd-?, spent_today=spent_today+?, spent_month=spent_month+?
            WHERE id=?""", (amount_usd, amount_usd, amount_usd, agent_wallet_id))

        tx_id = str(uuid.uuid4())[:12]

        if escrow:
            escrow_id = str(uuid.uuid4())[:12]
            c.execute("""INSERT INTO escrow_holds
                (id, agent_wallet_id, seller_api_id, amount_usd, status, created_at)
                VALUES (?, ?, ?, ?, 'held', ?)""",
                (escrow_id, agent_wallet_id, seller_slug, amount_usd, now))

            c.execute("""INSERT INTO wallet_transactions
                (id, wallet_id, type, amount_usd, seller_slug, route, escrow_id, created_at)
                VALUES (?, ?, 'escrow_hold', ?, ?, ?, ?, ?)""",
                (tx_id, agent_wallet_id, amount_usd, seller_slug, route_path, escrow_id, now))

            return {"status": "escrowed", "escrow_id": escrow_id, "amount_usd": amount_usd}
        else:
            seller_amount = round(amount_usd * (1 - PLATFORM_FEE), 6)
            platform_amount = round(amount_usd * PLATFORM_FEE, 6)

            c.execute("""UPDATE seller_apis SET
                total_calls=total_calls+1, total_revenue_usd=total_revenue_usd+?,
                balance_usd=balance_usd+? WHERE slug=?""",
                (seller_amount, seller_amount, seller_slug))

            c.execute("""INSERT INTO wallet_transactions
                (id, wallet_id, type, amount_usd, seller_slug, route, created_at)
                VALUES (?, ?, 'payment', ?, ?, ?, ?)""",
                (tx_id, agent_wallet_id, amount_usd, seller_slug, route_path, now))

            return {"status": "paid", "tx_id": tx_id, "amount_usd": amount_usd,
                    "seller_received": seller_amount, "platform_fee": platform_amount}


def get_escrow_hold(escrow_id):
    """Get an escrow hold by ID."""
    with _conn() as c:
        row = c.execute("SELECT * FROM escrow_holds WHERE id=?", (escrow_id,)).fetchone()
        return dict(row) if row else None


def resolve_escrow(escrow_id, action="release"):
    """Release or refund an escrow hold. action: 'release' | 'refund'"""
    now = datetime.utcnow().isoformat() + "Z"

    with _conn() as c:
        hold = c.execute("SELECT * FROM escrow_holds WHERE id=? AND status='held'",
                         (escrow_id,)).fetchone()
        if not hold:
            return {"error": "Escrow not found or already resolved"}
        hold = dict(hold)

        if action == "release":
            seller_amount = round(hold["amount_usd"] * (1 - PLATFORM_FEE), 6)
            c.execute("""UPDATE seller_apis SET
                total_calls=total_calls+1, total_revenue_usd=total_revenue_usd+?,
                balance_usd=balance_usd+? WHERE slug=?""",
                (seller_amount, seller_amount, hold["seller_api_id"]))
            c.execute("UPDATE escrow_holds SET status='released', resolved_at=? WHERE id=?",
                      (now, escrow_id))
            return {"status": "released", "seller_received": seller_amount}

        elif action == "refund":
            c.execute("UPDATE agent_wallets SET balance_usd=balance_usd+? WHERE id=?",
                      (hold["amount_usd"], hold["agent_wallet_id"]))
            c.execute("UPDATE escrow_holds SET status='refunded', resolved_at=? WHERE id=?",
                      (now, escrow_id))

            tx_id = str(uuid.uuid4())[:12]
            c.execute("""INSERT INTO wallet_transactions
                (id, wallet_id, type, amount_usd, escrow_id, created_at)
                VALUES (?, ?, 'escrow_refund', ?, ?, ?)""",
                (tx_id, hold["agent_wallet_id"], hold["amount_usd"], escrow_id, now))

            return {"status": "refunded", "amount_usd": hold["amount_usd"]}

        return {"error": f"Unknown action: {action}"}


# ---------------------------------------------------------------------------
# Agent wallet functions
# ---------------------------------------------------------------------------

def create_agent_wallet(owner_api_key, label="", daily_budget=10.0, monthly_budget=100.0):
    """Create a new agent wallet."""
    wallet_id = "aw_" + str(uuid.uuid4())[:10]
    now = datetime.utcnow().isoformat() + "Z"
    today = datetime.utcnow().strftime("%Y-%m-%d")
    month = datetime.utcnow().strftime("%Y-%m")

    with _conn() as c:
        c.execute("""INSERT INTO agent_wallets
            (id, owner_api_key, label, balance_usd, daily_budget, monthly_budget,
             last_daily_reset, last_monthly_reset, created_at)
            VALUES (?, ?, ?, 0.0, ?, ?, ?, ?, ?)""",
            (wallet_id, owner_api_key, label[:100], daily_budget, monthly_budget, today, month, now))

    return {"wallet_id": wallet_id, "label": label, "balance_usd": 0.0,
            "daily_budget": daily_budget, "monthly_budget": monthly_budget}


def get_agent_wallet(wallet_id):
    """Get wallet details."""
    with _conn() as c:
        row = c.execute("SELECT * FROM agent_wallets WHERE id=?", (wallet_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["vendor_allowlist"] = json.loads(d["vendor_allowlist"])
        return d


def fund_agent_wallet(wallet_id, amount_usd):
    """Add funds to an agent wallet (called after Stripe payment)."""
    now = datetime.utcnow().isoformat() + "Z"
    with _conn() as c:
        row = c.execute("SELECT id FROM agent_wallets WHERE id=?", (wallet_id,)).fetchone()
        if not row:
            return {"error": "Wallet not found"}
        c.execute("UPDATE agent_wallets SET balance_usd=balance_usd+? WHERE id=?",
                  (amount_usd, wallet_id))

        tx_id = str(uuid.uuid4())[:12]
        c.execute("""INSERT INTO wallet_transactions
            (id, wallet_id, type, amount_usd, created_at)
            VALUES (?, ?, 'deposit', ?, ?)""",
            (tx_id, wallet_id, amount_usd, now))

    return {"status": "funded", "amount_usd": amount_usd, "tx_id": tx_id}


def update_wallet_policy(wallet_id, owner_api_key, daily_budget=None, monthly_budget=None,
                         vendor_allowlist=None):
    """Update wallet spending policies."""
    with _conn() as c:
        row = c.execute("SELECT owner_api_key FROM agent_wallets WHERE id=?", (wallet_id,)).fetchone()
        if not row:
            return {"error": "Wallet not found"}
        if row["owner_api_key"] != owner_api_key:
            return {"error": "Not authorized"}

        updates = []
        params = []
        if daily_budget is not None:
            updates.append("daily_budget=?")
            params.append(daily_budget)
        if monthly_budget is not None:
            updates.append("monthly_budget=?")
            params.append(monthly_budget)
        if vendor_allowlist is not None:
            updates.append("vendor_allowlist=?")
            params.append(json.dumps(vendor_allowlist))

        if not updates:
            return {"error": "No updates provided"}

        params.append(wallet_id)
        c.execute(f"UPDATE agent_wallets SET {', '.join(updates)} WHERE id=?", params)

    return {"updated": True, "wallet_id": wallet_id}


def get_wallet_transactions(wallet_id, limit=50):
    """Get transaction history for a wallet."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM wallet_transactions WHERE wallet_id=? ORDER BY created_at DESC LIMIT ?",
            (wallet_id, limit)
        ).fetchall()
    return [dict(r) for r in rows]


def list_agent_wallets(owner_api_key):
    """List all wallets for an API key."""
    with _conn() as c:
        rows = c.execute("SELECT * FROM agent_wallets WHERE owner_api_key=?",
                         (owner_api_key,)).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["vendor_allowlist"] = json.loads(d["vendor_allowlist"])
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Seller withdrawal
# ---------------------------------------------------------------------------

def request_withdrawal(seller_id, amount_usd=None):
    """Request withdrawal of seller balance to their wallet."""
    now = datetime.utcnow().isoformat() + "Z"

    with _conn() as c:
        rows = c.execute(
            "SELECT id, balance_usd, seller_wallet, preferred_chain FROM seller_apis WHERE seller_id=?",
            (seller_id,)
        ).fetchall()
        if not rows:
            return {"error": "No APIs found for this seller"}

        total_balance = sum(r["balance_usd"] for r in rows)
        if amount_usd is None:
            amount_usd = total_balance

        if amount_usd > total_balance:
            return {"error": "insufficient_balance", "available": total_balance, "requested": amount_usd}

        if amount_usd < 1.0:
            return {"error": "Minimum withdrawal is $1.00"}

        wallet = rows[0]["seller_wallet"]
        chain = rows[0]["preferred_chain"]

        if not wallet:
            return {"error": "No wallet address set. Update your API with a seller_wallet."}

        # Deduct proportionally from each API's balance
        remaining = amount_usd
        for r in rows:
            if remaining <= 0:
                break
            deduct = min(r["balance_usd"], remaining)
            if deduct > 0:
                c.execute("UPDATE seller_apis SET balance_usd=balance_usd-? WHERE id=?",
                          (deduct, r["id"]))
                remaining -= deduct

        payout_id = "po_" + str(uuid.uuid4())[:10]
        c.execute("""INSERT INTO seller_payouts
            (id, seller_id, amount_usd, chain, status, created_at)
            VALUES (?, ?, ?, ?, 'pending', ?)""",
            (payout_id, seller_id, amount_usd, chain, now))

    return {"payout_id": payout_id, "amount_usd": amount_usd, "chain": chain,
            "wallet": wallet, "status": "pending",
            "note": "Payout will be processed within 24 hours."}
