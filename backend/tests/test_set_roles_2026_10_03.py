"""Set level role assignment (2026-10-03)."""
from backend.pqf.combination import decide_image
from backend.pqf.pipeline import process_batch

STRONG = dict(subject_centering=0.9, feature_visibility=0.9,
              marketing_suitability=0.9, lighting_style_quality=0.9)


def _d(fqs_target, angle, featvis=0.9):
    s = dict(STRONG, angle_value=angle, feature_visibility=featvis)
    # tqs = sqs = target gives fqs = target
    return decide_image(fqs_target, fqs_target, s)


def test_strong_angled_shots_become_angles_not_extra_heroes():
    # Before the fix all four classified as hero_shot and the gate failed.
    batch = [_d(0.92, 0.3), _d(0.90, 0.8), _d(0.89, 0.8), _d(0.88, 0.3)]
    r = process_batch(batch)
    roles = sorted(d.role for d in r.selected)
    assert roles.count("hero_shot") >= 1
    assert roles.count("angle_shot") == 2
    assert r.certified, r.recapture


def test_exactly_one_hero_is_the_best_image():
    batch = [_d(0.85, 0.3), _d(0.95, 0.3), _d(0.90, 0.8), _d(0.88, 0.8)]
    r = process_batch(batch)
    hero = [d for d in r.selected if d.role == "hero_shot"]
    assert max(hero, key=lambda d: d.fqs).fqs >= 0.95 - 1e-6


def test_detail_shot_is_not_dropped_from_a_large_batch():
    batch = [_d(0.95 - i * 0.01, 0.8) for i in range(7)]          # 7 strong angles/heroes
    det = decide_image(0.70, 0.70, dict(STRONG, angle_value=0.2, subject_centering=0.5,
                                        feature_visibility=0.9))   # weaker, detail only
    r = process_batch(batch + [det])
    assert any(d.role == "detail_shot" for d in r.selected)
    assert len(r.selected) <= 6


def test_role_rules_and_thresholds_are_unchanged():
    from backend.pqf import config
    assert config.ROLE_RULES["hero_shot"]["fqs_min"] == 0.75
    assert config.ROLE_RULES["angle_shot"]["criteria_min"]["angle_value"] == 0.60
    assert config.ROLE_PRIORITY == ["hero_shot", "angle_shot", "detail_shot"]
