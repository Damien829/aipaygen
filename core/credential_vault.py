"""Encrypted credential vault for external API keys. Stored in api_catalog.db."""
import os
import sqlite3
import hashlib
import base64

DB_PATH = os.path.join(os.path.dirname(__file__), "api_catalog.db")


def _get_fernet():
    """Get Fernet instance using the existing agent key."""
    key_path = os.path.expanduser("~/.agent_key")
    if not os.path.exists(key_path):
        return None
    try:
        from cryptography.fernet import Fernet
        with open(key_path, "rb") as f:
            raw_key = f.read().strip()
        # If it's already a valid Fernet key (44 bytes base64), use directly
        if len(raw_key) == 44:
            return Fernet(raw_key)
        # Otherwise derive a Fernet key from it
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw_key).digest())
        return Fernet(derived)
    except Exception:
        return None


def init_vault():
    """Create the credentials table if it doesn't exist."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS api_credentials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_id INTEGER,
        credential_type TEXT DEFAULT 'api_key',
        encrypted_value TEXT NOT NULL,
        label TEXT,
        created_at TEXT,
        UNIQUE(api_id, credential_type)
    )""")
    conn.commit()
    conn.close()


def store_credential(api_id: int, value: str, cred_type: str = "api_key",
                     label: str = "") -> dict:
    """Encrypt and store a credential for a catalog API."""
    f = _get_fernet()
    if not f:
        return {"error": "Encryption key not available (~/.agent_key)"}
    encrypted = f.encrypt(value.encode()).decode()
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO api_credentials "
        "(api_id, credential_type, encrypted_value, label, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (api_id, cred_type, encrypted, label),
    )
    conn.commit()
    conn.close()
    return {"stored": True, "api_id": api_id, "type": cred_type}


def get_credential(api_id: int, cred_type: str = "api_key") -> str | None:
    """Retrieve and decrypt a stored credential."""
    f = _get_fernet()
    if not f:
        return None
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT encrypted_value FROM api_credentials "
        "WHERE api_id = ? AND credential_type = ?",
        (api_id, cred_type),
    ).fetchone()
    conn.close()
    if not row:
        return None
    try:
        return f.decrypt(row["encrypted_value"].encode()).decode()
    except Exception:
        return None


def list_credentials() -> list:
    """List all stored credentials (without values)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, api_id, credential_type, label, created_at FROM api_credentials"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_credential(api_id: int, cred_type: str = "api_key") -> bool:
    """Remove a stored credential."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        "DELETE FROM api_credentials WHERE api_id = ? AND credential_type = ?",
        (api_id, cred_type),
    )
    conn.commit()
    conn.close()
    return cur.rowcount > 0
