"""A2A Commerce Engine — agent-to-agent discovery, RFQs, negotiation, contracts, settlement."""
import sqlite3
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.path.join(os.path.dirname(__file__), "a2a.db")


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def init_a2a_db():
    with _conn() as c:
        # RFQ Requests — agent broadcasts what it needs
        c.execute("""CREATE TABLE IF NOT EXISTS rfq_requests (
            id TEXT PRIMARY KEY,
            requester_id TEXT NOT NULL,
            requester_name TEXT DEFAULT '',
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            capabilities_needed TEXT NOT NULL DEFAULT '[]',
            budget_usd REAL NOT NULL DEFAULT 0.0,
            budget_type TEXT NOT NULL DEFAULT 'per_call',
            sla_requirements TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'open',
            responses_count INTEGER DEFAULT 0,
            selected_responder TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            closed_at TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rfq_status ON rfq_requests(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rfq_requester ON rfq_requests(requester_id)")

        # RFQ Responses — agents bid on RFQs
        c.execute("""CREATE TABLE IF NOT EXISTS rfq_responses (
            id TEXT PRIMARY KEY,
            rfq_id TEXT NOT NULL,
            responder_id TEXT NOT NULL,
            responder_name TEXT DEFAULT '',
            price_usd REAL NOT NULL,
            price_type TEXT NOT NULL DEFAULT 'per_call',
            sla_offered TEXT DEFAULT '{}',
            message TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (rfq_id) REFERENCES rfq_requests(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rfqr_rfq ON rfq_responses(rfq_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_rfqr_responder ON rfq_responses(responder_id)")

        # A2A Contracts — formalized agreements between agents
        c.execute("""CREATE TABLE IF NOT EXISTS a2a_contracts (
            id TEXT PRIMARY KEY,
            buyer_id TEXT NOT NULL,
            buyer_name TEXT DEFAULT '',
            seller_id TEXT NOT NULL,
            seller_name TEXT DEFAULT '',
            rfq_id TEXT,
            service_description TEXT NOT NULL,
            price_usd REAL NOT NULL,
            price_type TEXT NOT NULL DEFAULT 'per_call',
            terms TEXT DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            total_calls INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            FOREIGN KEY (rfq_id) REFERENCES rfq_requests(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_contract_buyer ON a2a_contracts(buyer_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_contract_seller ON a2a_contracts(seller_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_contract_status ON a2a_contracts(status)")

        # A2A Transactions — every payment between agents
        c.execute("""CREATE TABLE IF NOT EXISTS a2a_transactions (
            id TEXT PRIMARY KEY,
            contract_id TEXT,
            buyer_id TEXT NOT NULL,
            seller_id TEXT NOT NULL,
            amount_usd REAL NOT NULL,
            platform_fee REAL DEFAULT 0.0,
            payment_method TEXT DEFAULT 'credits',
            escrow_status TEXT DEFAULT 'none',
            service_endpoint TEXT DEFAULT '',
            request_payload TEXT DEFAULT '',
            response_status INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'completed',
            created_at TEXT NOT NULL,
            FOREIGN KEY (contract_id) REFERENCES a2a_contracts(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_a2a_tx_buyer ON a2a_transactions(buyer_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_a2a_tx_seller ON a2a_transactions(seller_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_a2a_tx_status ON a2a_transactions(status)")

        # A2A Agent Capabilities — what each agent offers for A2A
        c.execute("""CREATE TABLE IF NOT EXISTS a2a_capabilities (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            agent_name TEXT DEFAULT '',
            capabilities TEXT NOT NULL DEFAULT '[]',
            endpoint TEXT DEFAULT '',
            min_price_usd REAL DEFAULT 0.01,
            max_rate_per_hour INTEGER DEFAULT 100,
            auto_accept INTEGER DEFAULT 1,
            negotiation_enabled INTEGER DEFAULT 0,
            accepted_payments TEXT DEFAULT '["credits","x402"]',
            a2a_enabled INTEGER DEFAULT 1,
            total_a2a_calls INTEGER DEFAULT 0,
            total_a2a_revenue REAL DEFAULT 0.0,
            avg_response_ms INTEGER DEFAULT 0,
            reputation_score REAL DEFAULT 0.0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(agent_id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_a2a_cap_agent ON a2a_capabilities(agent_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_a2a_cap_enabled ON a2a_capabilities(a2a_enabled)")


# ── A2A Agent Registration ────────────────────────────────────────────────────

def register_a2a_agent(agent_id: str, agent_name: str = "", capabilities: list = None,
                       endpoint: str = "", min_price_usd: float = 0.01,
                       max_rate_per_hour: int = 100, auto_accept: bool = True,
                       negotiation_enabled: bool = False) -> dict:
    """Register or update an agent's A2A capabilities."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        c.execute("""INSERT INTO a2a_capabilities
            (id, agent_id, agent_name, capabilities, endpoint, min_price_usd,
             max_rate_per_hour, auto_accept, negotiation_enabled, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET
                agent_name=excluded.agent_name, capabilities=excluded.capabilities,
                endpoint=excluded.endpoint, min_price_usd=excluded.min_price_usd,
                max_rate_per_hour=excluded.max_rate_per_hour,
                auto_accept=excluded.auto_accept, negotiation_enabled=excluded.negotiation_enabled,
                updated_at=excluded.updated_at""",
            (str(uuid.uuid4()), agent_id, agent_name, json.dumps(capabilities or []),
             endpoint, min_price_usd, max_rate_per_hour,
             1 if auto_accept else 0, 1 if negotiation_enabled else 0, now, now))
    return {"agent_id": agent_id, "a2a_enabled": True}


def discover_agents(capability: str = None, max_price: float = None, limit: int = 20) -> list:
    """Discover A2A-enabled agents by capability."""
    conditions = ["a2a_enabled = 1"]
    params = []
    if capability:
        conditions.append("capabilities LIKE ?")
        params.append(f"%{capability}%")
    if max_price is not None:
        conditions.append("min_price_usd <= ?")
        params.append(max_price)
    where = " AND ".join(conditions)
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM a2a_capabilities WHERE {where} ORDER BY reputation_score DESC, total_a2a_calls DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = json.loads(d.get("capabilities") or "[]")
        d["accepted_payments"] = json.loads(d.get("accepted_payments") or "[]")
        results.append(d)
    return results


# ── RFQ System ────────────────────────────────────────────────────────────────

def create_rfq(requester_id: str, title: str, description: str,
               capabilities_needed: list = None, budget_usd: float = 0.0,
               budget_type: str = "per_call", sla_requirements: dict = None,
               requester_name: str = "", expires_hours: int = 24) -> dict:
    """Create a Request for Quote."""
    now = datetime.now(timezone.utc)
    rid = str(uuid.uuid4())
    expires = (now + __import__('datetime').timedelta(hours=expires_hours)).isoformat()
    with _conn() as c:
        c.execute("""INSERT INTO rfq_requests
            (id, requester_id, requester_name, title, description, capabilities_needed,
             budget_usd, budget_type, sla_requirements, status, created_at, expires_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rid, requester_id, requester_name, title, description,
             json.dumps(capabilities_needed or []), budget_usd, budget_type,
             json.dumps(sla_requirements or {}), "open", now.isoformat(), expires))
    return {"rfq_id": rid, "status": "open", "expires_at": expires}


def respond_to_rfq(rfq_id: str, responder_id: str, price_usd: float,
                   price_type: str = "per_call", sla_offered: dict = None,
                   message: str = "", responder_name: str = "") -> dict:
    """Submit a response/bid to an RFQ."""
    now = datetime.now(timezone.utc).isoformat()
    resp_id = str(uuid.uuid4())
    with _conn() as c:
        rfq = c.execute("SELECT * FROM rfq_requests WHERE id = ? AND status = 'open'", (rfq_id,)).fetchone()
        if not rfq:
            return {"error": "RFQ not found or closed"}
        c.execute("""INSERT INTO rfq_responses
            (id, rfq_id, responder_id, responder_name, price_usd, price_type,
             sla_offered, message, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (resp_id, rfq_id, responder_id, responder_name, price_usd, price_type,
             json.dumps(sla_offered or {}), message, "pending", now))
        c.execute("UPDATE rfq_requests SET responses_count = responses_count + 1 WHERE id = ?", (rfq_id,))
    return {"response_id": resp_id, "rfq_id": rfq_id, "status": "pending"}


def accept_rfq_response(rfq_id: str, response_id: str) -> dict:
    """Accept an RFQ response and create a contract."""
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        rfq = c.execute("SELECT * FROM rfq_requests WHERE id = ?", (rfq_id,)).fetchone()
        resp = c.execute("SELECT * FROM rfq_responses WHERE id = ? AND rfq_id = ?", (response_id, rfq_id)).fetchone()
        if not rfq or not resp:
            return {"error": "RFQ or response not found"}

        rfq = dict(rfq)
        resp = dict(resp)

        # Create contract
        contract_id = str(uuid.uuid4())
        c.execute("""INSERT INTO a2a_contracts
            (id, buyer_id, buyer_name, seller_id, seller_name, rfq_id,
             service_description, price_usd, price_type, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (contract_id, rfq["requester_id"], rfq.get("requester_name", ""),
             resp["responder_id"], resp.get("responder_name", ""), rfq_id,
             rfq["description"], resp["price_usd"], resp["price_type"],
             "active", now))

        # Update statuses
        c.execute("UPDATE rfq_requests SET status = 'accepted', selected_responder = ?, closed_at = ? WHERE id = ?",
                  (resp["responder_id"], now, rfq_id))
        c.execute("UPDATE rfq_responses SET status = 'accepted' WHERE id = ?", (response_id,))
        c.execute("UPDATE rfq_responses SET status = 'rejected' WHERE rfq_id = ? AND id != ?", (rfq_id, response_id))

    return {"contract_id": contract_id, "rfq_id": rfq_id, "status": "active"}


def get_open_rfqs(capability: str = None, limit: int = 20) -> list:
    """Get open RFQs, optionally filtered by capability."""
    conditions = ["status = 'open'"]
    params = []
    if capability:
        conditions.append("capabilities_needed LIKE ?")
        params.append(f"%{capability}%")
    where = " AND ".join(conditions)
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM rfq_requests WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["capabilities_needed"] = json.loads(d.get("capabilities_needed") or "[]")
        d["sla_requirements"] = json.loads(d.get("sla_requirements") or "{}")
        results.append(d)
    return results


def get_rfq_responses(rfq_id: str) -> list:
    with _conn() as c:
        rows = c.execute("SELECT * FROM rfq_responses WHERE rfq_id = ? ORDER BY price_usd ASC", (rfq_id,)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["sla_offered"] = json.loads(d.get("sla_offered") or "{}")
        results.append(d)
    return results


# ── A2A Transactions ──────────────────────────────────────────────────────────

PLATFORM_FEE_PCT = 0.03  # 3%

def record_a2a_transaction(buyer_id: str, seller_id: str, amount_usd: float,
                           contract_id: str = "", payment_method: str = "credits",
                           service_endpoint: str = "", response_status: int = 200) -> dict:
    """Record an A2A transaction."""
    now = datetime.now(timezone.utc).isoformat()
    tid = str(uuid.uuid4())
    fee = round(amount_usd * PLATFORM_FEE_PCT, 4)

    with _conn() as c:
        c.execute("""INSERT INTO a2a_transactions
            (id, contract_id, buyer_id, seller_id, amount_usd, platform_fee,
             payment_method, service_endpoint, response_status, status, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, contract_id, buyer_id, seller_id, amount_usd, fee,
             payment_method, service_endpoint, response_status, "completed", now))

        # Update contract stats
        if contract_id:
            c.execute("""UPDATE a2a_contracts SET total_calls = total_calls + 1,
                         total_spent = total_spent + ? WHERE id = ?""",
                      (amount_usd, contract_id))

        # Update seller stats
        c.execute("""UPDATE a2a_capabilities SET total_a2a_calls = total_a2a_calls + 1,
                     total_a2a_revenue = total_a2a_revenue + ? WHERE agent_id = ?""",
                  (amount_usd - fee, seller_id))

    return {"transaction_id": tid, "amount": amount_usd, "fee": fee,
            "seller_receives": round(amount_usd - fee, 4), "status": "completed"}


def get_a2a_transactions(buyer_id: str = None, seller_id: str = None,
                         limit: int = 50) -> list:
    """Get A2A transaction history."""
    conditions = []
    params = []
    if buyer_id:
        conditions.append("buyer_id = ?")
        params.append(buyer_id)
    if seller_id:
        conditions.append("seller_id = ?")
        params.append(seller_id)
    where = " AND ".join(conditions) if conditions else "1=1"
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM a2a_transactions WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params + [limit]
        ).fetchall()
    return [dict(r) for r in rows]


# ── A2A Stats & Leaderboard ──────────────────────────────────────────────────

def a2a_stats() -> dict:
    """Get network-wide A2A stats."""
    with _conn() as c:
        agents = c.execute("SELECT COUNT(*) FROM a2a_capabilities WHERE a2a_enabled = 1").fetchone()[0]
        rfqs_open = c.execute("SELECT COUNT(*) FROM rfq_requests WHERE status = 'open'").fetchone()[0]
        contracts = c.execute("SELECT COUNT(*) FROM a2a_contracts WHERE status = 'active'").fetchone()[0]
        tx_row = c.execute("SELECT COUNT(*), COALESCE(SUM(amount_usd), 0) FROM a2a_transactions").fetchone()
        tx_24h = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount_usd), 0) FROM a2a_transactions WHERE created_at > datetime('now', '-1 day')"
        ).fetchone()
    return {
        "live_agents": agents,
        "open_rfqs": rfqs_open,
        "active_contracts": contracts,
        "total_transactions": tx_row[0],
        "total_volume_usd": round(tx_row[1], 2),
        "transactions_24h": tx_24h[0],
        "volume_24h_usd": round(tx_24h[1], 2),
    }


def a2a_leaderboard(limit: int = 20) -> list:
    """Top A2A agents by revenue."""
    with _conn() as c:
        rows = c.execute("""SELECT * FROM a2a_capabilities
            WHERE a2a_enabled = 1 AND total_a2a_calls > 0
            ORDER BY total_a2a_revenue DESC LIMIT ?""", (limit,)).fetchall()
    results = []
    for r in rows:
        d = dict(r)
        d["capabilities"] = json.loads(d.get("capabilities") or "[]")
        results.append(d)
    return results
