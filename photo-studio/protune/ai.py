"""Claude as a retoucher's eye: it looks at the photo and returns slider values.

Claude never produces pixels. It sees a small preview plus the measurements and
the auto settings, and answers with numbers for the same sliders a human editor
would move. The engine in adjust.py applies those numbers to your real image.
"""

from __future__ import annotations

import base64
import io
import json

import anthropic
import numpy as np

from .adjust import RANGES, Adjustments, apply, linear_to_srgb
from .analyze import measure
from .io import to_8bit

MODEL = "claude-opus-5-5"

SYSTEM = """You are a senior photo retoucher grading a professional photographer's own camera files.
You control ONLY these global sliders; you never add, remove or invent image content.

Slider meanings (Lightroom-like):
- temperature/tint: white balance correction (+temperature warmer, +tint magenta).
- exposure: stops. contrast: global S-curve.
- highlights (negative recovers bright detail), shadows (positive opens dark areas).
- whites/blacks: end points. clarity: midtone local contrast (keep low on skin).
- vibrance: boosts muted colours, protects skin. saturation: all colours equally.
- sharpening, noise_reduction: detail. vignette: negative darkens corners.
- monochrome: black and white conversion.

Aim for a clean, natural, professional result a client would pay for: accurate skin,
believable whites, detail in highlights and shadows, no halos, no over-saturation.
Respect intent: a sunset can stay warm, a night street can stay dark.
Small, deliberate moves beat large ones. Return the complete set of values you want applied."""


def _schema() -> dict:
    props: dict = {
        "scene": {"type": "string", "description": "e.g. portrait, landscape, night, product, event"},
        "notes": {"type": "string", "description": "One or two sentences on what you changed and why."},
        "monochrome": {"type": "boolean"},
    }
    for name in RANGES:
        props[name] = {"type": "number"}
    return {
        "type": "object",
        "properties": props,
        "required": list(props),
        "additionalProperties": False,
    }


def _jpeg_b64(srgb: np.ndarray, long_side: int = 1024) -> str:
    im = to_8bit(srgb)
    im.thumbnail((long_side, long_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _ask(client: anthropic.Anthropic, content: list) -> dict:
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": _schema()}},
        # If a request is ever declined by a safety classifier, retry it on a suitable model.
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to grade this image")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def ai_refine(lin_preview: np.ndarray, auto: Adjustments, style: str, passes: int = 2,
              client: anthropic.Anthropic | None = None, log=print) -> Adjustments:
    """Pass 1: Claude reviews the original and the auto edit and sets the sliders.
    Pass 2+: Claude sees its own rendered result and fine-tunes it."""
    client = client or anthropic.Anthropic()
    current = auto
    for i in range(passes):
        rendered = apply(lin_preview, current)
        content: list = []
        if i == 0:
            content += [
                {"type": "text", "text": "ORIGINAL (camera file, no edits):"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": _jpeg_b64(linear_to_srgb(np.clip(lin_preview, 0, 1)))}},
            ]
        content += [
            {"type": "text", "text": f"CURRENT EDIT (pass {i + 1}):"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": _jpeg_b64(rendered)}},
            {"type": "text", "text": (
                f"Requested look: {style}.\n"
                f"Current slider values: {json.dumps(current.to_dict())}\n"
                f"Measurements of the current edit: {json.dumps({k: round(v, 4) for k, v in measure(rendered).items()})}\n"
                f"Allowed ranges: {json.dumps(RANGES)}\n"
                + ("Set the sliders for a professional finish." if i == 0 else
                   "This is your previous edit rendered. Fix anything still off; if it already looks right, "
                   "return the same values.")
            )},
        ]
        answer = _ask(client, content)
        new = Adjustments.from_dict(answer)
        log(f"    AI pass {i + 1} [{answer.get('scene', '?')}]: {answer.get('notes', '').strip()}")
        if new == current:
            break
        current = new
    return current
