"""Tuning datalog analysis for off-road / track / race use.

This reads a CSV datalog — from CarScope's own `log` command or exported from
your tuning software (rusEFI, Speeduino, MegaSquirt, HP Tuners, AEM, Haltech,
etc.) — and turns it into the views a tuner actually works from:

  - an AFR-error grid over RPM x load (where is it lean/rich, and by how much)
  - knock / ignition-retard events with the conditions they happened under
  - quick stats on fuel trims and the channels present

It is analysis only: it never writes to the vehicle or to a calibration. You
look at what it tells you, then make changes in your own tuning software. This
is the legal, DIY-friendly part of tuning — understanding your own data.
"""

from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Canonical channel -> keywords we'll look for in column headers (lowercased).
# First column whose name contains any keyword wins; override with --map.
CHANNEL_KEYWORDS: dict[str, list[str]] = {
    "rpm": ["rpm", "engine_speed", "revolutions"],
    "load": ["map", "manifold", "load", "boost", "tps", "throttle"],
    "afr": ["afr", "air_fuel", "lambda", "wideband", "o2_wide"],
    "afr_target": ["afr_target", "target_afr", "lambda_target", "target_lambda", "afrtgt"],
    "timing": ["timing", "ignition", "spark", "advance"],
    "knock": ["knock", "retard", "detonation", "ign_corr", "knk"],
    "stft": ["short_fuel_trim", "shrtft", "stft", "short_term"],
    "ltft": ["long_fuel_trim", "longft", "ltft", "long_term"],
}

GASOLINE_STOICH = 14.7  # for converting lambda -> AFR when only lambda is logged


@dataclass
class LogData:
    columns: list[str]
    rows: list[dict[str, str]]
    mapping: dict[str, Optional[str]] = field(default_factory=dict)

    def resolve(self, overrides: Optional[dict[str, str]] = None) -> None:
        overrides = overrides or {}
        lowered = {c.lower(): c for c in self.columns}
        for channel, keywords in CHANNEL_KEYWORDS.items():
            if channel in overrides:
                self.mapping[channel] = overrides[channel]
                continue
            match = None
            for low, orig in lowered.items():
                if any(k in low for k in keywords):
                    match = orig
                    break
            self.mapping[channel] = match

    def value(self, row: dict, channel: str) -> Optional[float]:
        col = self.mapping.get(channel)
        if not col or col not in row:
            return None
        raw = row[col]
        if raw is None or raw == "":
            return None
        try:
            v = float(raw)
        except ValueError:
            return None
        # If the AFR channel is actually lambda (values ~0.7-1.3), scale it up.
        if channel in ("afr", "afr_target") and 0.4 < v < 1.6:
            v *= GASOLINE_STOICH
        return v


def load_log(path: Path, overrides: Optional[dict[str, str]] = None) -> LogData:
    path = Path(path)
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames or []
        rows = list(reader)
    data = LogData(columns=columns, rows=rows)
    data.resolve(overrides)
    return data


