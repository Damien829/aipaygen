"""Every SQLite database the code opens must be backed up by Litestream."""
import re
from pathlib import Path

CORE = Path(__file__).resolve().parent.parent
CONFIG = CORE.parent / "deploy" / "litestream.yml"
SKIP_DIRS = {".venv", "tests", "sdk", "examples", "products", "docs", "scripts"}


def _code_dbs():
    names = set()
    for p in CORE.rglob("*.py"):
        if SKIP_DIRS & set(p.relative_to(CORE).parts):
            continue
        names |= set(re.findall(r"[\"']([a-z0-9_]+\.db)[\"']", p.read_text(errors="ignore")))
    return {n for n in names if "test" not in n and "example" not in n}


def test_every_database_is_replicated():
    backed_up = set(re.findall(r"^  - path: /data/([a-z0-9_]+\.db)$", CONFIG.read_text(), re.M))
    missing = _code_dbs() - backed_up
    assert not missing, f"add these to deploy/litestream.yml: {sorted(missing)}"
