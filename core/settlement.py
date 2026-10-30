"""Payment settlement executor — batch settlement for marketplace, A2A, and trading commissions."""
import sqlite3
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

_log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "settlement.db")

MARKETPLACE_FEE_PCT = 0.05  # 5%
A2A_FEE_PCT = 0.03          # 3%


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


# ── Schema ──────────────────────────────────────────────────────────────────

def init_settlement_db():
    """Create settlement tables."""
    with _conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS settlement_batches (
            id TEXT PRIMARY KEY,
            batch_type TEXT NOT NULL CHECK(batch_type IN ('marketplace', 'a2a', 'trading')),
            total_amount REAL NOT NULL DEFAULT 0.0,
            total_items INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_batch_type ON settlement_batches(batch_type)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_batch_status ON settlement_batches(status)")

        c.execute("""CREATE TABLE IF NOT EXISTS settlement_items (
            id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            seller_id TEXT NOT NULL,
            amount REAL NOT NULL,
            source_type TEXT NOT NULL
                CHECK(source_type IN ('marketplace_call', 'a2a_transaction', 'trading_commission')),
            source_id TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'processing', 'completed', 'failed')),
            error_msg TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (batch_id) REFERENCES settlement_batches(id)
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_item_batch ON settlement_items(batch_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_item_seller ON settlement_items(seller_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_item_status ON settlement_items(status)")
    _log.info("Settlement DB initialized at %s", DB_PATH)


# ── Marketplace Settlements ─────────────────────────────────────────────────

def process_marketplace_settlements() -> dict:
    """Settle pending marketplace seller payments from agent_memory payment_splits table.

    Groups by seller, deducts 5% platform fee, creates batch + items, marks completed.
    """
    from agent_memory import get_pending_payments, _conn as mem_conn

    pending = get_pending_payments(limit=500)
    if not pending:
        return {"status": "no_pending", "items": 0, "total": 0.0}

    now = datetime.now(timezone.utc).isoformat()
    batch_id = str(uuid.uuid4())

    # Group by seller
    seller_map: dict[str, list] = {}
    for p in pending:
        wallet = p["seller_wallet"]
        seller_map.setdefault(wallet, []).append(p)

    items = []
    total_amount = 0.0
    for seller, payments in seller_map.items():
        gross = sum(p["seller_amount"] for p in payments)
        fee = round(gross * MARKETPLACE_FEE_PCT, 4)
        net = round(gross - fee, 4)
        total_amount += net
        for p in payments:
            p_net = round(p["seller_amount"] * (1 - MARKETPLACE_FEE_PCT), 4)
            items.append({
                "id": str(uuid.uuid4()),
                "batch_id": batch_id,
                "seller_id": seller,
                "amount": p_net,
                "source_type": "marketplace_call",
                "source_id": str(p["id"]),
                "created_at": now,
            })

    total_amount = round(total_amount, 4)

    # Write batch + items to settlement DB
    with _conn() as c:
        c.execute(
            "INSERT INTO settlement_batches (id, batch_type, total_amount, total_items, status, created_at) VALUES (?,?,?,?,?,?)",
            (batch_id, "marketplace", total_amount, len(items), "processing", now),
        )
        for item in items:
            c.execute(
                "INSERT INTO settlement_items (id, batch_id, seller_id, amount, source_type, source_id, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (item["id"], item["batch_id"], item["seller_id"], item["amount"],
                 item["source_type"], item["source_id"], "processing", item["created_at"]),
            )

    # Mark source payment_splits as settled
    split_ids = [p["id"] for p in pending]
    with mem_conn() as mc:
        mc.executemany(
            "UPDATE payment_splits SET status = 'settled' WHERE id = ?",
            [(sid,) for sid in split_ids],
        )

    # Mark settlement items + batch as completed
    with _conn() as c:
        c.execute("UPDATE settlement_items SET status = 'completed' WHERE batch_id = ?", (batch_id,))
        c.execute(
            "UPDATE settlement_batches SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), batch_id),
        )

    _log.info("Marketplace settlement batch %s: %d items, $%.4f total", batch_id, len(items), total_amount)
    return {
        "status": "completed",
        "batch_id": batch_id,
        "items": len(items),
        "sellers": len(seller_map),
        "total_amount": total_amount,
    }


# ── A2A Settlements ────────────────────────────────────────────────────────

def process_a2a_settlements() -> dict:
    """Settle completed A2A transactions that haven't been settled yet.

    Groups by seller, deducts 3% platform fee, creates batch + items.
    """
    from a2a_engine import _conn as a2a_conn

    now = datetime.now(timezone.utc).isoformat()

    # Get completed A2A transactions not yet settled
    with a2a_conn() as ac:
        rows = ac.execute(
            "SELECT * FROM a2a_transactions WHERE status = 'completed' ORDER BY created_at LIMIT 500"
        ).fetchall()

    txns = [dict(r) for r in rows]
    if not txns:
        return {"status": "no_pending", "items": 0, "total": 0.0}

    # Filter out already-settled transaction IDs
    tx_ids = [t["id"] for t in txns]
    with _conn() as c:
        placeholders = ",".join("?" * len(tx_ids))
        already = set(
            r["source_id"] for r in c.execute(
                f"SELECT source_id FROM settlement_items WHERE source_type = 'a2a_transaction' AND source_id IN ({placeholders})",
                tx_ids,
            ).fetchall()
        )

    unsettled = [t for t in txns if t["id"] not in already]
    if not unsettled:
        return {"status": "no_pending", "items": 0, "total": 0.0}

    batch_id = str(uuid.uuid4())

    # Group by seller
    seller_map: dict[str, list] = {}
    for tx in unsettled:
        seller_map.setdefault(tx["seller_id"], []).append(tx)

    items = []
    total_amount = 0.0
    for seller, seller_txns in seller_map.items():
        for tx in seller_txns:
            net = round(tx["amount_usd"] * (1 - A2A_FEE_PCT), 4)
            total_amount += net
            items.append({
                "id": str(uuid.uuid4()),
                "batch_id": batch_id,
                "seller_id": seller,
                "amount": net,
                "source_type": "a2a_transaction",
                "source_id": tx["id"],
                "created_at": now,
            })

    total_amount = round(total_amount, 4)

    # Write batch + items
    with _conn() as c:
        c.execute(
            "INSERT INTO settlement_batches (id, batch_type, total_amount, total_items, status, created_at) VALUES (?,?,?,?,?,?)",
            (batch_id, "a2a", total_amount, len(items), "processing", now),
        )
        for item in items:
            c.execute(
                "INSERT INTO settlement_items (id, batch_id, seller_id, amount, source_type, source_id, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (item["id"], item["batch_id"], item["seller_id"], item["amount"],
                 item["source_type"], item["source_id"], "processing", item["created_at"]),
            )
        # Mark completed
        c.execute("UPDATE settlement_items SET status = 'completed' WHERE batch_id = ?", (batch_id,))
        c.execute(
            "UPDATE settlement_batches SET status = 'completed', completed_at = ? WHERE id = ?",
            (datetime.now(timezone.utc).isoformat(), batch_id),
        )

    _log.info("A2A settlement batch %s: %d items, $%.4f total", batch_id, len(items), total_amount)
    return {
        "status": "completed",
        "batch_id": batch_id,
        "items": len(items),
        "sellers": len(seller_map),
        "total_amount": total_amount,
    }


# ── Combined Settlement ─────────────────────────────────────────────────────

def process_all_settlements() -> dict:
    """Run both marketplace and A2A settlement in one call."""
    marketplace = process_marketplace_settlements()
    a2a = process_a2a_settlements()
    return {
        "marketplace": marketplace,
        "a2a": a2a,
        "total_settled": round(
            (marketplace.get("total_amount", 0.0) or 0.0) +
            (a2a.get("total_amount", 0.0) or 0.0), 4
        ),
    }


# ── History & Stats ─────────────────────────────────────────────────────────

def get_settlement_history(seller_id: str = None, limit: int = 20) -> list[dict]:
    """Get settlement history, optionally filtered by seller."""
    with _conn() as c:
        if seller_id:
            rows = c.execute(
                """SELECT si.*, sb.batch_type, sb.status as batch_status
                   FROM settlement_items si
                   JOIN settlement_batches sb ON si.batch_id = sb.id
                   WHERE si.seller_id = ?
                   ORDER BY si.created_at DESC LIMIT ?""",
                (seller_id, limit),
            ).fetchall()
        else:
            rows = c.execute(
                """SELECT si.*, sb.batch_type, sb.status as batch_status
                   FROM settlement_items si
                   JOIN settlement_batches sb ON si.batch_id = sb.id
                   ORDER BY si.created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
    return [dict(r) for r in rows]


def get_settlement_stats() -> dict:
    """Total settled, pending, broken down by type."""
    with _conn() as c:
        # By status
        completed = c.execute(
            "SELECT COALESCE(SUM(total_amount), 0) as total, COUNT(*) as batches FROM settlement_batches WHERE status = 'completed'"
        ).fetchone()
        pending = c.execute(
            "SELECT COALESCE(SUM(total_amount), 0) as total, COUNT(*) as batches FROM settlement_batches WHERE status IN ('pending', 'processing')"
        ).fetchone()
        failed = c.execute(
            "SELECT COALESCE(SUM(total_amount), 0) as total, COUNT(*) as batches FROM settlement_batches WHERE status = 'failed'"
        ).fetchone()

        # By type
        by_type = {}
        for bt in ("marketplace", "a2a", "trading"):
            row = c.execute(
                "SELECT COALESCE(SUM(total_amount), 0) as total, COUNT(*) as batches FROM settlement_batches WHERE batch_type = ? AND status = 'completed'",
                (bt,),
            ).fetchone()
            by_type[bt] = {"total": row["total"], "batches": row["batches"]}

        # Item-level stats
        total_items = c.execute("SELECT COUNT(*) as cnt FROM settlement_items").fetchone()["cnt"]
        unique_sellers = c.execute("SELECT COUNT(DISTINCT seller_id) as cnt FROM settlement_items").fetchone()["cnt"]

    return {
        "completed": {"total": completed["total"], "batches": completed["batches"]},
        "pending": {"total": pending["total"], "batches": pending["batches"]},
        "failed": {"total": failed["total"], "batches": failed["batches"]},
        "by_type": by_type,
        "total_items": total_items,
        "unique_sellers": unique_sellers,
    }
