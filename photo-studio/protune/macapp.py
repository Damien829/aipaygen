"""Builds ~/Applications/ProTune.app: a double-clickable (and Spotlight-findable)
launcher for the ProTune window. Run by install.sh; safe to run again."""

from __future__ import annotations

import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import __version__

LAUNCHER = """#!/bin/bash
# Apps opened from Finder get a bare PATH; add the usual tool locations.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p "$HOME/Library/Logs"
exec "{exe}" >> "$HOME/Library/Logs/ProTune.log" 2>&1
"""


def draw_icon(size: int = 1024):
    """A simple aperture-style icon, drawn with Pillow (no image files needed)."""
    import math

    from PIL import Image, ImageDraw

    s = size
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([s * .06, s * .06, s * .94, s * .94], radius=s * .2, fill=(32, 32, 34, 255))
    c, r = s / 2, s * .32
    d.ellipse([c - r - s * .03, c - r - s * .03, c + r + s * .03, c + r + s * .03], fill=(70, 70, 74, 255))
    colours = [(91, 155, 255), (120, 200, 160), (240, 200, 90), (235, 120, 90), (190, 110, 210), (90, 190, 230)]
    for i, col in enumerate(colours):  # six aperture blades
        a0 = math.radians(i * 60 - 90)
        a1 = math.radians(i * 60 - 30)
        pts = [(c, c), (c + r * math.cos(a0), c + r * math.sin(a0)), (c + r * math.cos(a1), c + r * math.sin(a1))]
        d.polygon(pts, fill=col + (255,))
    ri = s * .1
    d.ellipse([c - ri, c - ri, c + ri, c + ri], fill=(32, 32, 34, 255))
    return im


def build(app_dir: Path, exe: Path) -> Path:
    app = app_dir / "ProTune.app"
    if app.exists():
        shutil.rmtree(app)
    macos, res = app / "Contents/MacOS", app / "Contents/Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    launcher = macos / "ProTune"
    launcher.write_text(LAUNCHER.format(exe=exe))
    launcher.chmod(0o755)
    info = {
        "CFBundleName": "ProTune", "CFBundleDisplayName": "ProTune",
        "CFBundleIdentifier": "local.protune.app", "CFBundleExecutable": "ProTune",
        "CFBundlePackageType": "APPL", "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__, "CFBundleIconFile": "ProTune",
        "LSUIElement": True,  # no Dock icon; the window lives in your browser and has a Quit button
        "NSHighResolutionCapable": True,
    }
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(info))
    _icon(res)
    return app


def _icon(res: Path) -> None:
    icon = draw_icon()
    icon.save(res / "ProTune.png")
    if not shutil.which("iconutil"):
        return
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "ProTune.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            icon.resize((px, px)).save(iconset / f"icon_{px}x{px}.png")
            icon.resize((px * 2, px * 2)).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(res / "ProTune.icns")], check=False)


def main() -> int:
    exe = Path(sys.executable).with_name("protune-app")
    app = build(Path.home() / "Applications", exe)
    lsregister = Path("/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                      "LaunchServices.framework/Support/lsregister")
    if lsregister.exists():  # so Spotlight and Launchpad pick it up straight away
        subprocess.run([str(lsregister), "-f", str(app)], check=False)
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
