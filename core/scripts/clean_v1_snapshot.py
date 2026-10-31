"""Copy the v1 database snapshot and strip the rows its test suite wrote into it.

Until 2026-10-30 the tests ran against the live databases, so the 2026-03-30
snapshot is full of fake deposits, throwaway keys and rows that point at keys
which no longer exist. This copies SRC to DEST (SRC is never modified), removes
only rows matched by the exact rules below, checks integrity, and writes
DEST/cleanup-report.json with before/after counts for every table.

    python scripts/clean_v1_snapshot.py ~/AIPayGen-Backups/v1-databases-2026-03-30 /path/to/data-dir

billing_audit is deliberately left alone: audit logs are not edited.
"""
import json
import shutil
from contextlib import closing
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

FAKE_SENDERS = ("0xSENDER", "0xS", "SolSender")

# (database, table, WHERE clause, reason). Run in order; later rules can depend on
# earlier ones (orphan checks run after the test keys are gone).
RULES = [
    ("api_keys.db", "api_keys", "label = 'test-crypto'",
     "keys created by the crypto-deposit tests"),
    ("crypto_deposits.db", "deposits",
     f"sender_address IN ({','.join('?' * len(FAKE_SENDERS))}) OR api_key LIKE 'apk_test%'",
     "fake deposits from tests (placeholder senders, test keys)"),
    ("discovery_engine.db", "scout_conversions", "user_agent = 'test-agent' AND caller_ip = '1.2.3.4'",
     "conversions recorded by the scout tests"),
    ("accounts.db", "accounts", "email LIKE '%@example.com'",
     "test accounts on the reserved example.com domain"),
    ("email_queue.db", "email_queue", "email LIKE '%@example.com'",
     "queued mail to the reserved example.com domain"),
    ("agent_network.db", "subscribers", "email LIKE '%@example.com'",
     "test newsletter subscribers"),
]

# Rows whose api_key names a key that does not exist in api_keys.api_keys.
ORPHAN_KEY_TABLES = [
    ("api_keys.db", "daily_spend"),
    ("crypto_deposits.db", "deposits"),
    ("crypto_deposits.db", "deposit_addresses"),
    ("crypto_deposits.db", "pending_deposits"),
    ("notifications.db", "notifications"),
    ("webhook_dispatch.db", "user_webhooks"),
    ("accounts.db", "account_keys"),
]


def counts(db: Path) -> dict:
    with closing(sqlite3.connect(db)) as c:
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}


def main(src: Path, dest: Path) -> int:
    if not src.is_dir():
        sys.exit(f"source {src} is not a directory")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.glob("*.db")):
        sys.exit(f"{dest} already has databases; refusing to overwrite")
    for db in sorted(src.glob("*.db")):
        shutil.copy2(db, dest / db.name)

    before = {db.name: counts(db) for db in sorted(dest.glob("*.db"))}
    removed = []

    def run(db_name, table, where, reason, params=()):
        db = dest / db_name
        if not db.exists() or table not in before.get(db_name, {}):
            return
        with closing(sqlite3.connect(db)) as c:
            if db_name == "api_keys.db":
                where = where.replace("keys.api_keys", "main.api_keys")
            else:
                c.execute("ATTACH DATABASE ? AS keys", (str(dest / "api_keys.db"),))
            n = c.execute(f'DELETE FROM "{table}" WHERE {where}', params).rowcount
            c.commit()
        removed.append({"db": db_name, "table": table, "rows": n, "reason": reason})

    for db_name, table, where, reason in RULES:
        params = FAKE_SENDERS if "sender_address IN" in where else ()
        run(db_name, table, where, reason, params)
    for db_name, table in ORPHAN_KEY_TABLES:
        run(db_name, table, "api_key NOT IN (SELECT key FROM keys.api_keys)",
            "references an API key that does not exist")

    after, bad = {}, []
    for db in sorted(dest.glob("*.db")):
        with closing(sqlite3.connect(db)) as c:
            if c.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                bad.append(db.name)
            c.execute("VACUUM")
        after[db.name] = counts(db)

    report = {
        "source": str(src), "dest": str(dest),
        "cleaned_at": datetime.now(timezone.utc).isoformat(),
        "removed": removed,
        "tables": {f"{d}:{t}": {"before": before[d][t], "after": after[d][t]} for d in before for t in before[d]},
        "integrity_failures": bad,
        "untouched_on_purpose": ["billing_audit.db:billing_audit"],
    }
    (dest / "cleanup-report.json").write_text(json.dumps(report, indent=2))
    for r in removed:
        print(f"{r['rows']:6}  {r['db']}:{r['table']}  ({r['reason']})")
    print(f"total removed: {sum(r['rows'] for r in removed)}; integrity failures: {bad or 'none'}")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()))
