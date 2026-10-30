"""ProTune desktop app: a local web window for picking a folder, watching the
edits happen, comparing before/after and fine-tuning any photo.

Runs entirely on your computer (http://127.0.0.1), nothing is uploaded except the
small previews Claude looks at when AI fine-tuning is on.
"""

from __future__ import annotations

import io
import json
import os
import platform
import queue
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from collections import OrderedDict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from . import __version__
from .adjust import Adjustments, apply, linear_to_srgb
from .analyze import STYLES, auto_adjust
from .batch import (AiGuard, Options, collect, decide, detail_crop, output_path, read_sidecar,
                    render_and_save, write_sidecar)
from .io import load, preview, to_8bit

PORT = 8765
IS_MAC = platform.system() == "Darwin"
WEB = Path(__file__).with_name("web")

GROUPS = {
    "white_balance": ["temperature", "tint"],
    "exposure": ["exposure"],
    "tone": ["contrast", "highlights", "shadows", "whites", "blacks"],
    "presence": ["clarity", "vibrance", "saturation", "monochrome"],
    "detail": ["sharpening", "noise_reduction"],
    "effects": ["vignette"],
}


@dataclass
class Item:
    id: int
    src: Path
    out: Path
    status: str = "waiting"  # waiting | queued | working | done | failed
    source: str = ""  # auto | ai | manual
    notes: str = ""
    scene: str = ""
    error: str = ""
    settings: dict = field(default_factory=dict)
    version: int = 0

    def public(self) -> dict:
        return {"id": self.id, "name": self.src.name, "out": str(self.out), "status": self.status,
                "source": self.source, "notes": self.notes, "scene": self.scene, "error": self.error,
                "settings": self.settings, "version": self.version}


