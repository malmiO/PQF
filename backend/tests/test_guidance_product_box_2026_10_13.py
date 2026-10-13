"""/guidance exposes the product box it already computes, as an ADDITIVE field
(normalised x,y,w,h in the 4:5 region, or null). These tests prove the field is
purely additive: no existing field or framing decision changes (2026-10-13)."""
import os
import pathlib

import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import main as M
from backend.pqf import technical as T

client = TestClient(app)

# The GuidanceResponse fields that existed BEFORE product_box was added.
EXISTING_KEYS = {"ready", "checks", "feedback", "elapsed_ms",
                 "exposure_hint", "zoom_hint"}


def _frame(W=288, H=512, band=0.12, frac=0.30, shift=0.0):
    f = np.full((H, W, 3), 245, np.uint8)
    b = int(H * band)
    if b:
        f[:b] = (70, 90, 110)
        f[H - b:] = (60, 70, 80)
    s = int(W * frac ** 0.5 * 1.1)
    cx, cy = int(W / 2 + shift * W), H // 2
    cv2.rectangle(f, (cx - s // 2, cy - int(s * .8)),
                  (cx + s // 2, cy + int(s * .8)), (30, 110, 200), -1)
    return cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def _guide(b, **form):
    return client.post("/guidance",
                       files={"file": ("f.jpg", b, "image/jpeg")},
                       data=form).json()


def _assert_additive(r):
    assert "product_box" in r
    box = r["product_box"]
    assert box is None or (
        isinstance(box, list) and len(box) == 4
        and all(isinstance(v, (int, float)) and 0.0 <= v <= 1.0 for v in box)
    ), box
    # product_box is the ONLY new key; everything else is the pre-existing set.
    assert set(r.keys()) - {"product_box"} == EXISTING_KEYS, set(r.keys())


def test_product_box_is_additive_and_normalised():
    for b in [_frame(), _frame(frac=0.03), _frame(frac=0.9, band=0.0),
              _frame(shift=0.25)]:
        _assert_additive(_guide(b))


def test_box_does_not_change_the_framing_decision():
    # Before/after: the SAME frame measured with and without the info dict must
    # return an identical (score, message). The box is recorded, never acted on.
    for b in [_frame(), _frame(frac=0.03), _frame(frac=0.9, band=0.0),
              _frame(shift=0.25), _frame(frac=0.6)]:
        img = cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)
        img = M._crop_to_platform(img)
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > M.GUIDANCE_LONGEST_SIDE:
            s = M.GUIDANCE_LONGEST_SIDE / longest
            img = cv2.resize(img, (int(w * s), int(h * s)),
                             interpolation=cv2.INTER_AREA)
        mn, mx, edges = M.GUIDANCE_SHOT_FRAMING["main"]
        s0, m0 = M._framing_check(img, T, mn, mx, edges, None)
        info = {}
        s1, m1 = M._framing_check(img, T, mn, mx, edges, info)
        assert s0 == s1 and m0 == m1, (s0, m0, s1, m1)
        if "box" in info:
            assert len(info["box"]) == 4
            assert all(0.0 <= v <= 1.0 for v in info["box"]), info["box"]


def test_real_fixtures_return_additive_box():
    fx = pathlib.Path(__file__).parent / "fixtures"
    images = sorted(fx.glob("*.jpg"))
    assert images, "expected fixture images"
    for p in images:
        _assert_additive(_guide(p.read_bytes()))
