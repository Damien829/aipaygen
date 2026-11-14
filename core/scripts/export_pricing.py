"""Export the price table v1 actually charges to pricing/core-routes.json.

v1 merged three sources at startup (app.py, route_pricing.py, a data default).
This loads the app, reads the merged table, and writes one JSON file that the
edge Worker uses to charge for core routes. Re-run only to re-derive from v1:

    python scripts/export_pricing.py ../pricing/core-routes.json
"""
import json
import os
import re
import sys
import tempfile
from decimal import Decimal

os.environ.setdefault("AIPAYGEN_DATA_DIR", tempfile.mkdtemp(prefix="aipaygen-pricing-"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402


def micro(price: str) -> int:
    return int(Decimal(price.lstrip("$")) * 1_000_000)


def main(out: str) -> None:
    routes = []
    for key, cfg in sorted(app.routes.items()):
        method, path = key.split(" ", 1)
        option = cfg.accepts[0] if isinstance(cfg.accepts, list) else cfg.accepts
        price = micro(str(option.price))
        desc = re.sub(r"\s*\(\$[0-9.]+(?:/call)?\)\s*$", "", cfg.description or "").strip()
        routes.append({"method": method, "path": path, "price_micro": price, "description": desc})
    doc = {
        "_comment": "Prices for core (v1) routes, charged by the edge Worker. Source of truth; edit here, not in code.",
        "currency": "USD",
        "unit": "micro-USD (1000000 = $1.00)",
        "routes": routes,
    }
    with open(out, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    print(f"{len(routes)} routes -> {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../pricing/core-routes.json")
    os._exit(0)
