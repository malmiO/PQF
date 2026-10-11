"""v1.4.0 Part D: per-criterion pass thresholds in config, and T4 excluded (weight 0).

Decided 2026-10-11 after the pre-registered T4/T5 calibration (pooled n = 125): T4's
P10 is 0.0 and synthetic noise raises T4 at every level, so T4 carries no weight and
gives no feedback; T5's pass threshold is 0.33. Nothing else about TQS, SQS, FQS, the
hard reject, roles, the gate or the selection changes.
"""
import os
from pathlib import Path

import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api import batch_explain as BE
from backend.api import main as M
from backend.pqf import config
from backend.pqf.combination import ImageDecision

client = TestClient(M.app)
ROOT = Path(__file__).resolve().parents[2]
PASS_1 = ROOT / "research" / "test_set" / "PASS_1_expect_accepted__511VodekMvL.jpg"

# Per-criterion scores of PASS_1 measured BEFORE the edit (4 dp), pinned environment.
PASS_1_SCORES = {"sharpness": 0.5179, "exposure": 0.7052, "background": 0.9941,
                 "brisque": 0.1854, "piqe": 0.2693, "colorcast": 0.9958}
OLD_WEIGHTS = {"sharpness": 0.22, "exposure": 0.18, "background": 0.18,
               "brisque": 0.18, "piqe": 0.14, "colorcast": 0.10}
PASS_1_TQS_BEFORE = 0.5904


# ---- configuration --------------------------------------------------------------
def test_every_weighted_criterion_has_a_pass_threshold():
    assert set(config.TQS_PASS_THRESHOLDS) == set(config.TQS_WEIGHTS)


def test_weights_are_the_confirmed_ones_and_sum_to_one():
    assert config.TQS_WEIGHTS == {"sharpness": 0.27, "exposure": 0.22, "background": 0.22,
                                  "brisque": 0.00, "piqe": 0.17, "colorcast": 0.12}
    assert abs(sum(config.TQS_WEIGHTS.values()) - 1.0) < 1e-9


def test_t4_t5_thresholds_and_unchanged_values():
    assert config.T4_PASS_THRESHOLD == 0.0
    assert config.T5_PASS_THRESHOLD == 0.33
    assert config.TQS_PASS_THRESHOLDS["brisque"] == config.T4_PASS_THRESHOLD
    assert config.TQS_PASS_THRESHOLDS["piqe"] == config.T5_PASS_THRESHOLD
    # the specification's own values for the other four, unchanged
    assert config.TQS_PASS_THRESHOLDS["sharpness"] == 0.20
    assert config.TQS_PASS_THRESHOLDS["exposure"] == 0.60
    assert config.TQS_PASS_THRESHOLDS["background"] == 0.55
    assert config.TQS_PASS_THRESHOLDS["colorcast"] == 0.60
    # not part of this change
    assert config.TQS_HARD_REJECT == 0.40
    assert config.FQS_ALPHA == 0.4 and config.FQS_BETA == 0.6
    assert config.FQS_PASS_THRESHOLD == 0.55


def test_the_new_weights_keep_the_old_rank_order_without_t4():
    old = sorted((k for k in OLD_WEIGHTS if k != "brisque"), key=OLD_WEIGHTS.get, reverse=True)
    new = sorted((k for k in config.TQS_WEIGHTS if k != "brisque"),
                 key=config.TQS_WEIGHTS.get, reverse=True)
    assert old == new


# ---- feedback: below the threshold gives that criterion's message, above gives none --
def _decision(**scores):
    base = {k: 1.0 for k in config.TQS_WEIGHTS}     # everything fine
    base.update(scores)
    d = ImageDecision()
    d.technical_scores = base
    return d


@pytest.mark.parametrize("name", [k for k in config.TQS_WEIGHTS if k != "brisque"])
def test_just_below_a_threshold_gives_that_feedback(name):
    thr = config.TQS_PASS_THRESHOLDS[name]
    technical, _, feedback = M._shape(_decision(**{name: thr - 0.01}))
    assert M.FEEDBACK[name] in feedback
    assert next(c for c in technical if c.name == name).passed is False


@pytest.mark.parametrize("name", [k for k in config.TQS_WEIGHTS if k != "brisque"])
def test_at_or_just_above_a_threshold_gives_none(name):
    thr = config.TQS_PASS_THRESHOLDS[name]
    for score in (thr, thr + 0.01):
        technical, _, feedback = M._shape(_decision(**{name: score}))
        assert M.FEEDBACK[name] not in feedback
        assert next(c for c in technical if c.name == name).passed is True


