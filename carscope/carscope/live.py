"""Live sensor data: one-shot snapshots and continuous CSV logging."""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import obd
except ImportError:  # pragma: no cover - CLI still loads for --help
    obd = None  # type: ignore

# A sensible default set of PIDs most vehicles support. Anything not supported
# by the connected vehicle is silently skipped.
DEFAULT_PIDS = [
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "INTAKE_TEMP",
    "THROTTLE_POS",
    "ENGINE_LOAD",
    "MAF",
    "FUEL_LEVEL",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "O2_B1S1",
    "CONTROL_MODULE_VOLTAGE",
]


@dataclass
class Reading:
    name: str
    value: Optional[float]
    unit: str


def _resolve_commands(conn: "obd.OBD", pid_names: list[str]) -> list:
    cmds = []
    for name in pid_names:
        cmd = getattr(obd.commands, name, None)
        if cmd is None:
            print(f"  (unknown PID '{name}', skipping)", file=sys.stderr)
            continue
        if cmd not in conn.supported_commands:
            continue
        cmds.append(cmd)
    return cmds


def snapshot(conn: "obd.OBD", pid_names: Optional[list[str]] = None) -> list[Reading]:
    """Read each requested PID once."""
    pid_names = pid_names or DEFAULT_PIDS
    readings: list[Reading] = []
    for cmd in _resolve_commands(conn, pid_names):
        resp = conn.query(cmd)
        if resp.is_null() or resp.value is None:
            readings.append(Reading(cmd.name, None, ""))
            continue
        value = resp.value
        magnitude = getattr(value, "magnitude", value)  # strip pint units if present
        unit = str(getattr(value, "units", "")) if hasattr(value, "units") else ""
        try:
            magnitude = float(magnitude)
        except (TypeError, ValueError):
            magnitude = None
        readings.append(Reading(cmd.name, magnitude, unit))
    return readings


def log_to_csv(
    conn: "obd.OBD",
    out_path: Path,
    pid_names: Optional[list[str]] = None,
    interval: float = 1.0,
    duration: Optional[float] = None,
) -> Path:
    """Stream PIDs to a CSV until Ctrl-C (or `duration` seconds elapse).

    One row per sample; a column per PID plus a timestamp. Supported PIDs are
    resolved once up front so the header stays stable.
    """
    pid_names = pid_names or DEFAULT_PIDS
    cmds = _resolve_commands(conn, pid_names)
    if not cmds:
        raise RuntimeError("None of the requested PIDs are supported by this vehicle.")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = ["timestamp", "elapsed_s"] + [c.name for c in cmds]

    start = time.time()
    samples = 0
    print(f"Logging {len(cmds)} PIDs to {out_path}  (Ctrl-C to stop)")
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        try:
            while True:
                now = time.time()
                elapsed = now - start
                row = [time.strftime("%Y-%m-%d %H:%M:%S"), f"{elapsed:.2f}"]
                for cmd in cmds:
                    resp = conn.query(cmd)
                    if resp.is_null() or resp.value is None:
                        row.append("")
                    else:
                        val = getattr(resp.value, "magnitude", resp.value)
                        row.append(val)
                writer.writerow(row)
                f.flush()
                samples += 1
                print(f"\r  {samples} samples ({elapsed:.0f}s)", end="", file=sys.stderr)
                if duration is not None and elapsed >= duration:
                    break
                # Keep cadence roughly on `interval` without drifting.
                sleep_for = interval - (time.time() - now)
                if sleep_for > 0:
                    time.sleep(sleep_for)
        except KeyboardInterrupt:
            print("\n  Stopped.", file=sys.stderr)
    print(f"Wrote {samples} samples to {out_path}")
    return out_path
