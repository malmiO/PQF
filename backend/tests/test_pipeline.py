"""End-to-end pipeline tests (Phase D) using pre-scored decisions."""
from backend.pqf.combination import ImageDecision
from backend.pqf.pipeline import process_batch, score_image_from_scores


def _dec(role, fqs, passed=True, fv=0.8, path="x.jpg"):
    d = ImageDecision(tqs=0.8, sqs=0.8, fqs=fqs, role=role, passed=passed,
                      semantic_scores={"feature_visibility": fv})
    setattr(d, "path", path)
    return d


def test_batch_certifies_complete_set():
    batch = [
        _dec("hero_shot", 0.80, path="hero.jpg"),
        _dec("angle_shot", 0.66, path="a1.jpg"),
        _dec("angle_shot", 0.65, path="a2.jpg"),
        _dec("detail_shot", 0.64, fv=0.85, path="d1.jpg"),
    ]
    res = process_batch(batch)
    assert res.certified is True
    assert res.recapture is None
    assert len(res.role_sets["hero_shot"]) == 1
    assert len(res.role_sets["angle_shot"]) == 2
    assert len(res.role_sets["detail_shot"]) == 1


def test_batch_returns_recapture_when_incomplete():
    batch = [
        _dec("angle_shot", 0.66, path="a1.jpg"),
        _dec("angle_shot", 0.65, path="a2.jpg"),
    ]
    res = process_batch(batch)
    assert res.certified is False
    assert res.recapture is not None
    assert res.recapture["gate_status"] == "fail"
    assert res.recapture["instruction"]           # has corrective guidance
    assert "no_hero_shot" in res.recapture["fail_reasons"]


def test_batch_excludes_failing_images_from_selection():
    batch = [
        _dec("hero_shot", 0.80, path="hero.jpg"),
        _dec("reject", 0.30, passed=False, path="bad.jpg"),
        _dec("angle_shot", 0.66, path="a1.jpg"),
        _dec("angle_shot", 0.65, path="a2.jpg"),
        _dec("detail_shot", 0.64, fv=0.85, path="d1.jpg"),
    ]
    res = process_batch(batch)
    # the failing image must not appear in the selected set
    paths = [getattr(d, "path", None) for d in res.selected]
    assert "bad.jpg" not in paths
    assert res.certified is True


def test_batch_caps_set_size_at_max():
    # 8 passing images -> selected set capped at gate max (6)
    batch = [_dec("hero_shot", 0.90 - i * 0.01, path=f"h{i}.jpg") for i in range(8)]
    res = process_batch(batch)
    assert len(res.selected) <= 6


def test_score_from_scores_attaches_path():
    d = score_image_from_scores(
        0.85, 0.85,
        {"subject_centering": 0.9, "feature_visibility": 0.9,
         "marketing_suitability": 0.9, "angle_value": 0.9,
         "lighting_style_quality": 0.9},
        path="p.jpg",
    )
    assert getattr(d, "path") == "p.jpg"
    assert d.role == "hero_shot"
    assert d.passed is True
