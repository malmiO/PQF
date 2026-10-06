"""Step 3 (v1.1.0): callouts fall back to captions when their layout would mislead."""
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.video import features as F
from backend.video import promo as P

client = TestClient(app)
REAL = Path(__file__).resolve().parents[2] / "test-img" / \
    "WhatsApp Image 2026-10-05 at 1.39.48 PM (2).jpeg"
LABELS = ["Silver clasp", "Red apple", "Painted letters"]


def _photo():
    img = np.full((1350, 1080, 3), 208, np.uint8)
    cv2.rectangle(img, (380, 300), (700, 1000), (40, 60, 200), -1)
    return img


def _callouts(points):
    return [{"label": l, "x": x, "y": y} for l, (x, y) in zip(LABELS, points)]


def test_three_identical_points_are_rejected_by_rule_a():
    g = P.callout_guard(_photo(), _callouts([(0.5, 0.5)] * 3), "vertical")
    assert g["ok"] is False and g["rule"] == "a"


def test_point_outside_the_product_is_rejected_by_rule_c():
    g = P.callout_guard(_photo(), _callouts([(0.5, 0.3), (0.5, 0.6), (0.05, 0.95)]),
                        "vertical")
    assert g["ok"] is False and g["rule"] == "c"


def test_crossing_lines_are_rejected_by_rule_b(monkeypatch):
    real = P.layout_callouts

    def crossed(callouts, pts, *a, **k):
        items = real(callouts, pts, *a, **k)
        # line 0 runs straight down from its point; line 1 comes in from the left
        # and passes through it, so the two lines cross
        (x0, y0), (x1, y1) = pts[0], pts[1]
        by_i = {it["i"]: it for it in items}
        by_i[0]["anchor"] = (x0, y1 + 100)
        by_i[1]["anchor"] = (x0 - 200, (y0 + y1) / 2)
        return items
    monkeypatch.setattr(P, "layout_callouts", crossed)
    g = P.callout_guard(_photo(), _callouts([(0.45, 0.30), (0.55, 0.55), (0.5, 0.70)]),
                        "vertical")
    assert g["ok"] is False and g["rule"] == "b"


def test_segments_cross_helper():
    assert P._segments_cross((0, 0), (10, 10), (0, 10), (10, 0))
    assert not P._segments_cross((0, 0), (10, 0), (0, 5), (10, 5))


@pytest.mark.skipif(not REAL.exists(), reason="real keychain photo not present")
def test_real_good_case_still_gives_callouts():
    img = cv2.imread(str(REAL))
    pts = [(0.48, 0.25), (0.48, 0.41), (0.52, 0.54)]      # measured live 2026-10-06
    for fmt in ("vertical", "square"):
        assert P.callout_guard(img, _callouts(pts), fmt)["ok"] is True


def test_api_falls_back_to_captions_and_records_the_rule(monkeypatch):
    same = [230, 440, 310, 560]
    monkeypatch.setattr(F, "_call_model", lambda *a: json.dumps(
        [{"label": l, "box_2d": same} for l in LABELS]))
    jpg = cv2.imencode(".jpg", _photo())[1].tobytes()
    r = client.post("/video/plan",
                    files=[("files", (f"{i}.jpg", jpg, "image/jpeg")) for i in range(4)],
                    data={"roles": "hero_shot,angle_shot,angle_shot,detail_shot",
                          "product_name": "Keychain", "features": "\n".join(LABELS)})
    assert r.status_code == 200, r.text[:300]
    plan = r.json()
    assert plan["callout_guard"]["ok"] is False and plan["callout_guard"]["rule"] == "a"
    assert not any(s["kind"] == "feature" for s in plan["shots"])
    captions = [s.get("caption") for s in plan["shots"]]
    assert all(l in captions for l in LABELS)
