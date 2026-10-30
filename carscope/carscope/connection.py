"""Adapter connection handling.

Wraps python-OBD so the rest of CarScope doesn't care whether the ELM327 is
plugged in over USB, paired over Bluetooth, or reachable over Wi-Fi. On macOS
the adapter shows up as a serial device under /dev/tty.* (USB/Bluetooth) or as
a TCP endpoint (Wi-Fi adapters, usually 192.168.0.10:35000).
"""

from __future__ import annotations

import glob
import sys
from contextlib import contextmanager
from typing import Iterator, Optional

try:
    import obd
except ImportError:  # pragma: no cover - surfaced as a friendly message in cli
    obd = None


class ConnectionError(RuntimeError):
    """Raised when we can't establish a usable link to the vehicle."""


def _require_obd() -> None:
    if obd is None:
        raise ConnectionError(
            "The 'obd' package isn't installed. Run:  pip install -r requirements.txt"
        )


def list_candidate_ports() -> list[str]:
    """Best-effort list of serial ports an ELM327 might be on (macOS first)."""
    patterns = [
        "/dev/tty.usbserial*",  # common USB ELM327 on macOS
        "/dev/tty.OBDII*",      # some Bluetooth adapters
        "/dev/tty.*OBD*",
        "/dev/tty.Bluetooth*",
        "/dev/cu.usbserial*",
        "/dev/ttyUSB*",         # Linux, in case you run it on a Pi later
    ]
    found: list[str] = []
    for pat in patterns:
        found.extend(glob.glob(pat))
    # De-dupe while preserving order.
    return list(dict.fromkeys(found))


@contextmanager
def connect(
    portstr: Optional[str] = None,
    baudrate: Optional[int] = None,
    fast: bool = False,
    timeout: float = 30.0,
) -> Iterator["obd.OBD"]:
    """Open a connection to the vehicle, yielding a live python-OBD object.

    portstr: explicit port (e.g. "/dev/tty.usbserial-1420" or
             "socket://192.168.0.10:35000" for a Wi-Fi adapter). If None,
             python-OBD auto-detects.
    Used as a context manager so the port is always closed cleanly.
    """
    _require_obd()

    kwargs: dict = {"fast": fast, "timeout": timeout}
    if portstr:
        kwargs["portstr"] = portstr
    if baudrate:
        kwargs["baudrate"] = baudrate

    conn = obd.OBD(**kwargs)
    if not conn.is_connected():
        status = conn.status()
        hints = list_candidate_ports()
        hint_text = (
            f"\nSerial ports that look like an adapter: {hints}"
            if hints
            else "\nNo adapter-looking serial ports found."
        )
        conn.close()
        raise ConnectionError(
            f"Could not connect to the vehicle (adapter status: {status}).\n"
            "Checklist:\n"
            "  - Key in ON / engine running so the ECU is awake.\n"
            "  - Adapter firmly seated in the OBD-II port.\n"
            "  - For Bluetooth/Wi-Fi: paired/joined before running this.\n"
            "  - Try passing an explicit --port.\n"
            f"{hint_text}"
        )
    try:
        yield conn
    finally:
        conn.close()


def describe(conn: "obd.OBD") -> dict:
    """Return a small dict describing the active connection."""
    return {
        "status": str(conn.status()),
        "port": conn.port_name(),
        "protocol": f"{conn.protocol_name()} ({conn.protocol_id()})",
        "supported_commands": len(conn.supported_commands),
    }
