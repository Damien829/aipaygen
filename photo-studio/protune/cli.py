"""protune: professional auto-editing for your own camera files.

  protune ~/Pictures/shoot                 # auto edit every photo in the folder
  protune ~/Pictures/shoot --ai            # Claude (your plan, via Claude Code) fine-tunes each edit
  protune shot.NEF --style moody --compare # one file, a look, and a before/after image
  protune shot.NEF --set exposure=0.3 --set shadows=40   # override any slider
  protune ~/Pictures/shoot --settings edited/IMG_0001.json # same look on every photo
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__
from .adjust import RANGES, Adjustments, linear_to_srgb
from .analyze import STYLES
from .batch import AiGuard, Options, collect, output_path, process, read_sidecar, render_and_save, write_sidecar
from .io import load, preview, to_8bit


def _overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        k, _, v = (x.strip() for x in pair.partition("="))
        if k == "monochrome":
            out[k] = v.lower() in ("1", "true", "yes", "on")
        elif k in RANGES:
            out[k] = float(v)
        else:
            raise SystemExit(f"unknown slider '{k}'. Sliders: {', '.join(RANGES)}, monochrome")
    return out


def compare_image(before: np.ndarray, after: np.ndarray, path: Path) -> None:
    from PIL import Image

    a, b = to_8bit(before), to_8bit(after)
    a.thumbnail((1600, 1600))
    b.thumbnail((1600, 1600))
    gap = 16
    canvas = Image.new("RGB", (a.width + b.width + gap, max(a.height, b.height)), (24, 24, 24))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + gap, 0))
    canvas.save(path, quality=90)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="protune", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+", help="photos or folders (RAW, JPEG, HEIC, TIFF, PNG)")
    ap.add_argument("-o", "--out", default=None, help="output folder (default: <input folder>/edited)")
    ap.add_argument("-r", "--recursive", action="store_true", help="include subfolders")
    ap.add_argument("--style", choices=sorted(STYLES), default="natural")
    ap.add_argument("--ai", action="store_true", help="have Claude review and fine-tune every edit")
    ap.add_argument("--ai-passes", type=int, default=2, help="Claude review rounds per photo (default 2)")
    ap.add_argument("--ai-via", choices=["claude-code", "api"], default="claude-code",
                    help="claude-code: your Claude subscription via the `claude` CLI (default); "
                         "api: ANTHROPIC_API_KEY, pay per use")
    ap.add_argument("--ai-model", default=None, help="model for --ai-via claude-code (default: your Claude Code default)")
    ap.add_argument("--settings", help="JSON file of slider values to use for every photo instead of analysis")
    ap.add_argument("--set", action="append", default=[], metavar="SLIDER=VALUE", help="override one slider")
    ap.add_argument("--skip-done", action="store_true",
                    help="skip photos already edited (with --ai: only those Claude already reviewed)")
    ap.add_argument("--compare", action="store_true", help="also save a before/after image")
    ap.add_argument("--format", choices=["jpg", "tif", "png"], default="jpg", help="tif = 16-bit TIFF")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality (default 95)")
    ap.add_argument("--long-edge", type=int, default=None, help="resize so the long edge is this many pixels")
    ap.add_argument("--version", action="version", version=f"protune {__version__}")
    args = ap.parse_args(argv)

    over = _overrides(args.set)
    fixed = Adjustments.from_dict(json.loads(Path(args.settings).read_text())) if args.settings else None
    opts = Options(style=args.style, ai=args.ai, ai_passes=args.ai_passes, fmt=args.format,
                   quality=args.quality, long_edge=args.long_edge)

    out_root = Path(args.out).expanduser() if args.out else None
    files = collect(args.inputs, args.recursive, skip_dirs=(out_root,) if out_root else ())
    files = [f for f in files if f.parent.name != "edited" or out_root is not None]
    if not files:
        print("No photos found.", file=sys.stderr)
        return 1

    guard = None
    if args.ai and fixed is None:
        from .ai import make_backend

        try:
            guard = AiGuard(make_backend(args.ai_via, args.ai_model))
        except Exception as e:
            print(f"AI unavailable ({e}); using automatic edits only", file=sys.stderr)

    first = Path(args.inputs[0]).expanduser()
    root = first if first.is_dir() and len(args.inputs) == 1 else None
    failed: list[str] = []
    skipped = 0
    t_all = time.time()
    try:
        for n, f in enumerate(files, 1):
            t0 = time.time()
            out = output_path(f, out_root or (f.parent / "edited"), args.format,
                              root if out_root else None)
            if args.skip_done and out.exists():
                prev = read_sidecar(out) or {}
                if not args.ai or prev.get("_source") in ("ai", "manual"):
                    print(f"[{n}/{len(files)}] {f.name}: already done, skipping")
                    skipped += 1
                    continue
            print(f"[{n}/{len(files)}] {f.name}")
            if guard and guard.failures == guard.max:
                print(f"    Claude stopped responding ({guard.reason}); continuing with automatic edits")
                guard.failures += 1  # say it once
            if fixed is not None or over:
                photo = load(f)
                if fixed is not None:
                    adj, source = fixed, "manual"
                else:
                    from .analyze import auto_adjust

                    adj, source = auto_adjust(preview(photo.linear), photo.is_raw, args.style), "auto"
                adj = Adjustments.from_dict({**adj.to_dict(), **over})
                render_and_save(photo, adj, out, opts)
                write_sidecar(out, adj, "manual" if over else source)
                result = {"ok": True, "settings": adj}
            else:
                result = process(f, out, opts, guard)
                photo = None
            if not result["ok"]:
                print(f"    FAILED: {result['error']}")
                failed.append(f.name)
                continue
            adj = result["settings"]
            if args.compare:
                photo = photo or load(f)
                from .adjust import apply
                from .io import resize_long_edge

                compare_image(linear_to_srgb(np.clip(photo.linear, 0, 1)),
                              resize_long_edge(apply(preview(photo.linear, 1600), adj), 1600),
                              out.with_name(f"{out.stem}_before_after.jpg"))
            print(f"    saved {out}  ({time.time() - t0:.1f}s)  "
                  + " ".join(f"{k}={v}" for k, v in adj.to_dict().items() if v not in (0, 0.0, False)))
    except KeyboardInterrupt:
        print("\nStopped. Photos finished so far are saved.")
        return 130

    done = len(files) - len(failed) - skipped
    print(f"\nDone: {done} photo{'s' * (done != 1)} edited in {time.time() - t_all:.0f}s"
          + (f", {skipped} already done" if skipped else "") + ".")
    if failed:
        print("Could not edit: " + ", ".join(failed))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
