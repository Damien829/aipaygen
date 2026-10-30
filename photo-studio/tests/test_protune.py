import json
from types import SimpleNamespace

import numpy as np
from PIL import Image

from protune import Adjustments, apply, auto_adjust
from protune.adjust import luminance
from protune.ai import ApiBackend, ai_refine
from protune.cli import main


def _scene(h=300, w=450, gain=0.25, cast=(1.2, 1.0, 0.75), seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    img = np.where((yy / h > 0.55)[..., None], [0.15, 0.3, 0.05], [0.25, 0.4, 0.75]).astype(np.float32)
    img[h // 3: 2 * h // 3, w // 3: 2 * w // 3] = [0.8, 0.8, 0.8]  # neutral grey card
    img = img * gain * np.array(cast, np.float32)
    return np.clip(img + rng.normal(0, 0.002, img.shape), 0, 1).astype(np.float32)


def test_neutral_settings_change_almost_nothing():
    img = _scene(gain=1.0, cast=(1, 1, 1))
    out = apply(img, Adjustments())
    from protune.adjust import linear_to_srgb
    assert np.abs(out - linear_to_srgb(img)).mean() < 0.02


def test_auto_fixes_underexposure_and_colour_cast():
    img = _scene()
    adj = auto_adjust(img, is_raw=True)
    assert adj.exposure > 0.5
    assert adj.temperature < 0  # cools down the warm cast
    out = apply(img, adj)
    assert 0.3 < np.median(luminance(out)) < 0.6
    card = out[130:170, 190:260].reshape(-1, 3).mean(0)
    assert card.max() - card.min() < 0.06  # grey card is grey again


def test_settings_are_clamped():
    adj = Adjustments.from_dict({"exposure": 50, "shadows": -999, "bogus": 1})
    assert adj.exposure == 3.0 and adj.shadows == -100


def test_monochrome():
    out = apply(_scene(), Adjustments(monochrome=True, exposure=1))
    assert np.allclose(out[..., 0], out[..., 1]) and np.allclose(out[..., 1], out[..., 2])


class FakeClient:
    """Stands in for anthropic.Anthropic and records what was sent."""

    def __init__(self, answers):
        self.answers, self.calls = list(answers), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.answers.pop(0))
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def test_ai_refine_returns_only_slider_values():
    first = {**Adjustments(exposure=1.0, shadows=30).to_dict(), "scene": "landscape", "notes": "lifted"}
    client = FakeClient([first, first])  # second pass agrees -> stops
    adj = ai_refine(_scene(), Adjustments(), "natural", passes=3, backend=ApiBackend(client),
                    log=lambda m: None)
    assert adj.exposure == 1.0 and adj.shadows == 30
    assert len(client.calls) == 2
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    kinds = [c["type"] for c in req["messages"][0]["content"]]
    assert kinds.count("image") == 2  # original + current edit


def test_cli_end_to_end(tmp_path):
    src = tmp_path / "shot.jpg"
    Image.fromarray((_scene() ** (1 / 2.2) * 255).astype(np.uint8)).save(src)
    assert main([str(src), "--compare", "--set", "vignette=-20"]) == 0
    out = tmp_path / "edited"
    assert (out / "shot.jpg").exists() and (out / "shot_before_after.jpg").exists()
    settings = json.loads((out / "shot.json").read_text())
    assert settings["vignette"] == -20
    # Re-running with the saved settings reproduces the edit exactly.
    assert main([str(src), "--settings", str(out / "shot.json"), "-o", str(tmp_path / "again")]) == 0
    a = np.asarray(Image.open(out / "shot.jpg"), np.int16)
    b = np.asarray(Image.open(tmp_path / "again" / "shot.jpg"), np.int16)
    assert np.abs(a - b).max() <= 1
