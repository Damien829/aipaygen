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
    adj, notes, scene = ai_refine(_scene(), Adjustments(), "natural", passes=3, backend=ApiBackend(client),
                                  log=lambda m: None)
    assert notes == "lifted" and scene == "landscape"
    assert adj.exposure == 1.0 and adj.shadows == 30
    assert len(client.calls) == 2
    req = client.calls[0]
    assert req["model"] == "claude-opus-5-5"
    assert req["output_config"]["format"]["type"] == "json_schema"
    kinds = [c["type"] for c in req["messages"][0]["content"]]
    assert kinds.count("image") == 2  # original + current edit (no crop given)


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


# --- files and batch behaviour -------------------------------------------------

import shutil
import subprocess
import threading
import urllib.request

import pytest
from PIL import ImageCms

from protune.batch import AiGuard, Options, collect, output_path, process
from protune.io import load, save


def _jpg(path, **kw):
    Image.fromarray((_scene() ** (1 / 2.2) * 255).astype(np.uint8)).save(path, **kw)
    return path


def test_collect_skips_junk_and_prefers_raw(tmp_path):
    for name in ["A.jpg", "B.jpg", "._A.jpg", ".hidden.jpg", "notes.txt"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "B.NEF").write_bytes(b"x")  # RAW twin of B.jpg
    names = [f.name for f in collect([tmp_path])]
    assert names == ["A.jpg", "B.NEF"]


def test_never_overwrites_original(tmp_path):
    src = tmp_path / "IMG.jpg"
    assert output_path(src, tmp_path, "jpg") == tmp_path / "IMG_edited.jpg"
    assert output_path(src, tmp_path / "out", "jpg") == tmp_path / "out" / "IMG.jpg"


def test_one_bad_file_does_not_stop_the_batch(tmp_path):
    bad = tmp_path / "broken.jpg"
    bad.write_bytes(b"not an image")
    r = process(bad, tmp_path / "out" / "broken.jpg", Options())
    assert r["ok"] is False and r["error"]
    good = _jpg(tmp_path / "good.jpg")
    assert process(good, tmp_path / "out" / "good.jpg", Options())["ok"]


def test_ai_failure_falls_back_and_stops_asking(tmp_path):
    class Broken:
        calls = 0

        def ask(self, images, text):
            Broken.calls += 1
            raise RuntimeError("usage limit reached")

    guard = AiGuard(Broken(), max_failures=2)
    for i in range(4):
        r = process(_jpg(tmp_path / f"p{i}.jpg"), tmp_path / "out" / f"p{i}.jpg", Options(ai=True), guard,
                    log=lambda m: None)
        assert r["ok"] and r["source"] == "auto"
    assert Broken.calls == 2  # gave up after two failures instead of trying every photo


def test_sixteen_bit_tiff_round_trip(tmp_path):
    photo = load(_jpg(tmp_path / "a.jpg"))
    grad = np.linspace(0, 1, 4096, dtype=np.float32)
    srgb = np.repeat(np.repeat(grad[None, :, None], 8, 0), 3, 2)
    save(srgb, tmp_path / "out.tif", photo)
    back = load(tmp_path / "out.tif")
    assert back.linear.shape == (8, 4096, 3)
    assert len(np.unique(back.linear[0, :, 0])) > 1000  # far more than 256 levels


