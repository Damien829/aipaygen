"""Loading camera files (RAW or JPEG/TIFF/PNG) and saving finished photos."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

from .adjust import srgb_to_linear

RAW_EXTS = {".cr2", ".cr3", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2",
            ".pef", ".dng", ".srw", ".x3f", ".3fr", ".iiq", ".erf", ".kdc", ".mrw", ".rwl"}
RASTER_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}
SUPPORTED = RAW_EXTS | RASTER_EXTS

_SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


@dataclass
class Photo:
    path: Path
    linear: np.ndarray  # float32 HxWx3, linear-light sRGB primaries
    is_raw: bool
    exif: bytes | None


def load(path: str | Path) -> Photo:
    path = Path(path)
    ext = path.suffix.lower()
    if ext in RAW_EXTS:
        try:
            import rawpy
        except ImportError as e:  # pragma: no cover
            raise SystemExit("RAW files need rawpy:  pip install rawpy") from e
        with rawpy.imread(str(path)) as raw:
            rgb16 = raw.postprocess(
                use_camera_wb=True,  # start from what the camera measured
                no_auto_bright=True,  # exposure is our job, not libraw's
                output_bps=16,
                gamma=(1, 1),  # linear output
                output_color=rawpy.ColorSpace.sRGB,
                highlight_mode=rawpy.HighlightMode.Blend,
            )
        return Photo(path, rgb16.astype(np.float32) / 65535.0, True, _raw_exif(path))

    im = Image.open(path)
    exif = im.info.get("exif")
    im = ImageOps.exif_transpose(im)  # honour camera rotation
    if exif:
        e = Image.Exif()
        e.load(exif)
        e[0x0112] = 1  # pixels are now upright
        exif = e.tobytes()
    if im.mode in ("I;16", "I;16B", "I"):
        arr = np.asarray(im, dtype=np.float32) / 65535.0
        arr = np.repeat(arr[..., None], 3, -1)
    else:
        im = im.convert("RGB")
        arr = np.asarray(im, dtype=np.float32) / 255.0
    return Photo(path, srgb_to_linear(arr), False, exif)


def _raw_exif(path: Path) -> bytes | None:
    """Most RAW formats are TIFF-based, so Pillow can usually read their EXIF."""
    try:
        with Image.open(path) as im:
            e = im.getexif()
            if e:
                e[0x0112] = 1
                return e.tobytes()
    except Exception:
        pass
    return None


def to_8bit(srgb: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def save(srgb: np.ndarray, out: Path, exif: bytes | None, quality: int = 95) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower()
    kw = {"icc_profile": _SRGB_ICC}
    if exif:
        kw["exif"] = exif
    if ext in (".jpg", ".jpeg"):
        to_8bit(srgb).save(out, quality=quality, subsampling=0, optimize=True, **kw)
    else:
        to_8bit(srgb).save(out, **kw)


def preview(linear: np.ndarray, long_side: int = 1024) -> np.ndarray:
    """Downscaled linear copy used for analysis and for showing Claude."""
    h, w = linear.shape[:2]
    s = long_side / max(h, w)
    if s >= 1:
        return linear
    size = (max(1, int(w * s)), max(1, int(h * s)))
    chans = [np.asarray(Image.fromarray(linear[..., i].astype(np.float32), "F").resize(size, Image.BOX))
             for i in range(3)]
    return np.stack(chans, -1)
