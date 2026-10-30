"""Loading camera files and saving finished photos (with their camera metadata)."""

from __future__ import annotations

import io as _io
import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps

from .adjust import srgb_to_linear

try:  # iPhone / some cameras shoot HEIC
    import pillow_heif

    pillow_heif.register_heif_opener()
    HEIF_EXTS = {".heic", ".heif", ".hif"}
except ImportError:  # pragma: no cover
    HEIF_EXTS = set()

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

RAW_EXTS = {".cr2", ".cr3", ".crw", ".nef", ".nrw", ".arw", ".srf", ".sr2", ".raf", ".orf", ".rw2",
            ".pef", ".dng", ".srw", ".x3f", ".3fr", ".fff", ".iiq", ".erf", ".kdc", ".mrw", ".rwl", ".mos"}
RASTER_EXTS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"} | HEIF_EXTS
SUPPORTED = RAW_EXTS | RASTER_EXTS

_SRGB = ImageCms.createProfile("sRGB")
SRGB_ICC = ImageCms.ImageCmsProfile(_SRGB).tobytes()

# Camera details worth showing to Claude (EXIF tag ids).
_META_TAGS = {0x010F: "make", 0x0110: "camera", 0xA434: "lens", 0x8827: "iso",
              0x829A: "shutter_s", 0x829D: "aperture_f", 0x920A: "focal_mm", 0x9003: "taken"}


@dataclass
class Photo:
    path: Path
    linear: np.ndarray  # float32 HxWx3, linear-light sRGB primaries, upright
    is_raw: bool
    exif: bytes | None = None  # used when exiftool is not installed
    meta: dict = field(default_factory=dict)


def load(path: str | Path, half: bool = False) -> Photo:
    """Read any supported file. `half=True` decodes RAW at half size (fast previews)."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext in RAW_EXTS:
        import rawpy

        with rawpy.imread(str(path)) as raw:
            rgb16 = raw.postprocess(
                use_camera_wb=True,  # start from what the camera measured
                no_auto_bright=True,  # exposure is our job, not libraw's
                output_bps=16,
                gamma=(1, 1),  # linear output
                output_color=rawpy.ColorSpace.sRGB,
                highlight_mode=rawpy.HighlightMode.Blend,
                half_size=half,
            )
        return Photo(path, rgb16.astype(np.float32) / 65535.0, True, _pil_exif(path), read_meta(path))

    if ext in (".tif", ".tiff", ".png") and cv2 is not None:
        arr = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
        if arr is not None and arr.dtype == np.uint16:  # keep all 16 bits
            arr = arr[..., :3][..., ::-1] if arr.ndim == 3 else np.repeat(arr[..., None], 3, -1)
            return Photo(path, srgb_to_linear(arr.astype(np.float32) / 65535.0), False,
                         _pil_exif(path), read_meta(path))

    src = Image.open(path)
    icc = src.info.get("icc_profile")
    im = ImageOps.exif_transpose(src)  # honour camera rotation (before touching the EXIF)
    exif = _upright_exif(src.getexif())
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if icc:  # e.g. Adobe RGB JPEGs: convert so colours stay correct
        try:
            src = ImageCms.ImageCmsProfile(_io.BytesIO(icc))
            if "sRGB" not in (ImageCms.getProfileDescription(src) or ""):
                im = ImageCms.profileToProfile(im.convert("RGB"), src, _SRGB, outputMode="RGB")
        except Exception:
            pass
    im = im.convert("RGB")
    if half:
        im.thumbnail((max(im.size) // 2, max(im.size) // 2))
    arr = np.asarray(im, dtype=np.float32) / 255.0
    return Photo(path, srgb_to_linear(arr), False, exif, read_meta(path))


def _upright_exif(e: Image.Exif) -> bytes | None:
    if not e:
        return None
    e[0x0112] = 1  # pixels are saved upright
    try:
        return e.tobytes()
    except Exception:
        return None


def _pil_exif(path: Path) -> bytes | None:
    """Many RAW formats are TIFF-based, so Pillow can often read their EXIF."""
    try:
        with Image.open(path) as im:
            return _upright_exif(im.getexif())
    except Exception:
        return None


def exiftool() -> str | None:
    for p in (shutil.which("exiftool"), Path.home() / ".local/bin/exiftool",
              "/opt/homebrew/bin/exiftool", "/usr/local/bin/exiftool"):
        if p and Path(p).exists():
            return p
    return None


def read_meta(path: Path) -> dict:
    """Camera, lens, ISO, shutter, aperture, focal length, date: best effort."""
    tool = exiftool()
    if tool:
        try:
            out = subprocess.run([tool, "-j", "-n", "-Make", "-Model", "-LensModel", "-ISO", "-ExposureTime",
                                  "-FNumber", "-FocalLength", "-DateTimeOriginal", str(path)],
                                 capture_output=True, text=True, timeout=20)
            d = json.loads(out.stdout)[0]
            names = {"Make": "make", "Model": "camera", "LensModel": "lens", "ISO": "iso",
                     "ExposureTime": "shutter_s", "FNumber": "aperture_f", "FocalLength": "focal_mm",
                     "DateTimeOriginal": "taken"}
            return {names[k]: v for k, v in d.items() if k in names}
        except Exception:
            pass
    try:
        with Image.open(path) as im:
            e = im.getexif()
            tags = dict(e)
            tags.update(e.get_ifd(0x8769))
            meta = {}
            for tag, name in _META_TAGS.items():
                v = tags.get(tag)
                if v is not None:
                    meta[name] = float(v) if hasattr(v, "numerator") else (str(v).strip("\x00 ") if isinstance(v, str) else v)
            return meta
    except Exception:
        return {}


def to_8bit(srgb: np.ndarray) -> Image.Image:
    return Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")


def resize_long_edge(srgb: np.ndarray, long_edge: int | None) -> np.ndarray:
    h, w = srgb.shape[:2]
    if not long_edge or max(h, w) <= long_edge:
        return srgb
    s = long_edge / max(h, w)
    size = (max(1, round(w * s)), max(1, round(h * s)))
    if cv2 is not None:
        return cv2.resize(srgb.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    chans = [np.asarray(Image.fromarray(srgb[..., i].astype(np.float32), "F").resize(size, Image.LANCZOS))
             for i in range(3)]
    return np.stack(chans, -1)


def save(srgb: np.ndarray, out: Path, photo: Photo, quality: int = 95) -> None:
    """Save the finished photo. TIFF is 16-bit (for print/further editing)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    ext = out.suffix.lower()
    tool = exiftool()
    kw: dict = {"icc_profile": SRGB_ICC}
    if photo.exif and not tool:
        kw["exif"] = photo.exif
    if ext in (".tif", ".tiff") and cv2 is not None:
        bgr16 = (np.clip(srgb, 0, 1) * 65535 + 0.5).astype(np.uint16)[..., ::-1]
        cv2.imwrite(str(out), np.ascontiguousarray(bgr16))
    elif ext in (".jpg", ".jpeg"):
        to_8bit(srgb).save(out, quality=quality, subsampling=0, optimize=True, **kw)
    else:
        to_8bit(srgb).save(out, **kw)
    if tool:
        _copy_metadata(tool, photo.path, out)