class Studio:
    """All app state. One worker thread does the heavy jobs, in order."""

    def __init__(self):
        self.lock = threading.RLock()
        self.items: list[Item] = []
        self.folder: Path | None = None
        self.out_dir: Path | None = None
        self.opts = Options()
        self.tasks: queue.Queue = queue.Queue()
        self.current = ""
        self.progress = {"done": 0, "total": 0, "started": 0.0}
        self.stop = threading.Event()
        self.messages: list[str] = []
        self.guard: AiGuard | None = None
        self.ai_note = ""
        self.cache = Path(tempfile.mkdtemp(prefix="protune-"))
        self._previews: OrderedDict[int, tuple] = OrderedDict()
        self._render_slots = threading.Semaphore(2)
        self.last_seen = time.time()
        threading.Thread(target=self._worker, daemon=True).start()

    # -- previews -----------------------------------------------------------
    def preview_of(self, item: Item):
        with self.lock:
            if item.id in self._previews:
                self._previews.move_to_end(item.id)
                return self._previews[item.id]
        photo = load(item.src, half=True)
        entry = (preview(photo.linear), photo.is_raw, photo.meta)
        self._remember(item.id, entry)
        return entry

    def _remember(self, item_id: int, entry: tuple):
        with self.lock:
            self._previews[item_id] = entry
            self._previews.move_to_end(item_id)
            while len(self._previews) > 16:  # ~8 MB each
                self._previews.popitem(last=False)

    def image(self, item: Item, kind: str, settings: dict | None = None) -> bytes:
        """JPEG for the window: the original or an edit (live settings when given)."""
        key = self.cache / f"{item.id}_{kind}_{item.version}.jpg"
        if settings is None and key.exists():
            return key.read_bytes()
        with self._render_slots:
            small, _, _ = self.preview_of(item)
            if kind == "before":
                srgb = linear_to_srgb(np.clip(small, 0, 1))
            else:
                adj = Adjustments.from_dict(settings if settings is not None else item.settings)
                srgb = apply(small, adj)
        buf = io.BytesIO()
        to_8bit(srgb).save(buf, "JPEG", quality=88)
        data = buf.getvalue()
        if settings is None:
            key.write_bytes(data)
        return data

    # -- jobs -----------------------------------------------------------------
    def open_folder(self, folder: Path, out_dir: Path | None, recursive: bool, skip_done: bool) -> dict:
        if not folder.is_dir():
            return {"error": f"Folder not found: {folder}"}
        out_dir = out_dir or default_output(folder)
        files = collect([folder], recursive, skip_dirs=(out_dir,))
        with self.lock:
            self.folder, self.out_dir = folder, out_dir
            self.items = []
            self._previews.clear()
            for i, f in enumerate(files):
                it = Item(i, f, output_path(f, out_dir, self.opts.fmt, folder))
                prev = read_sidecar(it.out) if skip_done and it.out.exists() else None
                if prev:
                    it.status, it.source = "done", prev.get("_source", "auto")
                    it.notes, it.scene = prev.get("_notes", ""), prev.get("_scene", "")
                    it.settings = Adjustments.from_dict(prev).to_dict()
                self.items.append(it)
        return {"ok": True, "count": len(files)}

    def start(self, ai: bool, style: str, fmt: str, long_edge: int | None, model: str | None):
        with self.lock:
            self.opts = Options(style=style, ai=ai, fmt=fmt, long_edge=long_edge)
            for it in self.items:
                it.out = output_path(it.src, self.out_dir, fmt, self.folder)
            todo = [it for it in self.items if it.status != "done"]
            for it in todo:
                it.status = "queued"
            self._set_guard(ai, model)
            self.stop.clear()
            self.progress = {"done": 0, "total": len(todo), "started": time.time()}
        for it in todo:
            self.tasks.put(("edit", it.id, None))

    def _set_guard(self, ai: bool, model: str | None):
        self.guard, self.ai_note = None, ""
        if ai:
            from .ai import make_backend

            try:
                self.guard = AiGuard(make_backend("claude-code", model or None))
            except Exception as e:
                self.ai_note = str(e)

    def queue(self, kind: str, ids: list[int], payload=None):
        with self.lock:
            self.stop.clear()
            if self.tasks.empty() and not self.current:
                self.progress = {"done": 0, "total": 0, "started": time.time()}
            self.progress["total"] += len(ids)
            if kind == "ai" and (self.guard is None or self.guard.active is None):
                self._set_guard(True, None)
            for i in ids:
                if 0 <= i < len(self.items):
                    self.items[i].status = "queued"
        for i in ids:
            self.tasks.put((kind, i, payload))

    def _worker(self):
        while True:
            kind, item_id, payload = self.tasks.get()
            item = self.items[item_id] if item_id < len(self.items) else None
            if item is None or self.stop.is_set():
                continue
            with self.lock:
                item.status, item.error = "working", ""
                self.current = item.src.name
            try:
                self._run(kind, item, payload)
                item.status = "done"
            except Exception as e:
                item.status, item.error = "failed", f"{type(e).__name__}: {e}"
                traceback.print_exc()
            finally:
                with self.lock:
                    item.version += 1
                    self.progress["done"] += 1
                    self.current = ""

    def _run(self, kind: str, item: Item, payload):
        if kind == "save":  # apply given settings
            photo = load(item.src)
            adj = Adjustments.from_dict(payload)
            render_and_save(photo, adj, item.out, self.opts)
            item.settings, item.source = adj.to_dict(), "manual"
            write_sidecar(item.out, adj, "manual", item.notes, item.scene)
            return
        photo = load(item.src)
        small = preview(photo.linear)
        self._remember(item.id, (small, photo.is_raw, photo.meta))
        backend = self.guard.active if (self.guard and (self.opts.ai or kind == "ai")) else None
        if kind == "ai" and backend is None:
            raise RuntimeError(self.ai_note or (self.guard.reason if self.guard else "") or "Claude is not available")
        try:
            adj, source, notes, scene = decide(photo, small, self.opts, backend, log=self._log)
            if backend is not None:
                self.guard.ok()
        except Exception as e:
            if backend is None:
                raise
            self.guard.failed(e)
            self.ai_note = str(e)
            self._log(f"{item.src.name}: Claude unavailable, used the automatic edit. ({e})")
            adj, source, notes, scene = decide(photo, small, self.opts, None)
        render_and_save(photo, adj, item.out, self.opts)
        write_sidecar(item.out, adj, source, notes, scene)
        item.settings, item.source, item.notes, item.scene = adj.to_dict(), source, notes, scene

    def _log(self, msg: str):
        with self.lock:
            self.messages = (self.messages + [msg.strip()])[-50:]

    def cancel(self):
        """Stop after the photo being worked on; queued ones go back to 'not started'."""
        self.stop.set()
        while True:
            try:
                kind, i, _ = self.tasks.get_nowait()
            except queue.Empty:
                break
            if kind == "edit" and i < len(self.items) and self.items[i].status == "queued":
                self.items[i].status = "waiting"

    def status(self) -> dict:
        from .ai import find_claude
        from .io import exiftool

        with self.lock:
            p = self.progress
            elapsed = time.time() - p["started"] if p["started"] else 0
            eta = elapsed / p["done"] * (p["total"] - p["done"]) if p["done"] and p["total"] > p["done"] else None
            busy = bool(self.current) or not self.tasks.empty()
            return {
                "version": __version__, "folder": str(self.folder or ""), "out_dir": str(self.out_dir or ""),
                "items": [it.public() for it in self.items], "busy": busy, "current": self.current,
                "progress": {**p, "eta": eta}, "messages": self.messages[-8:],
                "ai": {"installed": bool(find_claude()), "note": self.ai_note,
                       "stopped": bool(self.guard and self.guard.active is None)},
                "home": str(Path.home()), "exiftool": bool(exiftool()), "styles": sorted(STYLES), "groups": GROUPS, "mac": IS_MAC,
            }


