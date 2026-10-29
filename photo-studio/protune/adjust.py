"""The editing engine: a fixed set of Lightroom-style sliders applied to real pixels.

Everything here is a classic, deterministic image operation (white balance,
tone curves, local contrast, colour, noise reduction, sharpening). Nothing is
generated or invented; the same settings always give the same result.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

import numpy as np

try:  # OpenCV makes the blurs ~10x faster; everything still works without it.
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

# (min, max) for every slider. Values coming from the auto analysis or from
# Claude are clamped to these ranges before they touch the image.
RANGES: dict[str, tuple[float, float]] = {
    "temperature": (-100, 100),  # + warmer / - cooler
    "tint": (-100, 100),  # + magenta / - green
    "exposure": (-3.0, 3.0),  # stops (EV)
    "contrast": (-100, 100),
    "highlights": (-100, 100),
    "shadows": (-100, 100),
    "whites": (-100, 100),
    "blacks": (-100, 100),
    "clarity": (-100, 100),
    "vibrance": (-100, 100),
    "saturation": (-100, 100),
    "sharpening": (0, 150),
    "noise_reduction": (0, 100),
    "vignette": (-100, 100),  # - darkens corners
}


@dataclass
class Adjustments:
    temperature: float = 0.0
    tint: float = 0.0
    exposure: float = 0.0
    contrast: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    clarity: float = 0.0
    vibrance: float = 0.0
    saturation: float = 0.0
    sharpening: float = 0.0
    noise_reduction: float = 0.0
    vignette: float = 0.0
    monochrome: bool = False

    def clamped(self) -> "Adjustments":
        out = Adjustments(**asdict(self))
        for name, (lo, hi) in RANGES.items():
            setattr(out, name, float(np.clip(float(getattr(out, name)), lo, hi)))
        out.monochrome = bool(out.monochrome)
        return out

    def to_dict(self) -> dict:
        d = asdict(self.clamped())
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in d.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "Adjustments":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names}).clamped()


# ---------------------------------------------------------------------------
# Colour-space helpers
# ---------------------------------------------------------------------------

LUMA = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def srgb_to_linear(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def linear_to_srgb(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, None)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * np.power(x, 1 / 2.4) - 0.055).astype(np.float32)


def luminance(rgb: np.ndarray) -> np.ndarray:
    return (rgb @ LUMA).astype(np.float32)


def smoothstep(e0: float, e1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------------------
# Filters (pure numpy, O(pixels) regardless of radius)
# ---------------------------------------------------------------------------


def _box_1d(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    if r < 1:
        return a
    a = np.moveaxis(a, axis, 0)
    pad = [(r + 1, r)] + [(0, 0)] * (a.ndim - 1)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=0, dtype=np.float64)
    n = a.shape[0]
    out = (c[2 * r + 1: 2 * r + 1 + n] - c[:n]) * (1.0 / (2 * r + 1))
    return np.moveaxis(out.astype(np.float32), 0, axis)


def box_blur(a: np.ndarray, r: int) -> np.ndarray:
    if cv2 is not None and r >= 1:
        return cv2.blur(np.ascontiguousarray(a, np.float32), (2 * r + 1, 2 * r + 1),
                        borderType=cv2.BORDER_REPLICATE)
    return _box_1d(_box_1d(a, r, 0), r, 1)


def gaussian_blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """Three box passes approximate a Gaussian closely enough for photo work."""
    if sigma < 0.3:
        return a
    r = max(1, int(round(np.sqrt(12 * sigma * sigma / 3 + 1) / 2)))
    for _ in range(3):
        a = box_blur(a, r)
    return a


def guided_filter(p: np.ndarray, r: int, eps: float) -> np.ndarray:
    """Self-guided edge-preserving smoothing (He et al.). Keeps edges, avoids halos."""
    mean_p = box_blur(p, r)
    var_p = box_blur(p * p, r) - mean_p * mean_p
    a = var_p / (var_p + eps)
    b = mean_p - a * mean_p
    return box_blur(a, r) * p + box_blur(b, r)


def _resize(a: np.ndarray, w: int, h: int) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((w, h), Image.BILINEAR))


def base_layer(lp: np.ndarray, work_px: int = 768) -> np.ndarray:
    """Large-scale illumination layer, computed small and upsampled for speed."""
    h, w = lp.shape
    s = min(1.0, work_px / max(h, w))
    small = _resize(lp, max(1, int(w * s)), max(1, int(h * s))) if s < 1 else lp
    r = max(2, int(max(small.shape) * 0.03))
    base = guided_filter(small, r, 0.01)
    return _resize(base, w, h) if s < 1 else base


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def wb_gains(temperature: float, tint: float) -> np.ndarray:
    t, g = temperature / 200.0, tint / 200.0
    return np.array([2 ** t, 2 ** (-g), 2 ** (-t)], dtype=np.float32)


def _tone(lp: np.ndarray, adj: Adjustments) -> np.ndarray:
    """Tone work on perceptual (gamma-encoded) luminance."""
    base = base_layer(lp)
    detail = lp - base

    # Highlights / shadows act on the smooth base layer so local texture survives.
    sh_mask = 1.0 - smoothstep(0.0, 0.55, base)
    hi_mask = smoothstep(0.45, 1.0, base)
    base = base + (adj.shadows / 100.0) * 0.30 * sh_mask * (1.0 - base)
    base = base + (adj.highlights / 100.0) * 0.30 * hi_mask * base

    # Clarity: midtone local contrast.
    mid = 1.0 - np.abs(base - 0.5) * 2.0
    detail = detail * (1.0 + (adj.clarity / 100.0) * 1.2 * np.clip(mid, 0.25, 1.0))
    lp = base + detail

    # Whites / blacks: move the end points.
    black = -adj.blacks / 100.0 * 0.08
    white = 1.0 - adj.whites / 100.0 * 0.12
    lp = (lp - black) / max(white - black, 1e-3)

    # Contrast: blend toward an S-curve (or its inverse) pivoting on mid-grey.
    c = adj.contrast / 100.0
    if c > 0:
        x = np.clip(lp, 0, 1)
        s = x * x * (3 - 2 * x)
        lp = lp + c * 0.7 * (s - x)
    elif c < 0:
        lp = 0.5 + (lp - 0.5) * (1 + c * 0.45)

    # Gentle highlight roll-off instead of a hard clip.
    knee = 0.92
    over = lp > knee
    lp = np.where(over, knee + (1 - knee) * np.tanh((lp - knee) / (1 - knee)), lp)
    return np.clip(lp, 0.0, 1.0).astype(np.float32)


def _colour(rgb: np.ndarray, adj: Adjustments) -> np.ndarray:
    """Vibrance / saturation on gamma-encoded RGB, protecting skin tones."""
    if adj.vibrance == 0 and adj.saturation == 0:
        return rgb
    y = luminance(rgb)[..., None]
    mx, mn = rgb.max(-1), rgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # Skin tones: red > green > blue, moderately saturated.
    skin = ((r > g) & (g > b) & (sat > 0.15) & (sat < 0.65)).astype(np.float32)
    skin = box_blur(skin, 2)
    vib = (adj.vibrance / 100.0) * (1.0 - sat) * (1.0 - 0.6 * skin)
    factor = 1.0 + adj.saturation / 100.0 + vib
    return np.clip(y + (rgb - y) * factor[..., None], 0.0, 1.0)


def _noise_reduction(rgb: np.ndarray, amount: float, scale: float) -> np.ndarray:
    if amount < 2:
        return rgb
    a = amount / 100.0
    y = luminance(rgb)
    chroma = rgb - y[..., None]
    # Colour noise: blur chroma generously (the eye sees little colour detail),
    # at half resolution because chroma is smooth anyway.
    h, w = y.shape
    cs = (1.0 + 3.0 * a) * scale / 2
    chroma = np.stack([
        _resize(gaussian_blur(_resize(chroma[..., i], max(1, w // 2), max(1, h // 2)), cs), w, h)
        for i in range(3)], -1)
    # Luminance noise: edge-preserving smoothing, blended by amount.
    yr = max(1, int(round(1.5 * scale)))
    y_s = guided_filter(y, yr, (0.0004 + 0.004 * a) ** 2 * 25)
    y = y + (y_s - y) * min(1.0, 0.9 * a)
    return np.clip(y[..., None] + chroma, 0.0, 1.0)


def _sharpen(rgb: np.ndarray, amount: float, scale: float) -> np.ndarray:
    if amount <= 0:
        return rgb
    y = luminance(rgb)
    hp = y - gaussian_blur(y, 0.9 * scale)
    # Edge mask: sharpen edges, leave flat areas (sky, skin) and noise alone.
    edge = smoothstep(0.004, 0.03, np.abs(gaussian_blur(hp, 1.5 * scale)) + np.abs(hp) * 0.5)
    return np.clip(rgb + (amount / 100.0 * 1.4 * hp * edge)[..., None], 0.0, 1.0)


def _vignette(rgb: np.ndarray, amount: float) -> np.ndarray:
    if amount == 0:
        return rgb
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / np.sqrt(2)
    m = smoothstep(0.35, 1.0, d)
    return np.clip(rgb * (1.0 + amount / 100.0 * 0.6 * m)[..., None], 0.0, 1.0)


def apply(linear_rgb: np.ndarray, adj: Adjustments) -> np.ndarray:
    """Linear-light float RGB in, display-ready sRGB float [0,1] out."""
    adj = adj.clamped()
    # Detail filters scale with resolution so a 45MP file and a preview look alike.
    scale = max(1.0, max(linear_rgb.shape[:2]) / 3000.0)

    lin = linear_rgb.astype(np.float32) * wb_gains(adj.temperature, adj.tint)
    lin = lin * (2.0 ** adj.exposure)

    # Tone on luminance, then carry the change back to RGB as a ratio (keeps hue).
    L = luminance(lin)
    lp = linear_to_srgb(np.clip(L, 0, 4) / 1.0)
    lp_new = _tone(np.clip(lp, 0, None), adj)
    ratio = srgb_to_linear(lp_new) / np.maximum(L, 1e-6)
    lin = lin * ratio[..., None]

    # A channel pushed past white keeps its hue and fades toward white, the way
    # film does, instead of clipping into a flat coloured blotch.
    peak = lin.max(-1, keepdims=True)
    hue = lin / np.maximum(peak, 1e-6)
    to_white = 1.0 - 1.0 / np.maximum(peak, 1.0)
    lin = np.where(peak > 1.0, hue + (1.0 - hue) * to_white, lin)
    lin = np.clip(lin, 0.0, 1.0)

    out = linear_to_srgb(lin)
    out = _noise_reduction(out, adj.noise_reduction, scale)
    if adj.monochrome:
        out = np.repeat(luminance(out)[..., None], 3, -1)
    else:
        out = _colour(out, adj)
    out = _vignette(out, adj.vignette)
    out = _sharpen(out, adj.sharpening, scale)
    return np.clip(out, 0.0, 1.0)
