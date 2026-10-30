"""Command-line interface for CarScope.

Subcommands:
  scan    Connect and show adapter + vehicle info.
  codes   Read stored / pending / permanent trouble codes (+ freeze frame).
  clear   Clear trouble codes and turn off the check-engine light.
  live    Print a one-shot snapshot of live sensor values.
  log     Stream live sensor data to a CSV file.
  explain Read codes, then have Claude interpret them (needs ANTHROPIC_API_KEY).
  can     Raw CAN capture: sniff / log / survey (needs a USB-CAN adapter).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import ai, can_bus, connection, diagnostics, live


def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--port",
        default=None,
        help="Adapter port (e.g. /dev/tty.usbserial-1420 or "
        "socket://192.168.0.10:35000). Default: auto-detect.",
    )
    p.add_argument("--baud", type=int, default=None, help="Serial baud rate (optional).")


def _print_report(report: diagnostics.DiagnosticReport) -> None:
    if report.mil_on is not None:
        lamp = "ON" if report.mil_on else "off"
        count = f" ({report.dtc_count} codes)" if report.dtc_count is not None else ""
        print(f"Check-engine light: {lamp}{count}")

    def show(title: str, items: list[diagnostics.DTC]) -> None:
        print(f"\n{title}: {len(items)}")
        for d in items:
            print(f"  {d.code}  [{d.system}]  {d.description}")

    show("Stored codes", report.stored)
    show("Pending codes", report.pending)
    if report.permanent:
        show("Permanent codes", report.permanent)
    if report.is_clean:
        print("\nNo trouble codes found.")


def cmd_scan(args) -> int:
    with connection.connect(args.port, args.baud) as conn:
        info = connection.describe(conn)
        print("Connected.")
        for k, v in info.items():
            print(f"  {k}: {v}")
    return 0


def cmd_codes(args) -> int:
    with connection.connect(args.port, args.baud) as conn:
        report = diagnostics.read_report(conn)
        _print_report(report)
        if args.freeze and not report.is_clean:
            frame = diagnostics.read_freeze_frame(conn)
            if frame:
                print("\nFreeze frame (snapshot when the fault set):")
                for k, v in frame.items():
                    print(f"  {k}: {v}")
    return 0


def cmd_clear(args) -> int:
    if not args.yes:
        print(
            "This will erase stored codes AND freeze-frame data and reset "
            "readiness monitors.\nRe-run with --yes to confirm."
        )
        return 1
    with connection.connect(args.port, args.baud) as conn:
        ok = diagnostics.clear_codes(conn)
        print("Codes cleared." if ok else "Clear command sent but no confirmation received.")
    return 0 if ok else 2


def cmd_live(args) -> int:
    pids = args.pids.split(",") if args.pids else None
    with connection.connect(args.port, args.baud) as conn:
        for r in live.snapshot(conn, pids):
            val = "—" if r.value is None else f"{r.value:g}"
            print(f"  {r.name:24} {val:>10} {r.unit}")
    return 0


def cmd_log(args) -> int:
    pids = args.pids.split(",") if args.pids else None
    out = Path(args.out)
    with connection.connect(args.port, args.baud) as conn:
        live.log_to_csv(conn, out, pids, interval=args.interval, duration=args.duration)
    return 0


def cmd_explain(args) -> int:
    if not ai.is_available():
        print(f"AI interpretation unavailable: {ai.unavailable_reason()}", file=sys.stderr)
        return 3
    with connection.connect(args.port, args.baud) as conn:
        report = diagnostics.read_report(conn)
        _print_report(report)
        if report.is_clean:
            print("\nNothing to interpret — no codes present.")
            return 0
        frame = diagnostics.read_freeze_frame(conn)
        snap = live.snapshot(conn)

    body = _build_explain_prompt(report, frame, snap)
    print("\nAsking Claude to interpret…\n" + "-" * 60)
    analysis = ai.interpret(body, vehicle=args.vehicle)
    print(analysis)
    return 0


def cmd_can(args) -> int:
    common = dict(interface=args.interface, bitrate=args.bitrate)
    if args.can_command == "sniff":
        can_bus.sniff(args.channel, duration=args.duration, **common)
    elif args.can_command == "log":
        can_bus.log_to_csv(args.channel, Path(args.out), duration=args.duration, **common)
    elif args.can_command == "survey":
        stats = can_bus.survey(args.channel, duration=args.duration or 15.0, **common)
        can_bus.print_survey(stats)
    return 0


def _build_explain_prompt(report, frame, snap) -> str:
    lines = ["Trouble codes read from the vehicle:"]
    for title, items in (
        ("Stored", report.stored),
        ("Pending", report.pending),
        ("Permanent", report.permanent),
    ):
        for d in items:
            lines.append(f"  [{title}] {d.code} — {d.description}")
    if report.mil_on is not None:
        lines.append(f"\nCheck-engine light: {'ON' if report.mil_on else 'off'}")
    if frame:
        lines.append("\nFreeze-frame data (captured when a fault set):")
        for k, v in frame.items():
            lines.append(f"  {k}: {v}")
    if snap:
        lines.append("\nCurrent live readings:")
        for r in snap:
            if r.value is not None:
                lines.append(f"  {r.name}: {r.value:g} {r.unit}")
    lines.append(
        "\nPlease interpret these for me: what's likely wrong, ranked causes, "
        "and the specific next things I should test or inspect."
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="carscope",
        description="AI-assisted OBD-II diagnostics for vehicles you own.",
    )
    parser.add_argument("--version", action="version", version=f"carscope {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("scan", help="Connect and show adapter/vehicle info.")
    _add_common(p)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("codes", help="Read trouble codes.")
    _add_common(p)
    p.add_argument("--freeze", action="store_true", help="Also read freeze-frame data.")
    p.set_defaults(func=cmd_codes)

    p = sub.add_parser("clear", help="Clear trouble codes (turns off check-engine light).")
    _add_common(p)
    p.add_argument("--yes", action="store_true", help="Confirm the (destructive) clear.")
    p.set_defaults(func=cmd_clear)

    p = sub.add_parser("live", help="One-shot snapshot of live sensor values.")
    _add_common(p)
    p.add_argument("--pids", help="Comma-separated PID names (default: a common set).")
    p.set_defaults(func=cmd_live)

    p = sub.add_parser("log", help="Stream live data to CSV.")
    _add_common(p)
    p.add_argument("--out", default="carscope_log.csv", help="Output CSV path.")
    p.add_argument("--pids", help="Comma-separated PID names (default: a common set).")
    p.add_argument("--interval", type=float, default=1.0, help="Seconds between samples.")
    p.add_argument("--duration", type=float, default=None, help="Stop after N seconds.")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("explain", help="Read codes and have Claude interpret them.")
    _add_common(p)
    p.add_argument("--vehicle", help="Year/make/model/engine, to sharpen the analysis.")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("can", help="Raw CAN bus capture (needs a USB-CAN adapter).")
    can_sub = p.add_subparsers(dest="can_command", required=True)
    for name, help_text in (
        ("sniff", "Live-print raw frames."),
        ("log", "Record raw frames to CSV."),
        ("survey", "Summarize active IDs and which bytes change."),
    ):
        cp = can_sub.add_parser(name, help=help_text)
        cp.add_argument("--channel", required=True,
                        help="Interface channel (e.g. /dev/tty.usbmodem14201, or can0 on a Pi).")
        cp.add_argument("--interface", default="slcan",
                        help="python-can interface (default: slcan; socketcan on a Pi).")
        cp.add_argument("--bitrate", type=int, default=500000,
                        help="Bus bitrate (500000 powertrain, 125000 body is common).")
        cp.add_argument("--duration", type=float, default=None, help="Stop after N seconds.")
        if name == "log":
            cp.add_argument("--out", default="carscope_can.csv", help="Output CSV path.")
        cp.set_defaults(func=cmd_can)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (connection.ConnectionError, can_bus.CANError) as e:
        print(f"\nConnection error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001 - top-level guard for a friendly message
        print(f"\nError: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