def _copy_metadata(tool: str, src: Path, out: Path) -> None:
    """Copy EXIF/IPTC/XMP (camera, lens, date, GPS, copyright) from the original.
    Embedded previews and the original colour profile are left out on purpose:
    they would show the unedited look or the wrong colours."""
    with tempfile.NamedTemporaryFile(suffix=".icc", delete=False) as f:
        f.write(SRGB_ICC)
        icc = f.name
    try:
        subprocess.run([tool, "-q", "-q", "-overwrite_original", "-m", "-TagsFromFile", str(src), "-all:all",
                        "--ICC_Profile:all", "--PreviewImage", "--ThumbnailImage", "--JpgFromRaw",
                        "--OtherImage", "--Orientation", "--StripOffsets", "--StripByteCounts",
                        "--ImageWidth", "--ImageHeight", "--BitsPerSample", "--Compression",
                        "--PhotometricInterpretation", "--SamplesPerPixel", "--PlanarConfiguration",
                        "-Orientation#=1", "-Software=ProTune", f"-ICC_Profile<={icc}", str(out)],
                       capture_output=True, timeout=60)
    except Exception:
        pass
    finally:
        Path(icc).unlink(missing_ok=True)


def preview(linear: np.ndarray, long_side: int = 1024) -> np.ndarray:
    """Downscaled linear copy used for analysis, live editing and for showing Claude."""
    h, w = linear.shape[:2]
    s = long_side / max(h, w)
    if s >= 1:
        return linear
    size = (max(1, int(w * s)), max(1, int(h * s)))
    if cv2 is not None:
        return cv2.resize(linear.astype(np.float32), size, interpolation=cv2.INTER_AREA)
    chans = [np.asarray(Image.fromarray(linear[..., i].astype(np.float32), "F").resize(size, Image.BOX))
             for i in range(3)]
    return np.stack(chans, -1)
