"""Step 4 (v1.1.0): the "Ready to post" checklist is measured from the finished
video, and every item carries met, measured and threshold."""
import os

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.video.measure import checklist, measure_video
from backend.video.plan import build_plan, ProductInfo
from backend.video.promo import FORMATS, LAYOUT, SAFE, render_plan, _text_layer
from backend.video.settings import FILL_MIN

try:
    from backend.video.builder import ffmpeg_available, ffmpeg_binary
except Exception:                                      # pragma: no cover
    import shutil
    ffmpeg_available = lambda: shutil.which("ffmpeg") is not None
    ffmpeg_binary = lambda: shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
client = TestClient(app)


def _write(tmp_path, n, box):
    paths = []
    for i in range(n):
        img = np.full((1350, 1080, 3), 214, np.uint8)
        x0, y0, x1, y1 = box
        cv2.rectangle(img, (x0 + 6 * i, y0), (x1 + 6 * i, y1), (40, 60, 200), -1)
        p = tmp_path / f"img_{i:02d}.img"
        p.write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
        paths.append(p)
    return paths


def _render(tmp_path, box, fmt="vertical"):
    paths = _write(tmp_path, 3, box)
    plan = build_plan([("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2)],
                      ProductInfo(name="Keychain"), fmt, None, None)
    r = render_plan(plan, paths, tmp_path / "out.mp4", ffmpeg_bin=ffmpeg_binary())
    m = measure_video(r.path, r.record, ffmpeg_binary())
    return checklist(plan, r.record, m), m


def _rule(items, name):
    return next(c for c in items if c["rule"] == name)


@needs_ffmpeg
def test_small_product_is_reported_not_met_with_its_value(tmp_path):
    items, m = _render(tmp_path, (515, 640, 565, 700))     # 50 x 60 px: capped upscale
    fill = _rule(items, "Product fills the frame")
    assert fill["met"] is False
    assert fill["measured"] < FILL_MIN and fill["threshold"] == FILL_MIN
    assert f"{fill['measured'] * 100:.0f} %" in fill["detail"]


@needs_ffmpeg
def test_normal_product_fills_its_zone_and_stays_centred(tmp_path):
    items, m = _render(tmp_path, (380, 330, 700, 1000))
    assert _rule(items, "Product fills the frame")["met"] is True
    cx = [s["cx"] for s in m["shots"] if s["kind"] in ("hook", "angle")]
    assert max(cx) - min(cx) <= 0.03
    assert _rule(items, "Brightness consistent")["met"] is True
    assert all({"met", "measured", "threshold"} <= set(c) for c in items)


@needs_ffmpeg
def test_render_api_saves_the_measured_checklist_with_the_plan():
    img = np.full((1350, 1080, 3), 214, np.uint8)
    cv2.rectangle(img, (380, 330), (700, 1000), (40, 60, 200), -1)
    jpg = cv2.imencode(".jpg", img)[1].tobytes()
    plan = client.post("/video/plan", files=[("files", (f"{i}.jpg", jpg, "image/jpeg"))
                                             for i in range(3)],
                       data={"roles": "hero_shot,angle_shot,angle_shot",
                             "product_name": "Keychain"}).json()
    v = client.post("/video/render", data={"plan_id": plan["plan_id"]})
    assert v.status_code == 200, v.text[:300]
    saved = client.get(f"/video/plan/{plan['plan_id']}").json()
    assert saved["checklist_source"] == "measured"
    rules = {c["rule"] for c in saved["checklist"]}
    assert {"Product fills the frame", "Brightness consistent",
            "Product colour preserved"} <= rules
    assert all(c["threshold"] is not None for c in saved["checklist"])
    assert _rule(saved["checklist"], "Brand early and at the end")["met"] is False
    assert "/" in v.headers["x-video-checklist"]


@pytest.mark.parametrize("fmt", ["vertical", "square"])
@pytest.mark.parametrize("kind", ["hook", "angle", "detail", "end"])
def test_text_stays_inside_safe_zones_in_every_format(fmt, kind):
    W, H = FORMATS[fmt]
    shot = {"kind": kind, "caption": "A fairly long caption that wraps", "kicker": "SHOP",
            "price": "Rs. 450", "cta": "Message us to order", "contact": "077 123 4567",
            "shop": "My shop"}
    layer = _text_layer(shot, fmt, (W, H), (31, 58, 99))
    a = np.asarray(layer)[..., 3]
    rows = np.flatnonzero(a.max(axis=1) > 0)
    top, bottom, _ = SAFE[fmt]
    assert rows.min() >= top * H - 1
    assert rows.max() <= (1 - bottom) * H + 1


def test_video_uses_only_the_scored_region_of_a_tall_photo(tmp_path):
    """A 9:16 capture is cropped to the scored 4:5 region before rendering, so its
    top and bottom strips (here dark, like a light box edge) never reach the video."""
    img = np.full((1920, 1080, 3), 214, np.uint8)
    img[:250] = 40                                   # dark strips outside 4:5
    img[-250:] = 40
    cv2.rectangle(img, (420, 700), (660, 1200), (40, 60, 200), -1)
    jpg = cv2.imencode(".jpg", img)[1].tobytes()
    plan = client.post("/video/plan", files=[("files", ("a.jpg", jpg, "image/jpeg"))],
                       data={"roles": "hero_shot", "product_name": "K"}).json()
    from backend.api.video_api import SESSIONS
    stored = cv2.imdecode(np.frombuffer(
        (SESSIONS / plan["plan_id"] / "img_00.img").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    h, w = stored.shape[:2]
    assert abs(w / h - 0.8) < 0.01                   # the 4:5 region
    assert stored[:20].mean() > 150 and stored[-20:].mean() > 150   # no dark strips