def _adobe_rgb_icc() -> bytes:
    """A minimal ICC v2 matrix/TRC profile with Adobe RGB (1998) primaries."""
    import struct

    def s15(v):
        return struct.pack(">i", round(v * 65536))

    def xyz(x, y, z):
        return b"XYZ " + b"\0" * 4 + s15(x) + s15(y) + s15(z)

    name = b"Adobe RGB test\0"
    desc = b"desc" + b"\0" * 4 + struct.pack(">I", len(name)) + name + b"\0" * 8 + b"\0" * 3 + b"\0" * 67
    curv = b"curv" + b"\0" * 4 + struct.pack(">IH", 1, 563) + b"\0\0"  # gamma 2.2
    tags = [(b"desc", desc), (b"wtpt", xyz(0.9642, 1.0, 0.8249)),
            (b"rXYZ", xyz(0.6097, 0.3111, 0.0195)), (b"gXYZ", xyz(0.2053, 0.6257, 0.0609)),
            (b"bXYZ", xyz(0.1492, 0.0632, 0.7446)), (b"rTRC", curv), (b"gTRC", curv), (b"bTRC", curv)]
    offset = 128 + 4 + 12 * len(tags)
    table, data = b"", b""
    for sig, body in tags:
        body += b"\0" * (-len(body) % 4)
        table += sig + struct.pack(">II", offset + len(data), len(body))
        data += body
    size = offset + len(data)
    header = (struct.pack(">I", size) + b"\0" * 4 + bytes([2, 0x10, 0, 0]) + b"mntrRGB XYZ " + b"\0" * 12
              + b"acsp" + b"\0" * 24 + b"\0" * 4 + s15(0.9642) + s15(1.0) + s15(0.8249) + b"\0" * 48)
    return header + struct.pack(">I", len(tags)) + table + data


def test_adobe_rgb_jpeg_is_converted(tmp_path):
    """A JPEG in Adobe RGB is converted to sRGB, not misread (which would look dull)."""
    pix = Image.new("RGB", (8, 8), (40, 180, 90))
    plain, tagged = tmp_path / "plain.jpg", tmp_path / "tagged.jpg"
    pix.save(plain, quality=100)
    pix.save(tagged, quality=100, icc_profile=_adobe_rgb_icc())
    a, b = load(plain).linear.mean((0, 1)), load(tagged).linear.mean((0, 1))
    assert b[0] < a[0] * 0.5  # same numbers mean a purer green in Adobe RGB: red drops after conversion


def test_heic_loads(tmp_path):
    pillow_heif = pytest.importorskip("pillow_heif")
    src = tmp_path / "phone.heic"
    Image.fromarray((_scene() ** (1 / 2.2) * 255).astype(np.uint8)).save(src)
    assert load(src).linear.shape == (300, 450, 3)


@pytest.mark.skipif(not shutil.which("exiftool"), reason="exiftool not installed")
def test_camera_metadata_is_copied(tmp_path):
    src = _jpg(tmp_path / "cam.jpg")
    subprocess.run(["exiftool", "-q", "-overwrite_original", "-Make=Canon", "-Model=EOS R5", "-ISO=3200",
                    "-Orientation#=6", "-Copyright=Me", str(src)], check=True)
    out = tmp_path / "out" / "cam.jpg"
    assert process(src, out, Options())["ok"]
    tags = subprocess.run(["exiftool", "-s", "-s", "-s", "-n", "-Model", "-ISO", "-Copyright", "-Orientation",
                           "-Software", "-ProfileDescription", str(out)], capture_output=True, text=True).stdout.split("\n")
    assert tags[:5] == ["EOS R5", "3200", "Me", "1", "ProTune"]
    assert "sRGB" in tags[5]
    # Orientation 6 = rotated: the edit must be saved upright (portrait shape).
    assert Image.open(out).size == (300, 450)


# --- the app ---------------------------------------------------------------------


def test_app_requires_its_token(tmp_path):
    from http.server import ThreadingHTTPServer

    from protune.app import Studio, make_handler

    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(Studio(), "secret"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/api/status")
        assert e.value.code == 403
        req = urllib.request.Request(base + "/api/status", headers={"X-Token": "secret"})
        assert json.loads(urllib.request.urlopen(req).read())["items"] == []
        html = urllib.request.urlopen(base + "/").read().decode()
        assert '"secret"' in html  # page gets the token
    finally:
        server.shutdown()


def test_big_photos_render_in_strips_identically(monkeypatch):
    import protune.adjust as A

    rng = np.random.default_rng(0)
    img = rng.random((900, 1400, 3), dtype=np.float32) * 0.2
    img[200:600, 300:900] *= 4
    adj = Adjustments(exposure=0.8, shadows=40, highlights=-50, clarity=20, vibrance=20,
                      noise_reduction=40, sharpening=50, vignette=-30)
    whole = A.apply(img, adj)
    monkeypatch.setattr(A, "STRIP_PIXELS", 100_000)
    assert np.abs(whole - A.apply(img, adj)).max() < 1e-4
