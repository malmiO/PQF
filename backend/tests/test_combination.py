"""Tests for Phase D combination + gate, checked against spec v1.3 values."""
from backend.pqf import config
from backend.pqf.combination import (
    combine_fqs, classify_role, decide_image, check_gate, ImageDecision,
)


# ---------- FQS combination ----------
def test_fqs_formula_matches_spec():
    # FQS = 0.40*TQS + 0.60*SQS
    assert abs(combine_fqs(1.0, 0.0) - 0.40) < 1e-9
    assert abs(combine_fqs(0.0, 1.0) - 0.60) < 1e-9
    assert abs(combine_fqs(0.5, 0.5) - 0.50) < 1e-9


def test_fqs_uses_config_weights():
    tqs, sqs = 0.8, 0.7
    expected = config.FQS_ALPHA * tqs + config.FQS_BETA * sqs
    assert abs(combine_fqs(tqs, sqs) - expected) < 1e-9


# ---------- role classification (spec 4.3) ----------
def _sem(sc=0.8, fv=0.8, ms=0.8, av=0.8, ls=0.8):
    return {"subject_centering": sc, "feature_visibility": fv,
            "marketing_suitability": ms, "angle_value": av,
            "lighting_style_quality": ls}


def test_hero_requires_fqs_075_and_centering_and_marketing():
    # High everything -> hero
    assert classify_role(0.80, _sem(sc=0.9, ms=0.9)) == "hero_shot"
    # FQS just below 0.75 -> not hero
    assert classify_role(0.74, _sem(sc=0.9, ms=0.9)) != "hero_shot"
    # centering too low -> not hero (falls through)
    assert classify_role(0.80, _sem(sc=0.5, ms=0.9)) != "hero_shot"


def test_angle_shot_rule():
    # FQS>=0.60 and angle_value>=0.60, but not hero-qualifying
    r = classify_role(0.62, _sem(sc=0.4, ms=0.4, av=0.7))
    assert r == "angle_shot"


def test_detail_shot_rule():
    # FQS>=0.60, feature_visibility>=0.70, not hero/angle qualifying
    r = classify_role(0.62, _sem(sc=0.4, ms=0.4, av=0.4, fv=0.85))
    assert r == "detail_shot"


def test_reject_when_below_all_rules():
    assert classify_role(0.50, _sem(0.4, 0.4, 0.4, 0.4, 0.4)) == "reject"


def test_priority_hero_beats_angle_and_detail():
    # An image qualifying for multiple roles gets hero (highest priority)
    r = classify_role(0.90, _sem(sc=0.9, ms=0.9, av=0.9, fv=0.9))
    assert r == "hero_shot"


# ---------- decide_image (full per-image decision) ----------
def test_hard_reject_low_tqs_skips_everything():
    d = decide_image(tqs=0.30, sqs=0.90, semantic_scores=_sem())
    assert d.hard_rejected is True
    assert d.role == "reject"
    assert d.passed is False
    assert d.fqs == 0.0  # semantic never combined


def test_passing_image_gets_role_and_pass():
    d = decide_image(tqs=0.85, sqs=0.85, semantic_scores=_sem(sc=0.9, ms=0.9))
    assert d.hard_rejected is False
    assert d.fqs > config.FQS_PASS_THRESHOLD
    assert d.role == "hero_shot"
    assert d.passed is True


def test_below_fqs_pass_not_passed():
    # TQS ok (not hard reject) but combined FQS below 0.55
    d = decide_image(tqs=0.45, sqs=0.45, semantic_scores=_sem(0.4, 0.4, 0.4, 0.4, 0.4))
    assert d.hard_rejected is False
    assert d.passed is False


# ---------- set-level gate (spec 7) ----------
def _mk(role, fqs, fv=0.8):
    return ImageDecision(tqs=0.8, sqs=0.8, fqs=fqs, role=role,
                         passed=True, semantic_scores={"feature_visibility": fv})


def test_gate_certifies_complete_set():
    s = [
        _mk("hero_shot", 0.80),
        _mk("angle_shot", 0.65),
        _mk("angle_shot", 0.66),
        _mk("detail_shot", 0.64, fv=0.85),
    ]
    r = check_gate(s)
    assert r.certified is True
    assert r.fail_reasons == []


def test_gate_flags_missing_hero():
    s = [
        _mk("angle_shot", 0.65),
        _mk("angle_shot", 0.66),
        _mk("detail_shot", 0.64, fv=0.85),
        _mk("angle_shot", 0.67),
    ]
    r = check_gate(s)
    assert r.certified is False
    assert "no_hero_shot" in r.fail_reasons


def test_gate_flags_insufficient_angles():
    s = [
        _mk("hero_shot", 0.80),
        _mk("detail_shot", 0.64, fv=0.85),
        _mk("angle_shot", 0.65),
        _mk("detail_shot", 0.63, fv=0.9),
    ]
    r = check_gate(s)
    assert "insufficient_angles" in r.fail_reasons


def test_gate_flags_set_too_small():
    s = [_mk("hero_shot", 0.80), _mk("angle_shot", 0.65)]
    r = check_gate(s)
    assert "insufficient_coverage" in r.fail_reasons


def test_gate_instruction_present_on_fail():
    s = [_mk("angle_shot", 0.65)]
    r = check_gate(s)
    assert r.certified is False
    assert r.instruction  # non-empty corrective guidance
