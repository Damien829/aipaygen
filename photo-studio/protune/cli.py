"""protune: professional auto-editing for your own camera files.

  protune ~/Pictures/shoot                 # auto edit every photo in the folder
  protune ~/Pictures/shoot --ai            # Claude (your Pro plan via Claude Code) fine-tunes each edit
  protune shot.NEF --style moody --compare # one file, a look, and a before/after image
  protune shot.NEF --set exposure=0.3 --set shadows=40   # override any slider
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from .adjust import Adjustments, apply, linear_to_srgb
from .analyze import STYLES, auto_adjust
from .io import SUPPORTED, load, preview, save, to_8bit


def _collect(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        p = Path(raw).expanduser()
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED)
        elif p.suffix.lower() in SUPPORTED:
            files.append(p)
        else:
            print(f"skipping {p} (not a supported photo)", file=sys.stderr)
    return files


def _overrides(pairs: list[str]) -> dict:
    out = {}
    for pair in pairs:
        k, _, v = pair.partition("=")
        out[k.strip()] = v.strip().lower() in ("1", "true", "yes") if k.strip() == "monochrome" else float(v)
    return out


def _compare(before: np.ndarray, after: np.ndarray, path: Path) -> None:
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
    ap.add_argument("inputs", nargs="+", help="photos or folders (RAW, JPEG, TIFF, PNG)")
    ap.add_argument("-o", "--out", default=None, help="output folder (default: <input folder>/edited)")
    ap.add_argument("--style", choices=sorted(STYLES), default="natural")
    ap.add_argument("--ai", action="store_true", help="have Claude review and fine-tune every edit")
    ap.add_argument("--ai-passes", type=int, default=2, help="Claude review rounds per photo (default 2)")
    ap.add_argument("--ai-via", choices=["claude-code", "api"], default="claude-code",
                    help="claude-code: your Claude subscription via the `claude` CLI (default); "
                         "api: ANTHROPIC_API_KEY, pay per use")
    ap.add_argument("--ai-model", default=None, help="model for --ai-via claude-code (default: your Claude Code default)")
    ap.add_argument("--settings", help="JSON file of slider values to use instead of auto analysis")
    ap.add_argument("--set", action="append", default=[], metavar="SLIDER=VALUE", help="override one slider")
    ap.add_argument("--compare", action="store_true", help="also save a before/after image")
    ap.add_argument("--format", choices=["jpg", "png", "tif"], default="jpg")
    ap.add_argument("--quality", type=int, default=95)
    args = ap.parse_args(argv)

    files = _collect(args.inputs)
    if not files:
        print("No photos found.", file=sys.stderr)
        return 1

    fixed = json.loads(Path(args.settings).read_text()) if args.settings else None
    over = _overrides(args.set)

    backend = None
    if args.ai and fixed is None:
        from .ai import make_backend

        try:
            backend = make_backend(args.ai_via, args.ai_model)
        except Exception as e:
            print(f"AI unavailable ({e}); using auto settings only", file=sys.stderr)

    for n, f in enumerate(files, 1):
        t0 = time.time()
        print(f"[{n}/{len(files)}] {f.name}")
        photo = load(f)
        small = preview(photo.linear)

        if fixed is not None:
            adj = Adjustments.from_dict(fixed)
        else:
            adj = auto_adjust(small, photo.is_raw, args.style)
            if backend is not None:
                from .ai import ai_refine

                try:
                    adj = ai_refine(small, adj, args.style, args.ai_passes, backend=backend)
                except Exception as e:  # keep going with the auto edit
                    print(f"    AI unavailable ({e}); using auto settings")
        if over:
            adj = Adjustments.from_dict({**adj.to_dict(), **over})

        result = apply(photo.linear, adj)
        out_dir = Path(args.out).expanduser() if args.out else f.parent / "edited"
        out = out_dir / f"{f.stem}.{args.format}"
        save(result, out, photo.exif, args.quality)
        # Sidecar with the exact settings: tweak it and re-run with --settings.
        out.with_suffix(".json").write_text(json.dumps(adj.to_dict(), indent=2))
        if args.compare:
            _compare(linear_to_srgb(np.clip(photo.linear, 0, 1)), result,
                     out_dir / f"{f.stem}_before_after.jpg")
        print(f"    saved {out}  ({time.time() - t0:.1f}s)  "
              + " ".join(f"{k}={v}" for k, v in adj.to_dict().items() if v not in (0, 0.0, False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
