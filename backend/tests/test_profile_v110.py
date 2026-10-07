"""Business profile (v1.1.0, Part C): shop name, contact and brand colour reach the
plan and the video, and "Brand early and at the end" is measured from the render."""
import os

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.video.measure import checklist, measure_video
from backend.video.plan import build_plan, ProductInfo
from backend.video.promo import render_plan

try:
    from backend.video.builder import ffmpeg_available, ffmpeg_binary
except Exception:                                      # pragma: no cover
    import shutil
    ffmpeg_available = lambda: shutil.which("ffmpeg") is not None
    ffmpeg_binary = lambda: shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")
client = TestClient(app)


def _jpg():
    img = np.full((1350, 1080, 3), 214, np.uint8)
    cv2.rectangle(img, (380, 330), (700, 1000), (40, 60, 200), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def _plan(**form):
    files = [("files", (f"{i}.jpg", _jpg(), "image/jpeg")) for i in range(3)]
    r = client.post("/video/plan", files=files, data={
        "roles": "hero_shot,angle_shot,angle_shot", "product_name": "Keychain", **form})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def test_plan_carries_the_profile():
    plan = _plan(shop="Malmi Crafts", contact="077 123 4567", brand_colour="#8E244D")
    hook = plan["shots"][0]
    end = plan["shots"][-1]
    assert hook["kicker"] == "Malmi Crafts"
    assert end["shop"] == "Malmi Crafts" and end["contact"] == "077 123 4567"
    assert plan["brand_colour"] == "#8E244D"
    assert "077 123 4567" in plan["post"]["caption"]


def test_bad_colour_falls_back_to_the_default():
    assert _plan(brand_colour="red; drop")["brand_colour"] == "#1F3A63"


@needs_ffmpeg
@pytest.mark.parametrize("shop,met", [("Malmi Crafts", True), ("", False)])
def test_brand_item_is_measured_from_the_render(tmp_path, shop, met):
    paths = []
    for i in range(3):
        p = tmp_path / f"img_{i:02d}.img"
        p.write_bytes(_jpg())
        paths.append(p)
    plan = build_plan([("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2)],
                      ProductInfo(name="Keychain", shop=shop, contact="077 123 4567"),
                      "vertical", None, None)
    r = render_plan(plan, paths, tmp_path / "out.mp4", ffmpeg_bin=ffmpeg_binary())
    items = checklist(plan, r.record, measure_video(r.path, r.record, ffmpeg_binary()))
    brand = next(c for c in items if c["rule"] == "Brand early and at the end")
    assert brand["met"] is met
    if met:
        assert brand["measured"] == "first shot, end card"
    else:
        assert "My shop" in brand["detail"]
