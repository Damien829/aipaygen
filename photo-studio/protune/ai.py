"""Claude as a retoucher's eye: it looks at the photo and returns slider values.

Claude never produces pixels. It sees a small preview plus the measurements and
the auto settings, and answers with numbers for the same sliders a human editor
would move. The engine in adjust.py applies those numbers to your real image.

Two ways to reach Claude:
- "claude-code" (default): runs the `claude` command line tool, so it uses the
  Claude subscription (Pro/Max) you are logged into. No API key needed.
- "api": the Anthropic API with ANTHROPIC_API_KEY, billed per use.
"""

from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .adjust import RANGES, Adjustments, apply, linear_to_srgb
from .analyze import measure
from .io import to_8bit

API_MODEL = "claude-opus-5-5"

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


def _jpeg_bytes(srgb: np.ndarray, long_side: int = 1024) -> bytes:
    im = to_8bit(srgb)
    im.thumbnail((long_side, long_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=88)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Backends. Each takes [(label, jpeg_bytes)] plus the instructions, returns the JSON answer.
# ---------------------------------------------------------------------------


def find_claude() -> str | None:
    """The `claude` command. Apps opened from Finder get a minimal PATH, so also
    look where the Claude Code installers put it."""
    home = Path.home()
    for p in (shutil.which("claude"), home / ".local/bin/claude", home / ".claude/local/claude",
              "/opt/homebrew/bin/claude", "/usr/local/bin/claude", home / ".npm-global/bin/claude"):
        if p and Path(p).exists():
            return str(p)
    return None


class ClaudeCodeBackend:
    """Uses the logged-in `claude` CLI, i.e. your Claude Pro/Max subscription."""

    def __init__(self, model: str | None = None):
        self.exe = find_claude()
        if not self.exe:
            raise RuntimeError("Claude Code is not installed (the `claude` command was not found)")
        self.model = model

    def ask(self, images: list[tuple[str, bytes]], text: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="protune-") as tmp:
            refs = []
            for i, (label, data) in enumerate(images):
                p = Path(tmp) / f"{i + 1}.jpg"
                p.write_bytes(data)
                refs.append(f"{label}: {p}")
            prompt = (SYSTEM + "\n\nRead each of these images with the Read tool and look at them carefully:\n"
                      + "\n".join(refs) + "\n\n" + text)
            cmd = [self.exe, "-p", prompt,
                   "--tools", "Read", "--allowedTools", "Read",  # it may only look at the previews
                   "--no-session-persistence",
                   "--output-format", "json",
                   "--json-schema", json.dumps(_schema())]
            if self.model:
                cmd += ["--model", self.model]
            # Drop any API key so the CLI uses the subscription login, not API billing.
            env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
            extra = [str(Path(self.exe).parent), str(Path.home() / ".local/bin"), "/opt/homebrew/bin", "/usr/local/bin"]
            env["PATH"] = os.pathsep.join(extra + [env.get("PATH", "/usr/bin:/bin")])
            proc = subprocess.run(cmd, cwd=tmp, env=env, capture_output=True, text=True, timeout=600)
        try:
            out = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(_friendly((proc.stderr or proc.stdout or "no output from claude").strip()))
        if out.get("is_error") or not out.get("structured_output"):
            raise RuntimeError(_friendly(str(out.get("result") or out.get("subtype") or "claude returned no settings")))
        return out["structured_output"]


def _friendly(msg: str) -> str:
    low = msg.lower()
    if "login" in low or "log in" in low or "api key" in low or "authenticat" in low:
        return "Claude Code isn't logged in. Open Terminal, type: claude  and log in, then try again."
    if "limit" in low or "usage" in low:
        return "Your Claude plan's usage limit was reached. It resets after a few hours. " + msg[:200]
    return msg[:300]


class ApiBackend:
    """Anthropic API with ANTHROPIC_API_KEY (pay per use)."""

    def __init__(self, client=None):
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def ask(self, images: list[tuple[str, bytes]], text: str) -> dict:
        content: list = []
        for label, data in images:
            content += [
                {"type": "text", "text": f"{label}:"},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(data).decode()}},
            ]
        content.append({"type": "text", "text": text})
        response = self.client.beta.messages.create(
            model=API_MODEL,
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
        return json.loads(next(b.text for b in response.content if b.type == "text"))


def make_backend(name: str = "claude-code", model: str | None = None):
    return ApiBackend() if name == "api" else ClaudeCodeBackend(model)


STYLE_HINTS = {
    "natural": "true-to-life, clean, neutral; what the scene looked like on a good day",
    "vibrant": "punchy colour and contrast, still believable",
    "moody": "darker, lower saturation, deeper shadows, cinematic",
    "bright": "light and airy, open shadows, soft contrast, clean whites",
    "bw": "black and white with rich tonal separation (monochrome must stay true)",
}


def _close(a: Adjustments, b: Adjustments) -> bool:
    da, db = a.to_dict(), b.to_dict()
    tol = {"exposure": 0.05}
    return all(da[k] == db[k] if isinstance(da[k], bool) else abs(da[k] - db[k]) <= tol.get(k, 2) for k in da)


def ai_refine(lin_preview: np.ndarray, auto: Adjustments, style: str, passes: int = 2,
              backend=None, log=print, crop: np.ndarray | None = None,
              meta: dict | None = None) -> tuple[Adjustments, str, str]:
    """Pass 1: Claude reviews the original and the auto edit and sets the sliders.
    Pass 2+: Claude sees its own rendered result and fine-tunes it.
    Returns (settings, notes, scene)."""
    backend = backend or make_backend()
    current, notes, scene = auto, "", ""
    for i in range(passes):
        rendered = apply(lin_preview, current)
        images = []
        if i == 0:
            images.append(("ORIGINAL (camera file, no edits, downscaled)",
                           _jpeg_bytes(linear_to_srgb(np.clip(lin_preview, 0, 1)))))
        images.append((f"CURRENT EDIT (pass {i + 1}, downscaled)", _jpeg_bytes(rendered)))
        if crop is not None:
            images.append(("CURRENT EDIT, 100% crop of the most detailed area (judge noise and sharpness here)",
                           _jpeg_bytes(apply(crop, current), long_side=max(crop.shape[:2]))))
        text = (
            f"Requested look: {style} ({STYLE_HINTS.get(style, '')}).\n"
            + (f"Camera data: {json.dumps(meta, default=str)}\n" if meta else "")
            + f"Current slider values: {json.dumps(current.to_dict())}\n"
            f"Measurements of the current edit: {json.dumps({k: round(v, 4) for k, v in measure(rendered).items()})}\n"
            f"Allowed ranges: {json.dumps(RANGES)}\n"
            + ("Set the sliders for a professional finish." if i == 0 else
               "This is your previous edit rendered. Fix anything still off; if it already looks right, "
               "return the same values.")
        )
        answer = backend.ask(images, text)
        new = Adjustments.from_dict(answer)
        notes, scene = answer.get("notes", "").strip(), answer.get("scene", "")
        log(f"    AI pass {i + 1} [{scene or '?'}]: {notes}")
        done = _close(new, current)
        current = new
        if done:
            break
    return current, notes, scene
