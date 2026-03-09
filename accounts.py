"""AiPayGen accounts database — links emails to API keys."""

import os
import sqlite3
from datetime import datetime, timezone

_DB_PATH = os.getenv("ACCOUNTS_DB", os.path.join(os.path.dirname(__file__), "accounts.db"))
_conn = None


def _get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.row_factory = sqlite3.Row
    return _conn


def init_accounts_db():
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            last_login TEXT,
            digest_opt_out INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS account_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            api_key TEXT UNIQUE NOT NULL,
            linked_at TEXT NOT NULL,
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        );
    """)
    conn.commit()


def create_or_get_account(email: str) -> dict:
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("INSERT INTO accounts (email, created_at) VALUES (?, ?)", (email, now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    return dict(row)


def get_account_by_email(email: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def link_key_to_account(account_id: int, api_key: str):
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute("INSERT INTO account_keys (account_id, api_key, linked_at) VALUES (?, ?, ?)",
                      (account_id, api_key, now))
        conn.commit()
    except sqlite3.IntegrityError:
        pass


def get_account_keys(account_id: int) -> list:
    conn = _get_conn()
    rows = conn.execute("SELECT * FROM account_keys WHERE account_id = ?", (account_id,)).fetchall()
    return [dict(r) for r in rows]


def update_last_login(account_id: int):
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE accounts SET last_login = ? WHERE id = ?", (now, account_id))
    conn.commit()


def set_digest_opt_out(account_id: int, opt_out: bool = True):
    conn = _get_conn()
    conn.execute("UPDATE accounts SET digest_opt_out = ? WHERE id = ?", (1 if opt_out else 0, account_id))
    conn.commit()
