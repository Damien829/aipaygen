# Lesson 01: Flask Foundation

## What You Will Build

A production-ready Flask application skeleton with SQLite, Gunicorn, CORS, health checks, and a modular blueprint architecture. This is the foundation everything else sits on.

## The App Skeleton

Here is the real pattern from the AiPayGen codebase. The key insight is that `app.py` is the orchestrator — it imports blueprints and wires everything together, but keeps its own code minimal.

```python
import os
import json
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.urandom(32)

# ── CORS (allow all origins for API usage) ──────────────────────────────
from flask_cors import CORS
CORS(app, resources={r"/*": {"origins": "*"}})
```

Notice: no database models, no complex configuration objects, no dependency injection framework. Just a Flask app with CORS enabled for API consumers. Environment variables come from `.env` through `python-dotenv`.

## SQLite as Your Database

Every module in this codebase manages its own SQLite database. This is unconventional but deliberate — it provides natural isolation and makes each module independently testable.

```python
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "api_keys.db")

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA cache_size=-8000")
    c.execute("PRAGMA temp_store=MEMORY")
    c.row_factory = sqlite3.Row
    return c
```

The four PRAGMAs are critical for production:

- **WAL mode**: Allows concurrent reads while writing. Without this, your API will stall under any load.
- **synchronous=NORMAL**: Trades a tiny amount of crash safety for significant write speed. For a web app where you can rebuild state, this is the right trade-off.
- **cache_size=-8000**: Uses 8MB of memory for the page cache. Faster reads on repeated queries.
- **temp_store=MEMORY**: Keeps temporary tables in RAM instead of disk.

The `row_factory = sqlite3.Row` line lets you access columns by name (`row["balance_usd"]`) instead of index (`row[3]`).

## Schema Migrations Without a Framework

Instead of Alembic or Django migrations, the codebase uses a try/except pattern for adding columns:

```python
def init_keys_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS api_keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                label TEXT DEFAULT '',
                balance_usd REAL DEFAULT 0.0,
                total_spent REAL DEFAULT 0.0,
                call_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_apikey_key ON api_keys(key)")
        
        # Safe migration: add column if it doesn't exist
        try:
            c.execute("ALTER TABLE api_keys ADD COLUMN source TEXT DEFAULT 'unknown'")
        except sqlite3.OperationalError:
            pass  # Column already exists
```

This is ugly but it works perfectly for a solo developer. Every time the app starts, it ensures the schema is up to date. No migration files to track, no migration state to corrupt.

## Health Check Endpoint

Every production service needs a health check. This is what load balancers, monitoring tools, and your deployment scripts hit to verify the service is alive.

```python
@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": APP_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
```

Keep it simple. Return 200 with a version number. Your deployment script (Lesson 08) will curl this endpoint after every deploy.

## Blueprint Architecture

As your app grows beyond 500 lines, split it into blueprints. Each blueprint handles one domain:

```python
# routes/auth.py
from flask import Blueprint
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/auth/generate-key", methods=["POST"])
def auth_generate_key():
    ...

# routes/webhooks.py
webhooks_bp = Blueprint("webhooks", __name__)

@webhooks_bp.route("/webhooks/subscribe", methods=["POST"])
def webhook_subscribe():
    ...
```

Then register them in `app.py`:

```python
from routes.auth import auth_bp
from routes.webhooks import webhooks_bp
from routes.marketplace import marketplace_bp

app.register_blueprint(auth_bp)
app.register_blueprint(webhooks_bp)
app.register_blueprint(marketplace_bp)
```

The AiPayGen codebase has 25 blueprint files across domains: auth, marketplace, trading, webhooks, discovery, admin, and more. Each one is independently readable.

## Gunicorn Configuration

Flask's built-in server is for development only. For production, use Gunicorn:

```bash
gunicorn app:app \
    --bind 0.0.0.0:5001 \
    --workers 2 \
    --timeout 120 \
    --access-logfile logs/access.log \
    --error-logfile logs/error.log
```

On a Raspberry Pi 5, 2 workers is the sweet spot. More workers means more memory, and SQLite handles concurrency through WAL mode rather than through connection pooling.

## Shared Utilities

Extract common functions into a `helpers.py` module:

```python
# helpers.py
APP_VERSION = "1.9.5"
import time as _time

_ip_rate: dict = {}
_RATE_LIMIT = 60
_RATE_WINDOW = 60

def check_rate_limit(ip: str, limit_override: int = None) -> bool:
    """Returns True if request is allowed, False if rate limited."""
    limit = limit_override or _RATE_LIMIT
    now = _time.time()
    times = [t for t in _ip_rate.get(ip, []) if t > now - _RATE_WINDOW][-limit:]
    if len(times) >= limit:
        _ip_rate[ip] = times
        return False
    times.append(now)
    _ip_rate[ip] = times
    return True
```

In-memory rate limiting is fine for a single-server deployment. No Redis needed. The dictionary gets cleaned up periodically to prevent memory growth.

## Exercise

1. Create an `app.py` with Flask, CORS, and a `/health` endpoint.
2. Create a `helpers.py` with the rate limiting function above.
3. Create a `routes/` directory with one blueprint that returns `{"hello": "world"}`.
4. Run it with `gunicorn app:app --bind 0.0.0.0:5001 --workers 2`.
5. Verify: `curl http://localhost:5001/health` should return `{"status": "ok"}`.

In the next lesson, we build the API key system that makes everything monetizable.
