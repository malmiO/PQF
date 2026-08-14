"""Unit tests for the technical engine (T0-T6, TQS)."""
import numpy as np
import pytest

from backend.pqf import config
from backend.pqf.preprocess import standardise
from backend.pqf import technical as T


def _solid(w, h, bgr):
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bgr
    return img


def _white_bg_with_center(w, h, center_bgr, border_bgr=(255, 255, 255)):
    img = _solid(w, h, border_bgr)
    ch, cw = h // 2, w // 2
    y0, x0 = h // 4, w // 4
    img[y0:y0 + ch, x0:x0 + cw] = center_bgr
    return img


# ---- T0 gate ----
def test_t0_passes_normal_image():
    assert T.t0_compliance(_solid(800, 800, (200, 200, 200))) is True


def test_t0_fails_too_small():
    assert T.t0_compliance(_solid(320, 320, (200, 200, 200))) is False


def test_t0_fails_extreme_aspect():
    assert T.t0_compliance(_solid(2000, 500, (200, 200, 200))) is False


# ---- T2 exposure ----
def test_t2_ideal_midtone_scores_high():
    img = _solid(800, 800, (130, 130, 130))  # mean ~130, inside band
    assert T.t2_exposure(img) == 1.0


def test_t2_too_dark_scores_low():
    img = _solid(800, 800, (10, 10, 10))
    assert T.t2_exposure(img) < 0.3


# ---- T3 background ----
def test_t3_white_border_scores_high():
    img = _white_bg_with_center(800, 800, (50, 50, 50))
    assert T.t3_background(img) > 0.95


def test_t3_dark_border_scores_low():
    img = _solid(800, 800, (30, 30, 30))
    assert T.t3_background(img) < 0.05


# ---- T6 colour cast ----
def test_t6_neutral_white_border_no_cast():
    img = _white_bg_with_center(800, 800, (0, 0, 200))  # red product, white bg
    # neutral border → low cast → high score (product colour must NOT trigger)
    assert T.t6_colorcast(img) > 0.8


def test_t6_tinted_border_detects_cast():
    # slightly warm-tinted near-white border (realistic tungsten cast):
    # still near-white (all channels >= threshold) but not neutral
    tinted = _white_bg_with_center(800, 800, (50, 50, 50), border_bgr=(225, 235, 245))
    neutral = _white_bg_with_center(800, 800, (50, 50, 50), border_bgr=(245, 245, 245))
    assert T.t6_colorcast(tinted) < T.t6_colorcast(neutral)


def test_t6_abstains_when_no_neutral_region():
    img = _solid(800, 800, (0, 0, 200))  # fully red, no neutral border
    assert T.t6_colorcast(img) == 1.0


# ---- TQS aggregation ----
def test_tqs_weights_sum_to_one():
    assert abs(sum(config.TQS_WEIGHTS.values()) - 1.0) < 1e-9


def test_compute_tqs_runs_end_to_end():
    img = standardise(_white_bg_with_center(1200, 1200, (120, 120, 120)))
    res = T.compute_tqs(img)
    assert res.passed_gate is True
    assert set(res.scores.keys()) == set(config.TQS_WEIGHTS.keys())
    assert 0.0 <= res.tqs <= 1.0


def test_compute_tqs_rejects_failed_gate():
    res = T.compute_tqs(_solid(320, 320, (120, 120, 120)))
    assert res.passed_gate is False
    assert res.hard_reject is True
