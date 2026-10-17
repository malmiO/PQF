"""v1.5.0 (2026-10-17) video framing: the product is fitted from its bounding box on the
feature and end cards, centred, never clipped; the end card holds at least 50 % of the
frame height; the film does not end on empty frames. Rendering only; no framework change."""
import cv2
import numpy as np
import pytest

from backend.video import promo as P
from backend.video.plan import ProductInfo, build_plan

W, H = P.FORMATS["vertical"]


def _photo(w=1080, h=1920, pw=300, ph=380):
    img = np.full((h, w, 3), 230, np.uint8)
    x, y = (w - pw) // 2, (h - ph) // 2
    cv2.rectangle(img, (x, y), (x + pw, y + ph), (40, 60, 190), -1)
    return img


def _report(kind, **photo):
    img = _photo(**photo)
    cy, fill = P.LAYOUT["vertical"][kind]
    cap = {"feature": P.FEATURE_MAX_UPSCALE, "end": P.END_MAX_UPSCALE}[kind]
    wf = P.FEATURE_WIDTH_FILL if kind == "feature" else P.MAX_WIDTH_FILL
    plate, to_plate = P._plate(img, W, H, fill, cy, wf, max_upscale=cap)
    return P.framing_report(img, plate, to_plate, W, H, P.MOTION[kind], cy)


def test_end_card_product_is_at_least_half_the_frame_height_and_not_clipped():
    r = _report("end")
    assert r["height_frac"] >= 0.50 - 1e-6 and not r["clipped"]


def test_feature_card_of_a_tall_product_reaches_sixty_percent_and_is_not_clipped():
    r = _report("feature", pw=200, ph=420)
    assert r["height_frac"] >= 0.58 and not r["clipped"]


def test_feature_card_of_a_wide_product_is_width_limited_but_larger_than_the_old_34_percent():
    r = _report("feature")              # 300 x 380: the label columns limit the width
    assert r["height_frac"] > 0.40 and not r["clipped"]


def test_end_card_text_stays_above_the_product_inside_the_safe_band():
    cy, fill = P.LAYOUT["vertical"]["end"]
    assert P.LAYOUT["vertical"]["end_limit"] <= cy - fill / 2          # text above product
    assert P.LAYOUT["vertical"]["end_limit"] <= 1 - P.SAFE["vertical"][1]
    shot = {"kind": "end", "price": "Rs. 350", "cta": "Message us to order: 0771234567",
            "contact": "", "shop": "Malmi Crafts"}
    layer = P._text_layer(shot, "vertical", (W, H), (31, 58, 99))
    rows = np.flatnonzero(np.asarray(layer)[..., 3].max(axis=1) > 0)
    assert rows.max() <= P.LAYOUT["vertical"]["end_limit"] * H + 2
    assert rows.min() >= P.SAFE["vertical"][0] * H - 1


def test_framing_is_recorded_and_the_last_frames_are_not_empty(tmp_path):
    from backend.video.builder import ffmpeg_binary
    ff = ffmpeg_binary()
    if not ff:
        pytest.skip("ffmpeg not available")
    paths = []
    for i in range(3):
        p = tmp_path / f"{i}.jpg"
        cv2.imwrite(str(p), _photo())
        paths.append(p)
    plan = build_plan([("hero_shot", 0), ("angle_shot", 1), ("detail_shot", 2)],
                      ProductInfo(name="Test", price="100", shop="Shop", contact="0771"))
    out = tmp_path / "v.mp4"
    r = P.render_plan(plan, paths, out, ffmpeg_bin=ff)
    assert all("framing" in s for s in r.record["timeline"])
    end = [s for s in r.record["timeline"] if s["kind"] == "end"][0]
    assert end["framing"]["height_frac"] >= 0.5 and not end["framing"]["clipped"]
    import subprocess
    raw = subprocess.run([ff, "-v", "error", "-sseof", "-0.3", "-i", str(out), "-vf",
                          "scale=108:192", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 192, 108)
    assert len(frames) >= 1 and all(f.mean() > 60 for f in frames)     # never black
