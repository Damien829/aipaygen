"""Raw CAN bus capture and decoding.

This is the deeper layer: instead of asking the ECU standardized OBD-II
questions, it listens to the raw CAN traffic on the bus — every frame, every
module — so you can find signals the standard PIDs never expose (door locks,
window state, custom sensors, etc.) on vehicles you own.

Hardware: a true USB-CAN interface, not an ELM327 (ELM327 firmware abstracts
the bus away and can't hand you raw frames). On a Mac the common path is a
CANable / CANtact-style adapter in `slcan` mode, which appears as a serial
device like /dev/tty.usbmodemXXXX. On a Raspberry Pi you'd typically use
SocketCAN (`interface="socketcan"`, `channel="can0"`).

Reading is passive and safe. Writing frames (transmit) is deliberately NOT
included here — injecting onto a live vehicle bus can affect its behavior, so
that stays out of this capture-only module by design.
"""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

try:
    import can
except ImportError:  # pragma: no cover - CLI still loads for --help
    can = None  # type: ignore


class CANError(RuntimeError):
    """Raised when the CAN interface can't be opened or used."""


def _require_can() -> None:
    if can is None:
        raise CANError(
            "The 'python-can' package isn't installed. Run:  pip install -r requirements.txt"
        )


@dataclass
class Frame:
    timestamp: float
    arb_id: int
    extended: bool
    data: bytes

    @property
    def id_hex(self) -> str:
        width = 8 if self.extended else 3
        return f"0x{self.arb_id:0{width}X}"

    @property
    def data_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in self.data)


def open_bus(
    channel: str,
    interface: str = "slcan",
    bitrate: int = 500000,
):
    """Open a CAN interface. Caller is responsible for closing it (use as a
    context manager via `with open_bus(...) as bus:` — python-can Bus supports it).

    Common vehicle bitrates: 500000 (high-speed powertrain CAN) and 125000
    (comfort/body CAN). If you see nothing, try the other one.
    """
    _require_can()
    try:
        return can.Bus(channel=channel, interface=interface, bitrate=bitrate)
    except Exception as e:  # python-can raises a variety of backend errors
        raise CANError(
            f"Couldn't open CAN interface (channel={channel!r}, "
            f"interface={interface!r}, bitrate={bitrate}): {e}\n"
            "Checklist:\n"
            "  - Adapter plugged in and in the right mode (slcan for CANable on a Mac).\n"
            "  - Correct serial device for --channel (ls /dev/tty.usbmodem*).\n"
            "  - Correct --bitrate for the bus you're tapping.\n"
            "  - On a Pi with SocketCAN: `sudo ip link set can0 up type can bitrate 500000` first."
        ) from e


def stream(bus, duration: Optional[float] = None) -> Iterator[Frame]:
    """Yield frames from the bus until Ctrl-C or `duration` seconds elapse."""
    start = time.time()
    while True:
        msg = bus.recv(timeout=1.0)
        if msg is not None:
            yield Frame(
                timestamp=msg.timestamp,
                arb_id=msg.arbitration_id,
                extended=bool(msg.is_extended_id),
                data=bytes(msg.data),
            )
        if duration is not None and (time.time() - start) >= duration:
            return


def sniff(
    channel: str,
    interface: str = "slcan",
    bitrate: int = 500000,
    duration: Optional[float] = None,
) -> None:
    """Live-print raw frames as they arrive (great for a quick look)."""
    with open_bus(channel, interface, bitrate) as bus:
        print(f"Listening on {channel} @ {bitrate} ({interface}).  Ctrl-C to stop.")
        print(f"{'time':>10}  {'id':>10}  dlc  data")
        start = time.time()
        count = 0
        try:
            for fr in stream(bus, duration):
                rel = fr.timestamp - start if fr.timestamp > 1e6 else fr.timestamp
                print(f"{rel:10.3f}  {fr.id_hex:>10}  {len(fr.data):>3}  {fr.data_hex}")
                count += 1
        except KeyboardInterrupt:
            pass
        print(f"\nCaptured {count} frames.", file=sys.stderr)


def log_to_csv(
    channel: str,
    out_path: Path,
    interface: str = "slcan",
    bitrate: int = 500000,
    duration: Optional[float] = None,
) -> Path:
    """Record raw frames to CSV: timestamp, id, extended flag, dlc, data (hex)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open_bus(channel, interface, bitrate) as bus, out_path.open(
        "w", newline=""
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "arb_id", "extended", "dlc", "data_hex"])
        count = 0
        print(f"Logging CAN frames to {out_path}  (Ctrl-C to stop)")
        try:
            for fr in stream(bus, duration):
                writer.writerow(
                    [f"{fr.timestamp:.6f}", fr.id_hex, int(fr.extended), len(fr.data), fr.data_hex]
                )
                count += 1
                if count % 50 == 0:
                    f.flush()
                    print(f"\r  {count} frames", end="", file=sys.stderr)
        except KeyboardInterrupt:
            pass
    print(f"\nWrote {count} frames to {out_path}")
    return out_path


@dataclass
class IdStats:
    arb_id: int
    extended: bool
    count: int = 0
    first_data: bytes = b""
    changing_bytes: set[int] = field(default_factory=set)
    _last: bytes = b""

    def observe(self, data: bytes) -> None:
        if self.count == 0:
            self.first_data = data
        else:
            for i in range(min(len(data), len(self._last))):
                if data[i] != self._last[i]:
                    self.changing_bytes.add(i)
        self._last = data
        self.count += 1


def survey(
    channel: str,
    interface: str = "slcan",
    bitrate: int = 500000,
    duration: float = 15.0,
) -> dict[int, IdStats]:
    """Listen for a while and summarize which arbitration IDs are active and
    which byte positions change — a fast first step in reverse-engineering a
    signal (wiggle a control, see which ID/byte moves).
    """
    stats: dict[int, IdStats] = {}
    with open_bus(channel, interface, bitrate) as bus:
        print(f"Surveying bus for {duration:.0f}s…  (Ctrl-C to stop early)")
        try:
            for fr in stream(bus, duration):
                st = stats.get(fr.arb_id)
                if st is None:
                    st = IdStats(arb_id=fr.arb_id, extended=fr.extended)
                    stats[fr.arb_id] = st
                st.observe(fr.data)
        except KeyboardInterrupt:
            pass
    return stats


def print_survey(stats: dict[int, IdStats]) -> None:
    if not stats:
        print("No frames seen. Wrong bitrate, wrong bus, or quiet ignition state?")
        return
    print(f"\n{'id':>10}  {'count':>7}  changing byte positions")
    for arb_id in sorted(stats):
        st = stats[arb_id]
        width = 8 if st.extended else 3
        changing = ",".join(str(i) for i in sorted(st.changing_bytes)) or "(static)"
        print(f"0x{arb_id:0{width}X}  {st.count:>7}  {changing}")
    print(f"\n{len(stats)} distinct IDs seen.")
