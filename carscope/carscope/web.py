"""Local web dashboard — the primary modern UI.

Runs a small HTTP server on your Mac (stdlib only, no extra dependencies) and
opens it in your browser. Everything stays on your machine; nothing is sent
anywhere except, if you use the AI features, your prompt to the Claude API.

    python main.py web

Connection is managed from the UI (enter the adapter port, click Connect), so
the server starts fine with no car attached. One OBD connection is held open
and all vehicle queries are serialized through a lock, since the adapter can
only answer one request at a time.
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional

from . import ai, connection, diagnostics, live, tuning

ASSETS = Path(__file__).parent / "web_assets"

_lock = threading.Lock()
_conn = None  # live python-OBD connection, or None when disconnected


def _status() -> dict:
    with _lock:
        if _conn is None:
            return {"connected": False, "info": None}
        return {"connected": True, "info": connection.describe(_conn)}


def _connect(port: Optional[str], baud: Optional[int]) -> dict:
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            finally:
                _conn = None
        _conn = connection.open_persistent(port or None, baud or None)
        return {"connected": True, "info": connection.describe(_conn)}


def _disconnect() -> dict:
    global _conn
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            finally:
                _conn = None
    return {"connected": False, "info": None}


def _require_conn():
    if _conn is None:
        raise RuntimeError("Not connected. Connect to the vehicle first.")
    return _conn


def _live() -> dict:
    with _lock:
        readings = live.snapshot(_require_conn())
    return {"readings": [{"name": r.name, "value": r.value, "unit": r.unit} for r in readings]}


def _codes() -> dict:
    with _lock:
        report = diagnostics.read_report(_require_conn())

    def rows(items):
        return [{"code": d.code, "system": d.system, "description": d.description} for d in items]

    return {
        "mil_on": report.mil_on,
        "dtc_count": report.dtc_count,
        "stored": rows(report.stored),
        "pending": rows(report.pending),
        "permanent": rows(report.permanent),
        "clean": report.is_clean,
    }


def _clear(confirm: bool) -> dict:
    if confirm is not True:
        raise RuntimeError("Confirmation required.")
    with _lock:
        ok = diagnostics.clear_codes(_require_conn())
    return {"cleared": ok}


def _explain(vehicle: Optional[str]) -> dict:
    if not ai.is_available():
        return {"error": ai.unavailable_reason()}
    from .cli import _build_explain_prompt
    with _lock:
        conn = _require_conn()
        report = diagnostics.read_report(conn)
        if report.is_clean:
            return {"analysis": "No trouble codes present — nothing to interpret."}
        frame = diagnostics.read_freeze_frame(conn)
        snap = live.snapshot(conn)
    return {"analysis": ai.interpret(_build_explain_prompt(report, frame, snap), vehicle=vehicle)}


def _tune(path: str, target: Optional[float], explain: bool, vehicle: Optional[str]) -> dict:
    if not path:
        raise RuntimeError("Give the path to a CSV datalog on this Mac.")
    data = tuning.load_log(Path(path).expanduser())
    if not data.rows:
        raise RuntimeError("Log is empty or unreadable.")
    if not data.mapping.get("afr"):
        raise RuntimeError("No AFR/lambda column found in that log.")
    if target is None and not data.mapping.get("afr_target"):
        raise RuntimeError("No target-AFR column found — set a target AFR.")
    grid = tuning.build_afr_grid(data, target_const=target)
    events = tuning.find_knock_events(data)
    out = {
        "summary": tuning.summarize(data),
        "grid": tuning.grid_to_dict(grid),
        "events": [
            {"row": e.row_index, "value": e.value, "rpm": e.rpm, "load": e.load, "timing": e.timing}
            for e in events[:50]
        ],
        "event_count": len(events),
    }
    if explain:
        if not ai.is_available():
            out["analysis_error"] = ai.unavailable_reason()
        else:
            body = tuning.build_tuning_prompt(data, grid, events)
            out["analysis"] = ai.interpret(body, vehicle=vehicle, system=tuning.TUNING_SYSTEM)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def _send(self, status: int, body: bytes, ctype: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj: dict, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def _serve_asset(self, name: str) -> None:
        # Only files directly inside web_assets are servable (no traversal).
        safe = (ASSETS / name).resolve()
        if not str(safe).startswith(str(ASSETS.resolve())) or not safe.is_file():
            self._json({"error": "not found"}, 404)
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "text/javascript",
            ".svg": "image/svg+xml",
        }.get(safe.suffix, "application/octet-stream")
        self._send(200, safe.read_bytes(), ctype)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/":
                self._serve_asset("index.html")
            elif path == "/api/status":
                self._json(_status())
            elif path == "/api/live":
                self._json(_live())
            elif path == "/api/codes":
                self._json(_codes())
            elif path.startswith("/assets/"):
                self._serve_asset(path[len("/assets/"):])
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001 - report to the page, keep serving
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}") if length else {}
        except json.JSONDecodeError:
            self._json({"error": "invalid JSON"}, 400)
            return
        try:
            if path == "/api/connect":
                self._json(_connect(body.get("port"), body.get("baud")))
            elif path == "/api/disconnect":
                self._json(_disconnect())
            elif path == "/api/clear":
                self._json(_clear(body.get("confirm")))
            elif path == "/api/explain":
                self._json(_explain(body.get("vehicle")))
            elif path == "/api/tune":
                self._json(_tune(body.get("path", ""), body.get("target"),
                                 bool(body.get("explain")), body.get("vehicle")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": str(e)}, 500)


def serve(port_str: Optional[str] = None, baud: Optional[int] = None,
          host: str = "127.0.0.1", http_port: int = 8765, open_browser: bool = True) -> int:
    global _conn
    # Optionally pre-connect if a port was passed on the command line.
    if port_str:
        try:
            _connect(port_str, baud)
        except Exception as e:  # noqa: BLE001 - UI can still connect manually
            print(f"(couldn't pre-connect: {e})")

    server = ThreadingHTTPServer((host, http_port), Handler)
    url = f"http://localhost:{http_port}"
    print(f"CarScope dashboard: {url}   (Ctrl-C to stop)")
    if host == "0.0.0.0":
        print("  Listening on all interfaces — reachable from other devices on your network.")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard.")
    finally:
        server.server_close()
        _disconnect()
    return 0
