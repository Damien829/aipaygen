"""Native desktop UI for CarScope (Tkinter).

A real Mac window — not a browser tab — built on Tkinter, which ships with
Python, so there's nothing extra to install. Launch it with:

    python main.py gui

All vehicle I/O runs on a background worker thread; the UI thread only ever
reads results off a queue, so the window never freezes while the adapter is
being queried (Tkinter is not thread-safe, so we never touch widgets from the
worker).
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Optional

from . import ai, connection, diagnostics, live, tuning

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # pragma: no cover - headless / no Tk build
    tk = None  # type: ignore


class _Worker(threading.Thread):
    """Owns the OBD connection and runs all blocking vehicle calls off-thread."""

    def __init__(self, results: "queue.Queue"):
        super().__init__(daemon=True)
        self.cmds: "queue.Queue" = queue.Queue()
        self.results = results
        self.conn = None
        self._stop = False

    def post(self, action: str, **kwargs) -> None:
        self.cmds.put((action, kwargs))

    def run(self) -> None:
        while not self._stop:
            action, kwargs = self.cmds.get()
            try:
                handler = getattr(self, f"_do_{action}", None)
                if handler is None:
                    continue
                handler(**kwargs)
            except Exception as e:  # noqa: BLE001 - report to UI, keep worker alive
                self.results.put(("error", {"action": action, "message": str(e)}))

    # --- command handlers (worker thread) ---
    def _do_connect(self, port: Optional[str], baud: Optional[int]) -> None:
        self._raw_close()
        if connection.obd is None:
            raise connection.ConnectionError(
                "The 'obd' package isn't installed. pip install -r requirements.txt"
            )
        kwargs: dict = {"fast": False, "timeout": 30}
        if port:
            kwargs["portstr"] = port
        if baud:
            kwargs["baudrate"] = baud
        conn = connection.obd.OBD(**kwargs)
        if not conn.is_connected():
            status = str(conn.status())
            conn.close()
            raise connection.ConnectionError(f"Not connected (adapter status: {status}).")
        self.conn = conn
        self.results.put(("connected", connection.describe(conn)))

    def _do_disconnect(self) -> None:
        self._raw_close()
        self.results.put(("disconnected", {}))

    def _do_snapshot(self) -> None:
        if not self.conn:
            return
        readings = live.snapshot(self.conn)
        self.results.put(("live", {"readings": readings}))

    def _do_codes(self) -> None:
        if not self.conn:
            return
        self.results.put(("codes", {"report": diagnostics.read_report(self.conn)}))

    def _do_clear(self) -> None:
        if not self.conn:
            return
        ok = diagnostics.clear_codes(self.conn)
        self.results.put(("cleared", {"ok": ok}))

    def _do_analyze(self, path: str, target: Optional[float]) -> None:
        data = tuning.load_log(Path(path))
        grid = tuning.build_afr_grid(data, target_const=target)
        events = tuning.find_knock_events(data)
        text = tuning.format_grid(grid)
        self.results.put(
            ("analysis", {"text": text, "events": len(events), "summary": tuning.summarize(data)})
        )

    def _raw_close(self) -> None:
        if self.conn:
            try:
                self.conn.close()
            finally:
                self.conn = None


class App:
    LIVE_INTERVAL_MS = 750

    def __init__(self, root, default_port: Optional[str], default_baud: Optional[int]):
        self.root = root
        self.results: "queue.Queue" = queue.Queue()
        self.worker = _Worker(self.results)
        self.worker.start()
        self.live_on = False
        self.default_port = default_port or ""
        self.default_baud = default_baud

        root.title("CarScope")
        root.geometry("760x560")
        self._build()
        self.root.after(100, self._pump)

    # --- UI construction ---
    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")
        ttk.Label(top, text="Adapter port:").pack(side="left")
        self.port_var = tk.StringVar(value=self.default_port)
        ttk.Entry(top, textvariable=self.port_var, width=34).pack(side="left", padx=6)
        self.connect_btn = ttk.Button(top, text="Connect", command=self._toggle_connect)
        self.connect_btn.pack(side="left")
        self.status = ttk.Label(top, text="Not connected", foreground="#b00")
        self.status.pack(side="left", padx=12)

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Live tab
        live_tab = ttk.Frame(nb, padding=10)
        nb.add(live_tab, text="Live data")
        self.live_btn = ttk.Button(live_tab, text="Start live", command=self._toggle_live,
                                    state="disabled")
        self.live_btn.pack(anchor="w")
        self.live_box = tk.Text(live_tab, height=18, font=("Menlo", 12))
        self.live_box.pack(fill="both", expand=True, pady=8)

        # Codes tab
        codes_tab = ttk.Frame(nb, padding=10)
        nb.add(codes_tab, text="Trouble codes")
        row = ttk.Frame(codes_tab)
        row.pack(fill="x")
        self.codes_btn = ttk.Button(row, text="Read codes", command=lambda: self.worker.post("codes"),
                                    state="disabled")
        self.codes_btn.pack(side="left")
        self.clear_btn = ttk.Button(row, text="Clear codes…", command=self._clear_codes,
                                    state="disabled")
        self.clear_btn.pack(side="left", padx=6)
        self.codes_box = tk.Text(codes_tab, height=18, font=("Menlo", 12))
        self.codes_box.pack(fill="both", expand=True, pady=8)

        # Tuning tab
        tune_tab = ttk.Frame(nb, padding=10)
        nb.add(tune_tab, text="Tuning log")
        trow = ttk.Frame(tune_tab)
        trow.pack(fill="x")
        ttk.Button(trow, text="Open log…", command=self._open_log).pack(side="left")
        ttk.Label(trow, text="Target AFR:").pack(side="left", padx=(12, 2))
        self.target_var = tk.StringVar(value="12.8")
        ttk.Entry(trow, textvariable=self.target_var, width=8).pack(side="left")
        self.tune_box = tk.Text(tune_tab, height=18, font=("Menlo", 11))
        self.tune_box.pack(fill="both", expand=True, pady=8)

    # --- actions (UI thread) ---
    def _connected(self) -> bool:
        return self.connect_btn["text"] == "Disconnect"

    def _toggle_connect(self) -> None:
        if self._connected():
            self.live_on = False
            self.worker.post("disconnect")
        else:
            self.status.config(text="Connecting…", foreground="#a60")
            baud = self.default_baud
            self.worker.post("connect", port=self.port_var.get().strip() or None, baud=baud)

    def _toggle_live(self) -> None:
        self.live_on = not self.live_on
        self.live_btn.config(text="Stop live" if self.live_on else "Start live")
        if self.live_on:
            self.worker.post("snapshot")

    def _clear_codes(self) -> None:
        if messagebox.askyesno(
            "Clear trouble codes?",
            "This erases stored codes AND freeze-frame data and resets readiness "
            "monitors. This cannot be undone.\n\nProceed?",
        ):
            self.worker.post("clear")

    def _open_log(self) -> None:
        path = filedialog.askopenfilename(
            title="Open tuning datalog", filetypes=[("CSV", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            target = float(self.target_var.get())
        except ValueError:
            target = None
        self.tune_box.delete("1.0", "end")
        self.tune_box.insert("end", "Analyzing…\n")
        self.worker.post("analyze", path=path, target=target)

    # --- result pump (UI thread) ---
    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.results.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    def _handle(self, kind: str, payload: dict) -> None:
        if kind == "connected":
            self.connect_btn.config(text="Disconnect")
            for b in (self.live_btn, self.codes_btn, self.clear_btn):
                b.config(state="normal")
            self.status.config(
                text=f"Connected · {payload.get('protocol', '')}", foreground="#070"
            )
        elif kind == "disconnected":
            self.connect_btn.config(text="Connect")
            for b in (self.live_btn, self.codes_btn, self.clear_btn):
                b.config(state="disabled")
            self.live_btn.config(text="Start live")
            self.status.config(text="Not connected", foreground="#b00")
        elif kind == "live":
            self._show_live(payload["readings"])
            if self.live_on:
                self.root.after(self.LIVE_INTERVAL_MS, lambda: self.worker.post("snapshot"))
        elif kind == "codes":
            self._show_codes(payload["report"])
        elif kind == "cleared":
            messagebox.showinfo("Clear codes", "Codes cleared." if payload["ok"]
                                else "Clear sent, but no confirmation received.")
            self.worker.post("codes")
        elif kind == "analysis":
            s = payload["summary"]
            self.tune_box.delete("1.0", "end")
            self.tune_box.insert("end", f"Samples: {s['samples']}   "
                                        f"Channels: {', '.join(s['channels_found']) or 'none'}\n")
            self.tune_box.insert("end", f"Knock/retard events: {payload['events']}\n\n")
            self.tune_box.insert("end", payload["text"])
        elif kind == "error":
            self.status.config(text="Not connected", foreground="#b00")
            self.connect_btn.config(text="Connect")
            messagebox.showerror("CarScope", payload["message"])

    def _show_live(self, readings) -> None:
        self.live_box.delete("1.0", "end")
        for r in readings:
            val = "—" if r.value is None else f"{r.value:g}"
            self.live_box.insert("end", f"{r.name:26}{val:>12} {r.unit}\n")

    def _show_codes(self, report) -> None:
        self.codes_box.delete("1.0", "end")
        if report.mil_on is not None:
            self.codes_box.insert("end", f"Check-engine light: {'ON' if report.mil_on else 'off'}\n\n")
        shown = False
        for title, items in (("Stored", report.stored), ("Pending", report.pending),
                             ("Permanent", report.permanent)):
            if items:
                shown = True
                self.codes_box.insert("end", f"{title}:\n")
                for d in items:
                    self.codes_box.insert("end", f"  {d.code}  [{d.system}]  {d.description}\n")
                self.codes_box.insert("end", "\n")
        if not shown:
            self.codes_box.insert("end", "No trouble codes found.\n")


def launch(port: Optional[str] = None, baud: Optional[int] = None) -> int:
    if tk is None:
        print("Tkinter isn't available in this Python build.\n"
              "On macOS, the python.org installer includes it; test with: python -m tkinter")
        return 1
    root = tk.Tk()
    App(root, default_port=port, default_baud=baud)
    root.mainloop()
    return 0
