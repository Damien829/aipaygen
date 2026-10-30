"""Optional AI layer: use Claude to interpret diagnostic data.

This is purely an assistant for *your own* diagnosis — it explains codes,
suggests likely causes ranked by probability, and proposes concrete next
tests. It never contacts the vehicle itself; it only reasons over data you've
already pulled off the bus with the rest of CarScope.

Requires the `anthropic` package and an ANTHROPIC_API_KEY in the environment.
If neither is present, CarScope still works — you just don't get the AI notes.
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover
    Anthropic = None  # type: ignore

MODEL = "claude-opus-5-5"

SYSTEM_PROMPT = (
    "You are an experienced automotive diagnostic technician helping the owner "
    "of a vehicle interpret OBD-II data they pulled themselves. Be practical and "
    "concrete. For each trouble code: explain what it means in plain language, "
    "list the most likely causes ordered from most to least probable, and give "
    "specific next diagnostic steps (what to measure or inspect, and the "
    "expected good values). Use any freeze-frame and live data provided to "
    "narrow things down. Call out safety-critical issues. When the data is "
    "insufficient to be sure, say so and say what else to capture. Do not invent "
    "manufacturer-specific procedures you aren't certain about."
)


def is_available() -> bool:
    return Anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def unavailable_reason() -> str:
    if Anthropic is None:
        return "The 'anthropic' package isn't installed (pip install -r requirements.txt)."
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "ANTHROPIC_API_KEY is not set in the environment."
    return ""


def _extract_text(message) -> str:
    parts = []
    for block in message.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def interpret(
    prompt_body: str,
    vehicle: Optional[str] = None,
    max_tokens: int = 4000,
    system: Optional[str] = None,
) -> str:
    """Send a formatted summary to Claude and return its analysis.

    `system` overrides the default diagnostic persona — the tuning module
    passes its own so the advice is framed for calibration work.
    """
    if not is_available():
        raise RuntimeError(unavailable_reason())

    client = Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    context = f"Vehicle: {vehicle}\n\n" if vehicle else ""
    message = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        thinking={"type": "adaptive"},
        system=system or SYSTEM_PROMPT,
        messages=[{"role": "user", "content": context + prompt_body}],
    )
    return _extract_text(message)
