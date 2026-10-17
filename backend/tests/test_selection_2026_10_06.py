"""Best 4 to 5 with DISTINCT angles (2026-10-06).

Synthetic product: an asymmetric object on a light grey lightbox background.
Same view = same pose, different size and position. Different view = turned or
seen from another side (different outline and appearance).
"""
import os

import cv2
import numpy as np

os.environ.setdefault("PQF_SEMANTIC_MOCK", "1")   # main.py refuses to start without a key

from backend.pqf.combination import ImageDecision, check_gate
from backend.pqf.pipeline.pipeline import _select_best_set, SELECT_MAX
from backend.pqf.pipeline.views import (view_signature, view_distance, product_box,
                                        NEAR_DUPLICATE)


def _product(angle=0.0, scale=1.0, dx=0, dy=0, side=False, bg=205):
    """1024x819 photo of a small asymmetric product. `side` shows a narrow side view."""
    h, w = 1024, 819
    obj = np.full((400, 400, 3), 255, np.uint8)
    if side:
        cv2.rectangle(obj, (170, 60), (230, 340), (40, 60, 200), -1)
        cv2.rectangle(obj, (175, 90), (225, 120), (30, 200, 230), -1)
    else:
        cv2.rectangle(obj, (90, 120), (310, 330), (40, 60, 200), -1)
        cv2.circle(obj, (200, 90), 55, (30, 160, 60), -1)
        cv2.putText(obj, "TEA", (120, 260), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (250, 250, 250), 6)
    M = cv2.getRotationMatrix2D((200, 200), angle, scale)
    obj = cv2.warpAffine(obj, M, (400, 400), borderValue=(255, 255, 255))
    img = np.full((h, w, 3), bg, np.uint8)
    y0, x0 = 312 + dy, 210 + dx
    region = img[y0:y0 + 400, x0:x0 + 400]
    keep = obj.min(axis=2) < 250
    region[keep] = obj[keep]
    return img


def _dec(img, role, fqs):
    d = ImageDecision(tqs=0.8, sqs=0.8, fqs=fqs, role=role, passed=True,
                      semantic_scores={"subject_centering": 0.8, "marketing_suitability": 0.8,
                                       "angle_value": 0.7, "feature_visibility": 0.8})
    d.view_sig = view_signature(img) if img is not None else None
    return d


def test_product_box_ignores_lightbox_corner_shadow():
    img = _product()
    cv2.rectangle(img, (0, 900), (120, 1023), (150, 150, 150), -1)   # dark corner
    x0, y0, x1, y1 = product_box(img)
    assert x0 > 150 and y1 < 800


def test_same_view_closer_or_moved_is_a_near_duplicate():
    a = view_signature(_product())
    b = view_signature(_product(scale=0.8, dx=40, dy=-30))
    assert view_distance(a, b) < NEAR_DUPLICATE


def test_turned_or_side_view_is_distinct():
    a = view_signature(_product())
    assert view_distance(a, view_signature(_product(angle=35))) >= NEAR_DUPLICATE
    assert view_distance(a, view_signature(_product(side=True))) >= NEAR_DUPLICATE


def test_angle_pair_is_the_most_different_not_the_two_highest_scores():
    hero = _dec(_product(), "hero_shot", 0.90)
    dup1 = _dec(_product(scale=0.9), "angle_shot", 0.86)        # same view as hero
    dup2 = _dec(_product(scale=0.8, dx=30), "angle_shot", 0.85)  # same view again
    turned = _dec(_product(angle=35), "angle_shot", 0.74)
    side = _dec(_product(side=True), "angle_shot", 0.72)
    detail = _dec(_product(angle=-20, scale=1.3), "detail_shot", 0.80)
    sel = _select_best_set([hero, dup1, dup2, turned, side, detail])
    assert turned in sel and side in sel
    assert dup1 not in sel and dup2 not in sel
    assert dup1.selection_note == "same_view" and dup1.duplicate_of is hero
    assert len(sel) <= SELECT_MAX
    assert check_gate(sel).certified


