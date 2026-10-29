"""Automatic analysis: measure the photo and choose slider values like an editor would.

Works on a small preview so it is fast, then checks its own result and nudges
exposure until the rendered preview lands where it should.
"""

from __future__ import annotations

import numpy as np

from .adjust import Adjustments, apply, guided_filter, linear_to_srgb, luminance, wb_gains

# Starting-point looks. Auto analysis decides corrections; the style adds taste on top.
STYLES: dict[str, dict] = {
    "natural": {},
    "vibrant": {"vibrance": 20, "contrast": 10, "clarity": 8},
    "moody": {"contrast": 15, "exposure": -0.25, "vibrance": -10, "highlights": -15, "vignette": -25},
    "bright": {"exposure": 0.25, "shadows": 15, "contrast": -10, "vibrance": 5},
    "bw": {"monochrome": True, "contrast": 20, "clarity": 12},
}


def _wb(lin: np.ndarray) -> tuple[float, float]:
    """Estimate temperature/tint from pixels that are probably neutral (grey/white)."""
    s = linear_to_srgb(lin)
    y = luminance(s)
    mx, mn = s.max(-1), s.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    cand = (y > 0.15) & (y < 0.92) & (sat < 0.25) & (mx < 0.98)
    if cand.mean() < 0.01:
        return 0.0, 0.0
    px = lin[cand]
    # Weight brighter neutrals more: white/grey objects are the best reference.
    w = luminance(px) ** 2
    m = (px * w[:, None]).sum(0) / max(w.sum(), 1e-6)
    a = np.log2(m[1] / max(m[0], 1e-6))  # wanted r/g change
    c = np.log2(m[1] / max(m[2], 1e-6))  # wanted b/g change
    temp, tint = 100 * (a - c), 100 * (a + c)
    # Confidence: plenty of neutral pixels -> trust them. A very strong cast
    # (sunset, candle light, stage) is usually intentional, so only tame it.
    strength = 0.9 * np.clip(cand.mean() / 0.05, 0.3, 1.0)
    if abs(temp) > 90:
        strength *= 90 / abs(temp)
    return float(np.clip(temp * strength, -80, 80)), float(np.clip(tint * strength, -40, 40))


def _noise_sigma(srgb_y: np.ndarray) -> float:
    """Noise level from the high-frequency residual of flat areas (robust MAD estimate)."""
    smooth = guided_filter(srgb_y, 2, 0.002)
    resid = srgb_y - smooth
    grad = np.abs(np.diff(smooth, axis=1, append=smooth[:, -1:]))
    flat = grad < np.percentile(grad, 40)
    r = resid[flat] if flat.any() else resid.ravel()
    return float(np.median(np.abs(r - np.median(r))) / 0.6745)


def measure(srgb: np.ndarray) -> dict:
    """Statistics of a rendered (display-space) image, also shown to Claude."""
    y = luminance(srgb)
    mx, mn = srgb.max(-1), srgb.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-4)
    p = np.percentile(y, [0.5, 5, 25, 50, 75, 95, 99.5])
    return {
        "luma_p0_5": float(p[0]), "luma_p5": float(p[1]), "luma_p25": float(p[2]),
        "luma_median": float(p[3]), "luma_p75": float(p[4]), "luma_p95": float(p[5]),
        "luma_p99_5": float(p[6]), "luma_std": float(y.std()),
        "clipped_highlights_pct": float((mx > 0.995).mean() * 100),
        "crushed_shadows_pct": float((mx < 0.01).mean() * 100),
        "mean_saturation": float(sat.mean()),
        "noise_sigma": _noise_sigma(y),
    }


def auto_adjust(lin_preview: np.ndarray, is_raw: bool, style: str = "natural") -> Adjustments:
    adj = Adjustments()
    adj.temperature, adj.tint = _wb(lin_preview)

    # Exposure: bring the log-average brightness to a mid-grey "key", without
    # pushing the brightest important tones past what highlight recovery can hold.
    lin = lin_preview * wb_gains(adj.temperature, adj.tint)
    L = luminance(lin)
    key = float(np.exp(np.mean(np.log(L + 1e-4))))
    ev = np.log2(0.16 / max(key, 1e-4)) * 0.8
    p995 = float(np.percentile(L, 99.5))
    ev = min(ev, np.log2(2.2 / max(p995, 1e-4)))
    adj.exposure = float(np.clip(ev, -2.0, 3.0))

    # Measure the exposed image to pick tone sliders.
    s = linear_to_srgb(np.clip(L * 2 ** adj.exposure, 0, None))
    p05, p10, p95, p998 = np.percentile(s, [0.5, 10, 95, 99.8])
    adj.highlights = -float(np.clip((p95 - 0.70) * 260, 0, 85)) - 8
    adj.shadows = float(np.clip((0.22 - p10) * 280, 0, 70)) + 5
    adj.whites = float(np.clip((0.97 - p998) * 300, -30, 35))
    adj.blacks = float(np.clip((0.02 - p05) * 400, -30, 25))
    adj.contrast = float(np.clip((0.22 - s.std()) * 250, -20, 35))

    srgb = linear_to_srgb(np.clip(lin * 2 ** adj.exposure, 0, 1))
    mx, mn = srgb.max(-1), srgb.min(-1)
    msat = float(((mx - mn) / np.maximum(mx, 1e-4)).mean())
    adj.vibrance = float(np.clip((0.30 - msat) * 120, -10, 35)) + 5

    sigma = _noise_sigma(luminance(srgb))
    adj.noise_reduction = float(np.clip((sigma - 0.004) * 4000, 0, 70))
    texture = float(np.mean(np.abs(np.diff(luminance(srgb), axis=1))))
    adj.clarity = float(np.clip(18 - texture * 400, 0, 18))
    # RAW files arrive soft; camera JPEGs are already sharpened in-camera.
    base_sharp = 45 if is_raw else 15
    adj.sharpening = float(max(5, base_sharp - adj.noise_reduction * 0.3))

    # Style on top (additive for sliders, replace for the B&W switch).
    for k, v in STYLES.get(style, {}).items():
        if isinstance(v, bool):
            setattr(adj, k, v)
        else:
            setattr(adj, k, getattr(adj, k) + v)

    return refine_exposure(lin_preview, adj.clamped(), style)


def refine_exposure(lin_preview: np.ndarray, adj: Adjustments, style: str = "natural") -> Adjustments:
    """Render the preview, check the median, correct exposure; twice is plenty.

    The correction is capped so night scenes and silhouettes stay dark on purpose.
    """
    target = {"bright": 0.50, "moody": 0.36}.get(style, 0.44)
    start = adj.exposure
    for _ in range(2):
        med = float(np.median(luminance(apply(lin_preview, adj))))
        if abs(med - target) < 0.02:
            break
        step = np.log2(target / max(med, 0.02)) * 0.9
        adj.exposure = float(np.clip(adj.exposure + step, start - 0.75, start + 0.75))
    return adj.clamped()
