"""Diagnostic trouble codes (DTCs) and readiness status.

All of this is standard OBD-II — Mode 03 (stored codes), Mode 07 (pending),
Mode 0A (permanent), and Mode 04 (clear). Nothing here is vehicle-brand-locked;
it's the same data any compliant tool reads off the bus.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

try:
    import obd
except ImportError:  # pragma: no cover - CLI still loads for --help
    obd = None  # type: ignore


@dataclass
class DTC:
    code: str
    description: str

    @property
    def system(self) -> str:
        """Rough subsystem from the first letter of the code."""
        return {
            "P": "Powertrain",
            "C": "Chassis",
            "B": "Body",
            "U": "Network / Communication",
        }.get(self.code[:1].upper(), "Unknown")


@dataclass
class DiagnosticReport:
    stored: list[DTC] = field(default_factory=list)
    pending: list[DTC] = field(default_factory=list)
    permanent: list[DTC] = field(default_factory=list)
    mil_on: Optional[bool] = None  # Malfunction Indicator Lamp ("check engine")
    dtc_count: Optional[int] = None

    @property
    def is_clean(self) -> bool:
        return not (self.stored or self.pending or self.permanent)


def _query_codes(conn: "obd.OBD", command) -> list[DTC]:
    if command not in conn.supported_commands:
        return []
    resp = conn.query(command)
    if resp.is_null() or not resp.value:
        return []
    out: list[DTC] = []
    for item in resp.value:
        # python-OBD returns (code, description) tuples.
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            code, desc = item[0], item[1]
        else:
            code, desc = str(item), ""
        out.append(DTC(code=code or "UNKNOWN", description=desc or "(no description)"))
    return out


def read_report(conn: "obd.OBD") -> DiagnosticReport:
    """Read stored/pending/permanent codes plus MIL status in one pass."""
    report = DiagnosticReport()
    report.stored = _query_codes(conn, obd.commands.GET_DTC)
    report.pending = _query_codes(conn, obd.commands.GET_CURRENT_DTC)

    # Permanent DTCs (Mode 0A) aren't in every python-OBD build; guard for it.
    perm_cmd = getattr(obd.commands, "GET_PERMANENT_DTC", None)
    if perm_cmd is not None:
        report.permanent = _query_codes(conn, perm_cmd)

    status_cmd = obd.commands.STATUS
    if status_cmd in conn.supported_commands:
        status = conn.query(status_cmd)
        if not status.is_null() and status.value is not None:
            report.mil_on = bool(getattr(status.value, "MIL", False))
            report.dtc_count = getattr(status.value, "DTC_count", None)
    return report


def clear_codes(conn: "obd.OBD") -> bool:
    """Clear DTCs and turn off the MIL (Mode 04).

    This is destructive: it erases stored codes AND freeze-frame data, and
    resets readiness monitors. Caller is responsible for confirming intent.
    Permanent (Mode 0A) codes will NOT clear until the fault self-heals over
    several drive cycles — that's by design, not a failure.
    """
    cmd = obd.commands.CLEAR_DTC
    if cmd not in conn.supported_commands:
        raise RuntimeError("This vehicle/adapter doesn't expose the clear-codes command.")
    resp = conn.query(cmd)
    return not resp.is_null()


def read_freeze_frame(conn: "obd.OBD") -> dict:
    """Pull whatever freeze-frame (Mode 02) PIDs the vehicle exposes.

    Freeze frame is the snapshot of sensor values captured when the code set —
    often the single most useful clue for diagnosis.
    """
    frame: dict = {}
    for cmd in conn.supported_commands:
        name = getattr(cmd, "name", "")
        if name.startswith("DTC_"):  # python-OBD prefixes freeze-frame PIDs with DTC_
            resp = conn.query(cmd)
            if not resp.is_null():
                frame[name] = str(resp.value)
    return frame
