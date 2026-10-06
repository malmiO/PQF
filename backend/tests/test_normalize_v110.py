"""Step 1 (v1.1.0): consistent background brightness in the video without changing
the product's colour. L* only, soft knee, CIEDE2000 fidelity guard."""
import hashlib

import cv2
import numpy as np
import pytest

from backend.video import normalize as N
from backend.video.settings import MAX_PRODUCT_DE00, TARGET_BG_L_MIN

try:
    from backend.video.builder import ffmpeg_available, ffmpeg_binary
except Exception:                                      # pragma: no cover
    import shutil
    ffmpeg_available = lambda: shutil.which("ffmpeg") is not None
    ffmpeg_binary = lambda: shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed")


def _scene(bg, product, box=(300, 400, 700, 900), size=(1100, 1000)):
    img = np.full((size[0], size[1], 3), bg, np.uint8)
    x0, y0, x1, y1 = box
    img[y0:y1, x0:x1] = product
    mask = np.zeros(img.shape[:2], bool)
    mask[y0:y1, x0:x1] = True
    return img, mask


def test_grey_background_is_lifted_to_the_target():
    # a near black product barely changes under a gain, so the guard does not bind
    img, mask = _scene((222, 222, 222), (12, 12, 12))
    out, rec = N.correct(img, mask, TARGET_BG_L_MIN)
    assert rec["bg_l_before"] < TARGET_BG_L_MIN - 1
    assert abs(N.background_white(out, mask) - TARGET_BG_L_MIN) < 0.6
    assert not rec["guard_limited"]


def test_saturated_red_product_stays_within_de00_and_guard_is_recorded():
    img, mask = _scene((200, 200, 200), (30, 30, 200))       # BGR: saturated red
    out, rec = N.correct(img, mask, TARGET_BG_L_MIN)
    assert rec["guard_limited"] is True                     # gain was capped
    assert rec["gain"] < rec["gain_wanted"]
    assert rec["product_de00"] <= MAX_PRODUCT_DE00 + 1e-6
    measured = N.deltaE_ciede2000(N.to_lab(img)[mask], N.to_lab(out)[mask]).mean()
    assert measured <= MAX_PRODUCT_DE00 + 0.15              # 8 bit rounding
    assert N.background_white(out, mask) > rec["bg_l_before"]  # still lifted a little


def test_only_lightness_changes():
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (60, 60, 3), dtype=np.uint8)
    lab = N.to_lab(img)
    for g in (0.9, 1.05, 1.15):
        out = N.apply_gain(lab, g)
        assert np.array_equal(out[..., 1:], lab[..., 1:])
        assert out[..., 0].max() <= 100.0


def test_gain_one_is_exactly_the_identity_and_white_stays_white():
    L = np.linspace(0, 100, 201)
    assert np.allclose(N._lift(L.copy(), 1.0), L)
    lifted = N._lift(L.copy(), 1.1)
    assert abs(lifted[-1] - 100.0) < 1e-9                   # no clipping, no overshoot
    assert np.all(np.diff(lifted) > 0)                      # monotonic: no banding


def test_match_set_targets_the_main_shot_but_not_below_minimum():
    a, ma = _scene((250, 250, 250), (12, 12, 12))           # main: L* about 98
    b, mb = _scene((228, 228, 228), (12, 12, 12))
    _, recs, target = N.match_set([a, b], [ma, mb], main_index=0)
    assert target == pytest.approx(recs[0]["bg_l_before"], abs=0.01)
    assert target >= TARGET_BG_L_MIN
    assert abs(recs[1]["bg_l_after"] - target) < 0.6
    dark, md = _scene((190, 190, 190), (12, 12, 12))        # dim main shot
    _, _, target = N.match_set([dark], [md])
    assert target == TARGET_BG_L_MIN


@needs_ffmpeg
def test_render_never_changes_the_saved_set_photos(tmp_path):
    from backend.video.plan import build_plan, ProductInfo
    from backend.video.promo import render_plan
    paths = []
    for i, angle in enumerate((0, 25, -25)):
        img, _ = _scene((214, 214, 214), (40, 60, 200), box=(380 + 10 * i, 420, 700, 930),
                        size=(1350, 1080))
        p = tmp_path / f"img_{i:02d}.img"
        p.write_bytes(cv2.imencode(".jpg", img)[1].tobytes())
        paths.append(p)
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    plan = build_plan([("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2)],
                      ProductInfo(name="Test"), "vertical", None, None)
    r = render_plan(plan, paths, tmp_path / "out.mp4", ffmpeg_bin=ffmpeg_binary())
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    assert before == after
    norm = r.record["normalisation"]
    assert set(norm["images"]) == {"0", "1", "2"}
    assert all("product_de00" in v and "gain" in v for v in norm["images"].values())
