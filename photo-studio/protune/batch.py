"""The workflow shared by the command line and the Mac app: find photos, edit, save."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .adjust import Adjustments, apply
from .analyze import auto_adjust
from .io import RAW_EXTS, SUPPORTED, Photo, load, preview, resize_long_edge, save

SIDE_KEYS = ("_source", "_notes", "_scene")


@dataclass
class Options:
    style: str = "natural"
    ai: bool = False
    ai_passes: int = 2
    fmt: str = "jpg"  # jpg | tif | png
    quality: int = 95
    long_edge: int | None = None  # resize for web; None = full size


def collect(inputs: list[str | Path], recursive: bool = False, skip_dirs: tuple[Path, ...] = ()) -> list[Path]:
    """Photos to edit, in name order.

    - Hidden files are ignored (macOS leaves "._IMG_0001.CR2" junk on SD cards).
    - RAW+JPEG pairs: the RAW is used and its JPEG twin skipped, so one doesn't
      overwrite the other in the output folder.
    """
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            it = p.rglob("*") if recursive else p.iterdir()
            for f in it:
                if any(part.startswith(".") for part in f.relative_to(p).parts):
                    continue
                if any(d == f or d in f.parents for d in skip_dirs):
                    continue
                if f.is_file() and f.suffix.lower() in SUPPORTED:
                    files.append(f)
        elif p.is_file() and p.suffix.lower() in SUPPORTED and not p.name.startswith("."):
            files.append(p)
    raw_stems = {(f.parent, f.stem.lower()) for f in files if f.suffix.lower() in RAW_EXTS}
    keep = [f for f in files if f.suffix.lower() in RAW_EXTS or (f.parent, f.stem.lower()) not in raw_stems]
    return sorted(dict.fromkeys(keep), key=lambda f: (str(f.parent).lower(), f.name.lower()))


def output_path(src: Path, out_dir: Path, fmt: str, root: Path | None = None) -> Path:
    """Where the edit of `src` goes. Keeps subfolders, never points at the original."""
    rel = src.parent.relative_to(root) if root and root in src.parents else Path()
    out = out_dir / rel / f"{src.stem}.{fmt}"
    if out.resolve() == src.resolve():
        out = out.with_name(f"{src.stem}_edited.{fmt}")
    return out


def sidecar(out: Path) -> Path:
    return out.with_suffix(".json")


def read_sidecar(out: Path) -> dict | None:
    try:
        return json.loads(sidecar(out).read_text())
    except Exception:
        return None


def write_sidecar(out: Path, adj: Adjustments, source: str, notes: str = "", scene: str = "") -> None:
    d = adj.to_dict()
    d.update({"_source": source, "_notes": notes, "_scene": scene})
    sidecar(out).write_text(json.dumps(d, indent=2))


def detail_crop(linear: np.ndarray, size: int = 640) -> np.ndarray:
    """A 100% crop from the most detailed part of the photo, so noise and
    sharpness can be judged (a shrunken preview hides both)."""
    h, w = linear.shape[:2]
    if max(h, w) <= size * 1.5:
        return linear
    small = preview(linear, 256)
    y = small.mean(-1)
    g = np.abs(np.diff(y, axis=0))[:, :-1] + np.abs(np.diff(y, axis=1))[:-1, :]
    sh, sw = g.shape
    ch, cw = max(1, int(sh * size / h)), max(1, int(sw * size / w))
    best, by, bx = -1.0, 0, 0
    for yy in range(0, max(1, sh - ch), max(1, ch // 2)):
        for xx in range(0, max(1, sw - cw), max(1, cw // 2)):
            v = float(g[yy:yy + ch, xx:xx + cw].mean())
            if v > best:
                best, by, bx = v, yy, xx
    y0 = min(h - size, int(by * h / sh))
    x0 = min(w - size, int(bx * w / sw))
    return linear[y0:y0 + size, x0:x0 + size]


def decide(photo: Photo, small: np.ndarray, opts: Options, backend=None, log=print) -> tuple[Adjustments, str, str, str]:
    """Pick the settings for one photo. Returns (settings, source, notes, scene)."""
    adj = auto_adjust(small, photo.is_raw, opts.style)
    if backend is None:
        return adj, "auto", "", ""
    from .ai import ai_refine

    adj, notes, scene = ai_refine(small, adj, opts.style, opts.ai_passes, backend=backend, log=log,
                                  crop=detail_crop(photo.linear), meta=photo.meta)
    return adj, "ai", notes, scene


def render_and_save(photo: Photo, adj: Adjustments, out: Path, opts: Options) -> None:
    result = apply(photo.linear, adj)
    result = resize_long_edge(result, opts.long_edge)
    save(result, out, photo, opts.quality)


class AiGuard:
    """Stops asking Claude after repeated failures (e.g. the plan's usage limit was
    reached) so the rest of the batch isn't slowed down by calls that will fail."""

    def __init__(self, backend, max_failures: int = 2):
        self.backend, self.failures, self.max, self.reason = backend, 0, max_failures, ""

    @property
    def active(self):
        return self.backend if self.backend is not None and self.failures < self.max else None

    def ok(self):
        self.failures = 0

    def failed(self, e: Exception):
        self.failures += 1
        self.reason = str(e)


def process(src: Path, out: Path, opts: Options, guard: AiGuard | None = None, log=print) -> dict:
    """Edit one photo end to end. Never raises: problems are reported in the result."""
    try:
        photo = load(src)
        small = preview(photo.linear)
        backend = guard.active if guard else None
        try:
            adj, source, notes, scene = decide(photo, small, opts, backend, log)
            if backend is not None:
                guard.ok()
        except Exception as e:  # AI trouble: fall back to the automatic edit
            if backend is None:
                raise
            guard.failed(e)
            log(f"    AI unavailable ({e}); using the automatic edit")
            adj, source, notes, scene = decide(photo, small, opts, None, log)
        render_and_save(photo, adj, out, opts)
        write_sidecar(out, adj, source, notes, scene)
        return {"ok": True, "settings": adj, "source": source, "notes": notes, "scene": scene}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
