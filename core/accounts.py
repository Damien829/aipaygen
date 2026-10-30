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
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.execute("PRAGMA cache_size=-8000")
        _conn.execute("PRAGMA temp_store=MEMORY")
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
    # OAuth columns migration
    for col, default in [("password_hash", ""), ("salt", ""), ("oauth_provider", ""), ("oauth_id", ""), ("display_name", ""), ("avatar_url", "")]:
        try:
            conn.execute(f"ALTER TABLE accounts ADD COLUMN {col} TEXT DEFAULT '{default}'")
        except sqlite3.OperationalError:
            pass
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


def create_or_get_oauth_account(email: str, provider: str, oauth_id: str,
                                 display_name: str = "", avatar_url: str = "") -> dict:
    """Create or retrieve account via OAuth provider. Links OAuth identity."""
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    # Check if account exists by email
    row = conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone()
    if row:
        # Update OAuth info if not already set
        if not row["oauth_provider"]:
            conn.execute(
                "UPDATE accounts SET oauth_provider = ?, oauth_id = ?, display_name = ?, avatar_url = ? WHERE id = ?",
                (provider, oauth_id, display_name, avatar_url, row["id"]),
            )
            conn.commit()
        update_last_login(row["id"])
        return dict(conn.execute("SELECT * FROM accounts WHERE id = ?", (row["id"],)).fetchone())
    # Create new account
    conn.execute(
        "INSERT INTO accounts (email, created_at, last_login, oauth_provider, oauth_id, display_name, avatar_url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (email, now, now, provider, oauth_id, display_name, avatar_url),
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM accounts WHERE email = ?", (email,)).fetchone())


def get_account_by_oauth(provider: str, oauth_id: str) -> dict | None:
    """Find account by OAuth provider and ID."""
    conn = _get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE oauth_provider = ? AND oauth_id = ?",
                       (provider, oauth_id)).fetchone()
    return dict(row) if row else None