def default_output(folder: Path) -> Path:
    """~/Pictures/ProTune/<folder name>: keeps edits off SD cards and out of the originals."""
    pics = Path.home() / "Pictures"
    return (pics if pics.exists() else Path.home()) / "ProTune" / (folder.name or "Photos")


def choose_folder(prompt: str) -> str | None:
    if not IS_MAC:
        return None
    script = ['-e', 'tell me to activate',
              '-e', f'POSIX path of (choose folder with prompt "{prompt}")']
    r = subprocess.run(["osascript", *script], capture_output=True, text=True)
    return r.stdout.strip() or None if r.returncode == 0 else None


def reveal(path: Path):
    if IS_MAC:
        subprocess.run(["open", str(path)])
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(path)])


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def make_handler(studio: Studio, token: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "ProTune"

        def log_message(self, *a):  # quiet
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, default=str).encode(), "application/json")

        def _allowed(self) -> bool:
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"):
                return False
            path = urlparse(self.path).path
            if not path.startswith("/api/") or path == "/api/ping":
                return True
            return self.headers.get("X-Token") == token or f"t={token}" in (urlparse(self.path).query or "")

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _item(self, i) -> Item | None:
            i = int(i)
            return studio.items[i] if 0 <= i < len(studio.items) else None

        def do_GET(self):
            if not self._allowed():
                return self._send(403, b"forbidden", "text/plain")
            studio.last_seen = time.time()
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                if parts == [""]:
                    html = (WEB / "index.html").read_text().replace("__TOKEN__", token)
                    return self._send(200, html.encode(), "text/html; charset=utf-8")
                if parts == ["api", "ping"]:
                    return self._json({"app": "protune"})
                if parts == ["api", "status"]:
                    return self._json(studio.status())
                if parts[:2] == ["api", "img"] and len(parts) >= 4:
                    it = self._item(parts[2])
                    if not it:
                        return self._json({"error": "no such photo"}, 404)
                    return self._send(200, studio.image(it, parts[3]), "image/jpeg")
                if parts[:2] == ["api", "auto"] and len(parts) == 3:
                    it = self._item(parts[2])
                    small, is_raw, _ = studio.preview_of(it)
                    return self._json(auto_adjust(small, is_raw, studio.opts.style).to_dict())
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._allowed():
                return self._send(403, b"forbidden", "text/plain")
            studio.last_seen = time.time()
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                b = self._body()
                if parts == ["api", "heartbeat"]:
                    return self._json({"ok": True})
                if parts == ["api", "choose"]:
                    p = choose_folder(b.get("prompt") or "Choose a folder")
                    return self._json({"path": p, "mac": IS_MAC})
                if parts == ["api", "open"]:
                    folder = Path(os.path.expanduser(b["folder"])).resolve()
                    out = Path(os.path.expanduser(b["out_dir"])).resolve() if b.get("out_dir") else None
                    return self._json(studio.open_folder(folder, out, bool(b.get("recursive")),
                                                         bool(b.get("skip_done", True))))
                if parts == ["api", "start"]:
                    studio.start(bool(b.get("ai")), b.get("style", "natural"), b.get("format", "jpg"),
                                 int(b["long_edge"]) if b.get("long_edge") else None, b.get("model"))
                    return self._json({"ok": True})
                if parts == ["api", "cancel"]:
                    studio.cancel()
                    return self._json({"ok": True})
                if parts[:2] == ["api", "render"] and len(parts) == 3:
                    it = self._item(parts[2])
                    return self._send(200, studio.image(it, "after", b.get("settings") or {}), "image/jpeg")
                if parts[:2] == ["api", "save"] and len(parts) == 3:
                    studio.queue("save", [int(parts[2])], b.get("settings") or {})
                    return self._json({"ok": True})
                if parts == ["api", "ai"]:
                    studio.queue("ai", [int(i) for i in b.get("ids", [])])
                    return self._json({"ok": True})
                if parts == ["api", "apply"]:
                    keys = [k for g in b.get("groups", []) for k in GROUPS.get(g, [])]
                    src = b.get("settings") or {}
                    for i in b.get("ids", []):
                        it = self._item(i)
                        if it and it.status == "done":
                            merged = {**(it.settings or {}), **{k: src[k] for k in keys if k in src}}
                            studio.queue("save", [it.id], merged)
                    return self._json({"ok": True})
                if parts == ["api", "reveal"]:
                    target = Path(b.get("path") or studio.out_dir or Path.home())
                    reveal(target if target.exists() else target.parent)
                    return self._json({"ok": True})
                if parts == ["api", "quit"]:
                    self._json({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
            except Exception as e:
                traceback.print_exc()
                return self._json({"error": str(e)}, 500)
            self._json({"error": "not found"}, 404)

    return Handler


def _already_running(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5) as s:
            s.sendall(b"GET /api/ping HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            return b"protune" in s.recv(4096)
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="protune-app", description="Open the ProTune window")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--idle-minutes", type=float, default=10,
                    help="quit after the window has been closed this long (0 = never)")
    args = ap.parse_args(argv)

    port_file = Path.home() / ".protune" / "app.json"
    try:  # second launch: just bring up the window of the running app
        info = json.loads(port_file.read_text())
        if _already_running(info["port"]):
            if not args.no_browser:
                webbrowser.open(info["url"])
            return 0
    except Exception:
        pass

    token = secrets.token_urlsafe(16)
    studio = Studio()
    server = None
    for port in [args.port] + list(range(args.port + 1, args.port + 20)):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(studio, token))
            break
        except OSError:
            continue
    if server is None:
        print("No free port for ProTune", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_port}/"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(json.dumps({"port": server.server_port, "url": url}))
    print(f"ProTune {__version__} running at {url}  (Ctrl+C to quit)", flush=True)

    def watchdog():  # quit when the window is gone and nothing is running
        while args.idle_minutes > 0:
            time.sleep(15)
            idle = time.time() - studio.last_seen
            busy = bool(studio.current) or not studio.tasks.empty()
            if idle > args.idle_minutes * 60 and not busy:
                server.shutdown()
                return

    threading.Thread(target=watchdog, daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        port_file.unlink(missing_ok=True)
        shutil.rmtree(studio.cache, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