def test_set_is_four_or_five_never_six():
    imgs = [_dec(_product(angle=a), "angle_shot", 0.8 - i * 0.01)
            for i, a in enumerate((25, -25, 50, -50, 75))]
    sel = _select_best_set([_dec(_product(), "hero_shot", 0.9), *imgs,
                            _dec(_product(side=True), "detail_shot", 0.8)])
    assert 4 <= len(sel) <= 5


def test_gate_rejects_two_copies_of_the_same_angle():
    hero = _dec(_product(), "hero_shot", 0.9)
    a1 = _dec(_product(angle=35), "angle_shot", 0.8)
    a2 = _dec(_product(angle=35, scale=0.85, dx=20), "angle_shot", 0.79)
    detail = _dec(_product(side=True), "detail_shot", 0.8)
    g = check_gate([hero, a1, a2, detail])
    assert not g.certified and "insufficient_angles" in g.fail_reasons
    assert g.counts["angle"] == 2 and g.counts["distinct_angles"] == 1


def test_without_view_signatures_behaviour_is_unchanged():
    ds = [_dec(None, r, f) for r, f in (("hero_shot", .9), ("angle_shot", .8),
                                        ("angle_shot", .7), ("detail_shot", .75))]
    sel = _select_best_set(ds)
    assert len(sel) == 4 and check_gate(sel).certified


# ---------------------------------------------------------------- explanations for the app
from backend.pqf.pipeline.pipeline import process_batch
from backend.api.batch_explain import explain_batch
from backend.api.main import FEEDBACK
from backend.pqf import config


def test_every_photo_gets_a_status_and_message():
    hero = _dec(_product(), "hero_shot", 0.90)
    dup = _dec(_product(scale=0.9), "angle_shot", 0.86)
    turned = _dec(_product(angle=35), "angle_shot", 0.74)
    side = _dec(_product(side=True), "angle_shot", 0.72)
    detail = _dec(_product(angle=-20, scale=1.3), "detail_shot", 0.80)
    bad = ImageDecision(tqs=0.2, role="reject", passed=False, hard_rejected=True)
    bad.technical_scores = {"sharpness": 0.05, "exposure": 0.6}
    res = process_batch([hero, dup, turned, side, detail, bad])
    out = explain_batch(res, FEEDBACK, config.SQS_PASS_THRESHOLDS)
    st = {e["index"]: e for e in out["images"]}
    assert res.certified and out["missing"] == []
    assert st[1]["status"] == "same_view" and "photo 1" in st[1]["message"]
    assert st[5]["status"] == "not_good_enough" and FEEDBACK["sharpness"] in st[5]["message"]
    assert sum(e["selected"] for e in out["images"]) == len(res.selected)


def test_missing_lists_only_the_shots_to_retake():
    hero = _dec(_product(), "hero_shot", 0.90)
    a1 = _dec(_product(angle=35), "angle_shot", 0.8)
    a2 = _dec(_product(angle=35, scale=0.85, dx=20), "angle_shot", 0.79)  # same view
    res = process_batch([hero, a1, a2])
    out = explain_batch(res, FEEDBACK, config.SQS_PASS_THRESHOLDS)
    roles = {m["role"]: m for m in out["missing"]}
    assert set(roles) == {"angle_shot", "detail_shot"}
    assert roles["angle_shot"]["count"] == 1



def test_set_is_exactly_main_two_angles_and_detail_when_more_pass():
    """v1.1.0: the set is the four roles only, even with more distinct good views."""
    hero = _dec(_product(), "hero_shot", 0.90)
    hero2 = _dec(_product(angle=60), "hero_shot", 0.88)        # a different good view
    angles = [_dec(_product(angle=a), "angle_shot", 0.8) for a in (30, -30, 75)]
    detail = _dec(_product(side=True), "detail_shot", 0.8)
    sel = _select_best_set([hero, hero2, *angles, detail])
    assert SELECT_MAX == 4 and len(sel) == 4
    assert sorted(d.role for d in sel) == ["angle_shot", "angle_shot", "detail_shot",
                                           "hero_shot"]
    assert hero2.selection_note == "not_needed"
    assert check_gate(sel).certified
