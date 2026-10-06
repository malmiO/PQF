"""Auto zoom (v1.1.0): /guidance returns a zoom hint from the framing check it
already runs. No model call; one number added to the existing response."""
import os

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
import backend.api.main as M

client = TestClient(M.app)


def _frame(box, size=(1000, 800), bg=235):
    """A 4:5 frame (no crop needed) with a dark product in `box` (fractions)."""
    h, w = size
    img = np.full((h, w, 3), bg, np.uint8)
    x0, y0, x1, y1 = (int(v * s) for v, s in zip(box, (w, h, w, h)))
    cv2.rectangle(img, (x0, y0), (x1, y1), (40, 60, 160), -1)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def _hint(box, shot="main"):
    r = client.post("/guidance", files={"file": ("f.jpg", _frame(box), "image/jpeg")},
                    data={"shot": shot})
    assert r.status_code == 200, r.text
    return r.json()["zoom_hint"]


def test_small_centred_product_asks_to_zoom_in_towards_the_target():
    k = _hint((0.42, 0.42, 0.58, 0.58))             # about 2.6 % of the frame
    assert k > 1.5
    area_after = 0.0256 * k * k
    assert area_after <= M.GUIDANCE_ZOOM_TARGET_AREA["main"] + 0.01


def test_well_framed_product_needs_no_zoom():
    assert _hint((0.25, 0.22, 0.75, 0.78)) == 1.0   # about 28 %, inside the range


def test_cut_off_product_asks_to_zoom_out():
    assert _hint((0.0, 0.1, 0.6, 0.9)) < 1.0


def test_off_centre_product_is_never_zoomed_out_of_the_frame():
    box = (0.62, 0.42, 0.74, 0.56)                    # small and to the right
    k = _hint(box)
    reach = max(abs(box[2] - 0.5), abs(box[0] - 0.5), abs(box[3] - 0.5),
                abs(box[1] - 0.5)) * 2
    assert k * reach <= M.GUIDANCE_ZOOM_EDGE_LIMIT + 0.02


def test_hint_never_jumps_more_than_two_times():
    assert _hint((0.48, 0.48, 0.52, 0.52)) <= 2.0


def test_zoom_hint_helper_dead_band_and_range():
    assert M._zoom_hint({"area": 0.30, "reach": 0.5}, "main", 0.10, 0.68) == 1.0
    assert M._zoom_hint({"area": 0.095, "reach": 0.3}, "main", 0.10, 0.68) > 1.0
    assert M._zoom_hint({"area": 0.80, "reach": 0.95}, "main", 0.10, 0.68) < 1.0
    assert M._zoom_hint({}, "detail", 0.30, 1.0) == 1.0