def test_t4_is_returned_but_never_gives_feedback():
    technical, _, feedback = M._shape(_decision(brisque=0.0))
    t4 = next(c for c in technical if c.name == "brisque")
    assert t4.score == 0.0 and t4.weight == 0.0 and t4.passed is True
    assert M.FEEDBACK["brisque"] not in feedback


def test_the_old_blanket_cut_no_longer_applies():
    # 0.45 is above the old 0.40 cut but below T2's own threshold 0.60: now flagged
    _, _, feedback = M._shape(_decision(exposure=0.45))
    assert M.FEEDBACK["exposure"] in feedback
    # T5 at 0.35 is above its calibrated 0.33: no feedback (the old spec 0.55 would have fired)
    _, _, feedback = M._shape(_decision(piqe=0.35))
    assert M.FEEDBACK["piqe"] not in feedback


# ---- /criteria ------------------------------------------------------------------
def test_criteria_lists_technical_pass_thresholds():
    body = client.get("/criteria").json()
    got = {t["name"]: t for t in body["technical"]}
    assert set(got) == set(config.TQS_WEIGHTS)
    for k, t in got.items():
        assert t["pass_threshold"] == config.TQS_PASS_THRESHOLDS[k]
        assert t["weight"] == config.TQS_WEIGHTS[k]
    assert got["brisque"]["weight"] == 0.0 and got["brisque"]["pass_threshold"] == 0.0


# ---- a fixed image: scores unchanged, only the aggregation moves ----------------------
@pytest.mark.skipif(not PASS_1.exists(), reason="verification image not present")
def test_fixed_image_scores_unchanged_and_tqs_is_the_new_weighted_sum():
    from backend.pqf.pipeline import score_image
    d = score_image(PASS_1.read_bytes(), path=str(PASS_1))
    got = {k: round(v, 4) for k, v in d.technical_scores.items()}
    assert got == PASS_1_SCORES, "the six criterion scores must be unchanged by the edit"
    # before the edit: the old weighted sum reproduced the stored TQS
    # (the six scores are rounded to 4 dp here, so allow that much)
    old_sum = sum(OLD_WEIGHTS[k] * PASS_1_SCORES[k] for k in OLD_WEIGHTS)
    assert old_sum == pytest.approx(PASS_1_TQS_BEFORE, abs=2e-4)
    expected = sum(config.TQS_WEIGHTS[k] * d.technical_scores[k] for k in config.TQS_WEIGHTS)
    assert d.tqs == pytest.approx(expected, abs=1e-9)
    # FQS is still alpha * TQS + beta * SQS
    assert d.fqs == pytest.approx(config.FQS_ALPHA * d.tqs + config.FQS_BETA * d.sqs, abs=1e-9)


# ---- explaining a hard reject -----------------------------------------------------
def test_weakest_is_the_largest_shortfall_below_its_threshold():
    # exposure is 0.50 below its 0.60 (shortfall 0.10); sharpness 0.05 below 0.20 (0.15)
    tech = {"sharpness": 0.05, "exposure": 0.50, "background": 0.90,
            "brisque": 0.0, "piqe": 0.90, "colorcast": 0.90}
    assert BE.weakest_technical(tech) == "sharpness"
    # lowest raw score is brisque (0.0) but it carries no weight and is never named
    assert BE.weakest_technical(tech) != "brisque"


def test_weakest_falls_back_to_the_lowest_score_when_none_is_below_threshold():
    tech = {"sharpness": 0.90, "exposure": 0.70, "background": 0.60,
            "brisque": 0.0, "piqe": 0.50, "colorcast": 0.95}
    assert BE.weakest_technical(tech) == "piqe"


def test_hard_reject_explanation_uses_the_shortfall_rule():
    d = ImageDecision(hard_rejected=True)
    d.technical_scores = {"sharpness": 0.05, "exposure": 0.55, "background": 0.9,
                          "brisque": 0.0, "piqe": 0.9, "colorcast": 0.9}
    msg = BE._weakest(d, M.FEEDBACK, config.SQS_PASS_THRESHOLDS)
    assert msg == "Not used: " + M.FEEDBACK["sharpness"]


def test_the_evaluation_harness_uses_the_servers_thresholds():
    import sys
    sys.path.insert(0, str(ROOT / "research" / "evaluation"))
    import importlib
    ec = importlib.import_module("evalcommon")
    for k, v in config.TQS_PASS_THRESHOLDS.items():
        assert ec.SPEC_PASS[k] == v
    assert ec.SPEC_PASS_V13["brisque"] == 0.60 and ec.SPEC_PASS_V13["piqe"] == 0.55
    assert "failed construct validity" in ec.LABEL["brisque"]