def _bin_index(value: float, step: float, count: int) -> int:
    return max(0, min(count - 1, int(value // step)))


@dataclass
class AFRGrid:
    rpm_step: int
    rpm_bins: int
    load_step: float
    load_bins: int
    # cell -> list of AFR errors (actual - target); positive = lean.
    cells: dict[tuple[int, int], list[float]] = field(default_factory=dict)
    target_const: Optional[float] = None

    def mean_error(self, r: int, l: int) -> Optional[float]:
        vals = self.cells.get((r, l))
        return statistics.fmean(vals) if vals else None


def build_afr_grid(
    data: LogData,
    target_const: Optional[float] = None,
    rpm_step: int = 500,
    rpm_max: int = 8000,
    load_step: float = 10.0,
    load_max: float = 100.0,
) -> AFRGrid:
    rpm_bins = max(1, math.ceil(rpm_max / rpm_step))
    load_bins = max(1, math.ceil(load_max / load_step))
    grid = AFRGrid(rpm_step, rpm_bins, load_step, load_bins, target_const=target_const)

    for row in data.rows:
        rpm = data.value(row, "rpm")
        load = data.value(row, "load")
        afr = data.value(row, "afr")
        if rpm is None or load is None or afr is None:
            continue
        target = target_const if target_const is not None else data.value(row, "afr_target")
        if target is None:
            continue
        r = _bin_index(rpm, rpm_step, rpm_bins)
        l = _bin_index(load, load_step, load_bins)
        grid.cells.setdefault((r, l), []).append(afr - target)
    return grid


@dataclass
class KnockEvent:
    row_index: int
    rpm: Optional[float]
    load: Optional[float]
    value: float
    timing: Optional[float]


def find_knock_events(data: LogData, threshold: float = 0.5) -> list[KnockEvent]:
    """Rows where the knock/ignition-retard channel exceeds `threshold`
    (in whatever units the log uses — degrees of retard, a knock count, etc.)."""
    events: list[KnockEvent] = []
    if not data.mapping.get("knock"):
        return events
    for i, row in enumerate(data.rows):
        k = data.value(row, "knock")
        if k is not None and abs(k) >= threshold:
            events.append(
                KnockEvent(
                    row_index=i,
                    rpm=data.value(row, "rpm"),
                    load=data.value(row, "load"),
                    value=k,
                    timing=data.value(row, "timing"),
                )
            )
    return events


def summarize(data: LogData) -> dict:
    present = {ch: col for ch, col in data.mapping.items() if col}
    out: dict = {"samples": len(data.rows), "channels_found": present}
    for ch in ("rpm", "afr", "stft", "ltft", "timing"):
        vals = [v for row in data.rows if (v := data.value(row, ch)) is not None]
        if vals:
            out[ch] = {
                "min": round(min(vals), 2),
                "max": round(max(vals), 2),
                "mean": round(statistics.fmean(vals), 2),
            }
    return out


def format_grid(grid: AFRGrid) -> str:
    """Render the AFR-error grid, load (rows, high at top) x RPM (columns)."""
    lines = []
    header = "load\\rpm |" + "".join(
        f"{c * grid.rpm_step:>7}" for c in range(grid.rpm_bins)
    )
    lines.append(header)
    lines.append("-" * len(header))
    for l in range(grid.load_bins - 1, -1, -1):
        label = f"{int(l * grid.load_step):>7} |"
        cells = []
        for r in range(grid.rpm_bins):
            err = grid.mean_error(r, l)
            cells.append("     . " if err is None else f"{err:+7.2f}")
        lines.append(label + "".join(cells))
    lines.append("")
    lines.append("Cells show mean AFR error (actual - target). Positive = LEAN, negative = RICH.")
    lines.append("'.' = no data in that RPM/load region.")
    return "\n".join(lines)


TUNING_SYSTEM = (
    "You are an experienced engine calibrator helping the owner of an "
    "off-road / track / race vehicle interpret their own datalog. The vehicle "
    "is not for street/emissions-regulated use. Give practical, specific "
    "tuning guidance: identify lean or rich regions by RPM/load and the "
    "direction and rough magnitude to move fuel; call out any knock or "
    "ignition-retard events as the top priority and advise pulling timing or "
    "adding fuel in those cells; note where the data is too sparse to trust. "
    "Be conservative on anything safety- or engine-damage-related (knock, very "
    "lean under load). Do not give instructions for defeating emissions "
    "equipment; this is performance calibration only."
)


def build_tuning_prompt(data: LogData, grid: AFRGrid, events: list[KnockEvent]) -> str:
    lines = ["Datalog summary:"]
    summ = summarize(data)
    lines.append(f"  Samples: {summ['samples']}")
    lines.append(f"  Channels detected: {', '.join(summ['channels_found']) or 'none'}")
    for ch in ("rpm", "afr", "stft", "ltft", "timing"):
        if ch in summ:
            s = summ[ch]
            lines.append(f"  {ch}: min {s['min']}, mean {s['mean']}, max {s['max']}")
    if grid.target_const is not None:
        lines.append(f"\nTarget AFR used: {grid.target_const}")
    lines.append("\nAFR-error grid (actual - target; + lean, - rich):")
    lines.append(format_grid(grid))
    if events:
        lines.append(f"\nKnock / ignition-retard events: {len(events)} (showing up to 15)")
        for e in events[:15]:
            lines.append(
                f"  row {e.row_index}: value {e.value:+.2f} @ "
                f"rpm {e.rpm}, load {e.load}, timing {e.timing}"
            )
    else:
        lines.append("\nNo knock/ignition-retard channel found or no events over threshold.")
    lines.append(
        "\nPlease tell me: which cells to richen or lean out and roughly how much, "
        "any knock I need to address first, and what to log next to tighten this up."
    )
    return "\n".join(lines)
