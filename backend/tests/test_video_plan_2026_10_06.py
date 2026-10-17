"""Automatic marketing video (2026-10-06): plan from the product form, feature
callouts, safe zones, checklist, post kit, and the two call API with no approval."""
import json
import os

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.video import features as F
from backend.video.plan import build_plan, ProductInfo, post_kit, MAX_SECONDS
from backend.video.promo import (_text_layer, layout_callouts, LAYOUT, FORMATS,
                                 MOOD_STYLE, SAFE)

client = TestClient(app)
try:
    from backend.video.builder import ffmpeg_available
except Exception:
    import shutil
    ffmpeg_available = lambda: shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")

INFO = ProductInfo(name="Teacher's Day Book Charm", price="Rs. 450",
                   features=["Silver clasp", "Red apple", "Hand-painted titles"],
                   category="accessories", mood="upbeat")
SET = [("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2), ("detail_shot", 3)]
LOCATED = {"points": [(0.5, 0.2), (0.45, 0.4), None], "source": "model", "error": ""}


def _photo(angle=0):
    f = np.full((1350, 1080, 3), 208, np.uint8)
    M = cv2.getRotationMatrix2D((540, 675), angle, 1.0)
    obj = np.full((1350, 1080, 3), 208, np.uint8)
    cv2.rectangle(obj, (430, 420), (650, 930), (40, 60, 200), -1)
    cv2.circle(obj, (540, 360), 60, (30, 160, 60), -1)
    obj = cv2.warpAffine(obj, M, (1080, 1350), borderValue=(208, 208, 208))
    return cv2.imencode(".jpg", obj, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


# ---------------------------------------------------------------- plan
def test_plan_order_and_owner_words_only():
    plan = build_plan(SET, INFO, "vertical", LOCATED)
    kinds = [s["kind"] for s in plan["shots"]]
    assert kinds[0] == "hook" and kinds[-1] == "end" and "feature" in kinds
    assert plan["shots"][0]["caption"] == INFO.name
    feat = next(s for s in plan["shots"] if s["kind"] == "feature")
    assert [c["label"] for c in feat["callouts"]] == ["Silver clasp", "Red apple"]
    # the feature that was NOT found becomes a caption, so nothing is lost
    captions = [s.get("caption") for s in plan["shots"] if s["kind"] in ("angle", "detail")]
    assert "Hand-painted titles" in captions
    shown = {c["label"] for c in feat["callouts"]} | set(filter(None, captions))
    assert shown <= set(INFO.features) | {INFO.name}


def test_no_callouts_when_features_cannot_be_located():
    plan = build_plan(SET, INFO, "vertical", {"points": [None] * 3, "source": "unavailable",
                                              "error": "GEMINI_API_KEY not set"})
    assert all(s["kind"] != "feature" for s in plan["shots"])
    assert plan["callout_source"] == "unavailable"
    item = next(c for c in plan["checklist"] if c["rule"] == "Key features shown")
    assert item["met"]


@pytest.mark.parametrize("mood", ["calm", "elegant", "upbeat"])
def test_duration_is_short_form_for_every_mood_with_five_images(mood):
    five = SET + [("angle_shot", 4)]
    info = ProductInfo(**{**INFO.__dict__, "mood": mood})
    plan = build_plan(five, info, "vertical", {"points": [(.5, .2), (.45, .4), (.5, .6)],
                                               "source": "model", "error": ""})
    assert 8.0 <= plan["duration_seconds"] <= MAX_SECONDS


def test_checklist_reports_missing_brand_until_profile_exists():
    plan = build_plan(SET, INFO, "vertical", LOCATED)
    brand = next(c for c in plan["checklist"] if c["rule"].startswith("Brand"))
    assert brand["met"] is False and "profile" in brand["detail"]
    with_shop = ProductInfo(**{**INFO.__dict__, "shop": "Nethmi Crafts"})
    plan2 = build_plan(SET, with_shop, "vertical", LOCATED)
    assert next(c for c in plan2["checklist"] if c["rule"].startswith("Brand"))["met"]
    assert plan2["shots"][0]["kicker"] == "Nethmi Crafts"


def test_post_kit_has_caption_cta_and_hashtags():
    kit = post_kit(ProductInfo(**{**INFO.__dict__, "contact": "077 123 4567"}).clean())
    assert INFO.name in kit["caption"] and "Rs. 450" in kit["caption"]
    assert "077 123 4567" in kit["caption"] and kit["hashtags"]
    assert all(t.startswith("#") for t in kit["hashtags"])


def test_form_input_is_trimmed():
    i = ProductInfo(name="x" * 90, features=["a" * 50, "b", "c", "d"], mood="disco").clean()
    assert len(i.name) <= 40 and len(i.features) == 3 and len(i.features[0]) <= 30
    assert i.mood == ""


# ---------------------------------------------------------------- callout safety
def test_feature_box_validation_rejects_bad_and_whole_product_boxes():
    assert F.validate_box([100, 100, 200, 200]) == (0.15, 0.15)
    assert F.validate_box([0, 0, 1000, 1000]) is None           # whole photo
    assert F.validate_box([500, 500, 400, 600]) is None         # inverted
    assert F.validate_box(None) is None
    assert F.validate_box([10, 10, 30, 30], (0.4, 0.4, 0.6, 0.6)) is None  # off product


def test_locate_features_survives_model_failure():
    def broken(*a):
        raise RuntimeError("quota")
    r = F.locate_features(_photo(), ["clasp"], call=broken)
    assert r["points"] == [None] and r["source"] == "unavailable"


def test_locate_features_parses_model_json():
    raw = json.dumps([{"label": "clasp", "box_2d": [300, 450, 380, 550]}])
    r = F.locate_features(_photo(), ["clasp"], call=lambda *a: "```json\n" + raw + "\n```")
    assert r["points"][0] is not None and r["source"] == "model"


# ---------------------------------------------------------------- layout
@pytest.mark.parametrize("fmt", ["vertical", "square"])
@pytest.mark.parametrize("kind", ["hook", "angle", "detail"])
def test_text_never_covers_the_product_zone(fmt, kind):
    W, H = FORMATS[fmt]
    shot = {"kind": kind, "caption": "A Very Long Handmade Product Name For Testing It",
            "kicker": "Nethmi Crafts"}
    alpha = np.asarray(_text_layer(shot, fmt, (W, H), (31, 58, 99)))[..., 3]
    cy, fill = LAYOUT[fmt][kind]
    assert alpha[int((cy - fill / 2) * H):int((cy + fill / 2) * H)].max() == 0


def test_vertical_text_respects_platform_safe_zones():
    W, H = FORMATS["vertical"]
    shots = [{"kind": "hook", "caption": "Name", "kicker": "Shop"},
             {"kind": "angle", "caption": "p"}, {"kind": "feature"},
             {"kind": "end", "price": "Rs. 450", "cta": "Message us to order:",
              "contact": "WhatsApp 077 123 4567", "shop": "Shop"}]
    for shot in shots:
        a = np.asarray(_text_layer(shot, "vertical", (W, H), (31, 58, 99)))[..., 3]
        assert a[: int(0.14 * H)].max() == 0
        assert a[int(0.65 * H):].max() == 0


@pytest.mark.parametrize("fmt", ["vertical", "square"])
def test_callout_labels_stay_beside_the_product_and_inside_safe_band(fmt):
    W, H = FORMATS[fmt]
    callouts = [{"label": "Silver lobster clasp"}, {"label": "Shiny red apple"},
                {"label": "Hand-painted book titles"}]
    pts = [(W * 0.52, H * 0.25), (W * 0.47, H * 0.40), (W * 0.55, H * 0.55)]
    items = layout_callouts(callouts, pts, fmt, (W, H), (31, 58, 99),
                            product_x=(W * 0.32, W * 0.68))
    lo, hi = LAYOUT[fmt]["label_band"]
    boxes = []
    for it in items:
        x, y, w, h = it["x"], it["y"], it["img"].width, it["img"].height
        assert x + w <= W * 0.32 or x >= W * 0.68          # never over the product
        assert y >= lo * H - 1 and y + h <= hi * H + 1     # inside the safe band
        boxes.append((x, y, x + w, y + h))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_calm_is_slower_than_upbeat():
    assert MOOD_STYLE["calm"]["pace"] > MOOD_STYLE["upbeat"]["pace"]


# ---------------------------------------------------------------- API, no approval step
@needs_ffmpeg
def test_plan_then_render_with_no_owner_input_in_between(monkeypatch):
    monkeypatch.setattr(F, "_call_model", lambda *a: json.dumps(
        [{"label": "x", "box_2d": [230, 440, 310, 560]}, {"label": "y", "box_2d": None}]))
    files = [("files", (f"{i}.jpg", _photo(a), "image/jpeg"))
             for i, a in enumerate((0, 30, -30, 0))]
    r = client.post("/video/plan", files=files, data={
        "roles": "hero_shot,angle_shot,angle_shot,detail_shot", "format": "vertical",
        "product_name": "Keychain", "price": "Rs. 450", "features": "Green top\nBlue body",
        "category": "accessories"})
    assert r.status_code == 200, r.text[:300]
    plan = r.json()
    assert plan["plan_id"] and plan["checklist"] and plan["post"]["caption"]
    assert any(s["kind"] == "feature" for s in plan["shots"])
    v = client.post("/video/render", data={"plan_id": plan["plan_id"]})
    assert v.status_code == 200, v.text[:300]
    assert v.headers["content-type"] == "video/mp4"
    assert 8.0 <= float(v.headers["x-video-duration"]) <= 15.0
    assert client.get(f"/video/plan/{plan['plan_id']}").json()["plan_id"] == plan["plan_id"]


def test_plan_rejects_mismatched_roles_and_bad_ids():
    files = [("files", ("a.jpg", _photo(), "image/jpeg"))]
    assert client.post("/video/plan", files=files, data={"roles": "hero_shot,angle_shot"}).status_code == 400
    assert client.post("/video/render", data={"plan_id": "../etc"}).status_code == 400
    assert client.post("/video/render", data={"plan_id": "0" * 32}).status_code == 404
