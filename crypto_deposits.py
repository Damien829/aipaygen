"""SQLite-backed crypto deposit records, addresses, and pending intents."""

import os
import sqlite3
import time
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "crypto_deposits.db")

# ---------------------------------------------------------------------------
# Config from env
# ---------------------------------------------------------------------------
CRYPTO_MIN_DEPOSIT_USD = float(os.environ.get("CRYPTO_MIN_DEPOSIT_USD", "0.50"))
CRYPTO_MAX_DEPOSIT_USD = float(os.environ.get("CRYPTO_MAX_DEPOSIT_USD", "10000"))
CRYPTO_FEE_PERCENT = float(os.environ.get("CRYPTO_FEE_PERCENT", "0"))
CRYPTO_BASE_CONFIRMATIONS = int(os.environ.get("CRYPTO_BASE_CONFIRMATIONS", "5"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
USDC_BASE = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
USDC_SOL_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

PENDING_TTL_SECONDS = 24 * 60 * 60  # 24 hours


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
def init_crypto_db():
    """Create the three tables if they don't exist."""
    conn = _conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL,
            tx_hash TEXT NOT NULL UNIQUE,
            network TEXT NOT NULL,
            amount_token REAL NOT NULL,
            amount_usd REAL NOT NULL,
            sender_address TEXT,
            deposit_address TEXT,
            block_number INTEGER,
            confirmations INTEGER DEFAULT 0,
            credited INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deposit_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL UNIQUE,
            evm_address TEXT,
            evm_index INTEGER,
            solana_address TEXT,
            solana_index INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pending_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            api_key TEXT NOT NULL,
            network TEXT NOT NULL,
            deposit_address TEXT NOT NULL,
            expected_amount REAL,
            expires_at REAL NOT NULL,
            created_at TEXT NOT NULL
        );
    """)
    conn.close()


# ---------------------------------------------------------------------------
# Deposits
# ---------------------------------------------------------------------------
def record_deposit(api_key, tx_hash, network, amount_token, amount_usd,
                   sender_address, deposit_address, block_number,
                   confirmations=0):
    """Insert a deposit record. Returns dict with status 'recorded' or 'already_claimed'."""
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """INSERT INTO deposits
               (api_key, tx_hash, network, amount_token, amount_usd,
                sender_address, deposit_address, block_number, confirmations, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (api_key, tx_hash, network, amount_token, amount_usd,
             sender_address, deposit_address, block_number, confirmations, now),
        )
        conn.commit()
        return {"status": "recorded", "tx_hash": tx_hash, "amount_usd": amount_usd}
    except sqlite3.IntegrityError:
        return {"status": "already_claimed", "tx_hash": tx_hash}
    finally:
        conn.close()


def get_deposit_by_tx(tx_hash):
    """Return a single deposit dict or None."""
    conn = _conn()
    row = conn.execute("SELECT * FROM deposits WHERE tx_hash = ?", (tx_hash,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_deposits_for_key(api_key):
    """Return list of deposit dicts for an API key."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM deposits WHERE api_key = ? ORDER BY id DESC", (api_key,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_deposits(limit=100):
    """Return the most recent deposits."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM deposits ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def is_tx_claimed(tx_hash):
    """Check whether a tx_hash already exists in deposits."""
    conn = _conn()
    row = conn.execute("SELECT 1 FROM deposits WHERE tx_hash = ?", (tx_hash,)).fetchone()
    conn.close()
    return row is not None


def mark_deposit_credited(tx_hash):
    """Set credited=1 for a deposit. Returns True if updated."""
    conn = _conn()
    cur = conn.execute(
        "UPDATE deposits SET credited = 1 WHERE tx_hash = ?", (tx_hash,)
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


# ---------------------------------------------------------------------------
# Pending deposits
# ---------------------------------------------------------------------------
def create_pending_deposit(api_key, network, deposit_address, expected_amount=None):
    """Create a pending deposit intent with 24h TTL. Returns dict."""
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    expires_at = time.time() + PENDING_TTL_SECONDS
    conn.execute(
        """INSERT INTO pending_deposits
           (api_key, network, deposit_address, expected_amount, expires_at, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (api_key, network, deposit_address, expected_amount, expires_at, now),
    )
    conn.commit()
    row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.close()
    return {
        "id": row_id,
        "api_key": api_key,
        "network": network,
        "deposit_address": deposit_address,
        "expected_amount": expected_amount,
        "expires_at": expires_at,
    }


def get_pending_for_address(address, network):
    """Return non-expired pending deposits for an address + network."""
    conn = _conn()
    now = time.time()
    rows = conn.execute(
        """SELECT * FROM pending_deposits
           WHERE deposit_address = ? AND network = ? AND expires_at > ?""",
        (address, network, now),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Deposit addresses
# ---------------------------------------------------------------------------
def create_deposit_address(api_key, evm_address, evm_index,
                           solana_address=None, solana_index=None):
    """Assign deposit addresses for an API key (INSERT OR REPLACE)."""
    conn = _conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO deposit_addresses
           (api_key, evm_address, evm_index, solana_address, solana_index, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (api_key, evm_address, evm_index, solana_address, solana_index, now),
    )
    conn.commit()
    conn.close()
    return {
        "api_key": api_key,
        "evm_address": evm_address,
        "evm_index": evm_index,
        "solana_address": solana_address,
        "solana_index": solana_index,
    }


def get_deposit_address(api_key):
    """Return deposit address dict or None."""
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM deposit_addresses WHERE api_key = ?", (api_key,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
