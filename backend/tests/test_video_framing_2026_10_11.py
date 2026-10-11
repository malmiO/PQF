"""Promo video fixes of 2026-10-11 (found on a dry run, a pair of earrings). Video only:
no criterion, weight, threshold or decision of the framework is involved.

1. The whole product is framed, not one connected region.
2. A transition never holds two full frames stacked.
3. The detail shot is not enlarged as far, and its push is capped, so it stays sharp."""
import cv2
import numpy as np
import pytest

from backend.video import promo as P

W, H = P.FORMATS["vertical"]


def _pair(w=1080, h=1350, gap=420):
    """A plain background with TWO separate objects (a pair of earrings)."""
    img = np.full((h, w, 3), 226, np.uint8)
    cx = w // 2
    for x in (cx - gap // 2, cx + gap // 2):
        cv2.rectangle(img, (x - 55, 520), (x + 55, 860), (40, 60, 190), -1)
        cv2.circle(img, (x, 480), 42, (30, 150, 70), -1)
    return img


def _frame_box_for(img, kind):
    """Where the whole product lands in the output frame at the END of the shot's motion."""
    centre_y, fill_h = P.LAYOUT["vertical"][kind]
    cap = P.DETAIL_MAX_UPSCALE if kind in ("detail", "feature") else P.MAX_UPSCALE
    plate, to_plate = P._plate(img, W, H, fill_h, centre_y, P.MAX_WIDTH_FILL, max_upscale=cap)
    motion = P.MOTION[kind]
    M = P._matrix(plate.shape[1::-1], W, H, 1.0, motion, 1, centre_y)
    cx, cy, pw, ph = P.product_box_xywh(img)
    pts = [M @ np.float32([*to_plate(x, y), 1])
           for x, y in ((cx - pw / 2, cy - ph / 2), (cx + pw / 2, cy + ph / 2))]
    return pts[0][0], pts[0][1], pts[1][0], pts[1][1]


# ---------------------------------------------------------------- fix 1: whole product
def test_whole_box_covers_every_object_of_a_pair_with_a_margin():
    img = _pair()
    x0, y0, x1, y1 = P.whole_product_box(img)
    cx = img.shape[1] // 2
    left_obj, right_obj = (cx - 210 - 55, cx + 210 + 55)
    assert x0 <= left_obj and x1 >= right_obj            # both objects inside
    assert y0 <= 480 - 42 and y1 >= 860                  # whole height
    assert x0 > 0 and y0 > 0 and x1 < img.shape[1]       # a margin, not the frame edge


def test_product_box_xywh_centres_on_the_pair_not_on_one_object():
    img = _pair()
    cx, cy, pw, ph = P.product_box_xywh(img)
    assert abs(cx - img.shape[1] / 2) < 25               # the middle of the PAIR
    assert pw > 0.5 * img.shape[1] * 0.5                 # wide enough to hold both


@pytest.mark.parametrize("kind", ["hook", "angle", "detail", "end"])
def test_the_whole_pair_is_inside_the_frame_in_every_shot(kind):
    x0, y0, x1, y1 = _frame_box_for(_pair(), kind)
    assert x0 >= 0 and y0 >= 0 and x1 <= W and y1 <= H, (kind, x0, y0, x1, y1)


def test_edge_touching_regions_are_ignored_and_empty_falls_back():
    img = _pair()
    img[:, :60] = (90, 90, 90)                           # a dark strip running off the frame
    x0, y0, x1, y1 = P.whole_product_box(img)
    assert x0 > 100                                      # the strip is not part of the product
    blank = np.full((1350, 1080, 3), 226, np.uint8)
    assert P.whole_product_box(blank) is None            # nothing found -> caller falls back
    cx, cy, pw, ph = P.product_box_xywh(blank)           # and the fallback still gives a box
    assert pw > 0 and ph > 0 and 0 < cx < 1080 and 0 < cy < 1350


# ---------------------------------------------------------------- fix 2: transition
def test_every_mood_uses_a_quick_slide():
    for mood, style in P.MOOD_STYLE.items():
        assert style["transition"] == "slide", mood
        assert style["trans_s"] <= 0.35, mood


def test_a_slide_never_blends_two_frames():
    a = np.full((60, 100, 3), (0, 0, 255), np.uint8)      # red
    b = np.full((60, 100, 3), (255, 0, 0), np.uint8)      # blue
    for p in (0.1, 0.25, 0.5, 0.75, 0.9):
        out = P._transition_frame(a, b, p, "slide")
        pure = ((out == a).all(axis=2)) | ((out == b).all(axis=2))
        assert pure.all(), f"p={p}: a pixel mixes the two photos"


def test_a_dissolve_would_blend_which_is_why_it_was_dropped():
    a = np.full((60, 100, 3), (0, 0, 255), np.uint8)
    b = np.full((60, 100, 3), (255, 0, 0), np.uint8)
    out = P._transition_frame(a, b, 0.5, "fade")
    assert not ((out == a).all(axis=2) | (out == b).all(axis=2)).any()


# ---------------------------------------------------------------- fix 3: detail sharpness
def test_detail_cap_is_lower_and_the_push_is_capped():
    assert P.DETAIL_MAX_UPSCALE < P.MAX_UPSCALE
    assert P.MAX_UPSCALE == 2.4                            # the default is unchanged
    for t in np.linspace(0, 1, 11):
        M = P._matrix((1404, 2496), W, H, float(t), "deep", 1, 0.55)
        assert M[0, 0] / (W / 1404) <= P.DETAIL_PUSH_MAX + 1e-6


def test_a_small_product_in_a_detail_shot_stays_smaller_than_in_a_hook():
    """A low resolution photo with a small product: the detail shot is not enlarged past
    DETAIL_MAX_UPSCALE (times the oversample), where the old cap allowed 2.4."""
    img = _pair(w=540, h=675, gap=120)
    centre_y, fill_h = P.LAYOUT["vertical"]["detail"]
    _, to_old = P._plate(img, W, H, fill_h, centre_y, P.MAX_WIDTH_FILL)
    _, to_new = P._plate(img, W, H, fill_h, centre_y, P.MAX_WIDTH_FILL,
                         max_upscale=P.DETAIL_MAX_UPSCALE)
    scale = lambda to: (to(100, 0)[0] - to(0, 0)[0]) / 100.0     # plate px per source px
    oversample = 1.3
    assert scale(to_old) / oversample <= P.MAX_UPSCALE + 1e-6
    assert scale(to_new) / oversample <= P.DETAIL_MAX_UPSCALE + 1e-6
    assert scale(to_new) < scale(to_old)                  # smaller, hence sharper
