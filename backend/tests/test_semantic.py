"""Tests for the semantic evaluator (Phase C), using mock mode (no API)."""
import os
import numpy as np
import cv2

from backend.pqf import config
from backend.pqf.semantic.evaluator import (
    evaluate_semantic, _parse_response, _aggregate_sqs, SemanticResult,
)
from backend.pqf.semantic.prompt import build_prompt, SEMANTIC_CRITERIA, ROLE_OPTIONS


def _img_bytes(color=(120, 120, 120)):
    img = np.full((256, 256, 3), color, np.uint8)
    return cv2.imencode(".jpg", img)[1].tobytes()


# ---- config sanity ----
def test_sqs_weights_sum_to_one():
    assert abs(sum(config.SQS_WEIGHTS.values()) - 1.0) < 1e-9


def test_all_criteria_have_weights():
    for key, _ in SEMANTIC_CRITERIA:
        assert key in config.SQS_WEIGHTS


# ---- prompt ----
def test_prompt_mentions_all_criteria_and_json():
    p = build_prompt()
    for key, _ in SEMANTIC_CRITERIA:
        assert key in p
    assert "JSON" in p


# ---- parsing ----
def test_parse_valid_json():
    txt = '{"scores": {"subject_centering":0.9,"feature_visibility":0.8,"marketing_suitability":0.7,"angle_value":0.6,"lighting_style_quality":0.5}, "role":"hero_shot","justification":"clean"}'
    r = _parse_response(txt)
    assert r.ok
    assert r.role == "hero_shot"
    assert 0.0 <= r.sqs <= 1.0
    assert abs(r.sqs - _aggregate_sqs(r.scores)) < 1e-9


def test_parse_json_with_markdown_fence():
    txt = '```json\n{"scores": {"subject_centering":1,"feature_visibility":1,"marketing_suitability":1,"angle_value":1,"lighting_style_quality":1},"role":"hero_shot","justification":"x"}\n```'
    r = _parse_response(txt)
    assert r.ok
    assert r.sqs == 1.0


def test_parse_garbage_flagged_not_crash():
    r = _parse_response("the model refused to answer")
    assert r.ok is False
    assert r.error


def test_parse_invalid_role_defaults_reject():
    txt = '{"scores":{"subject_centering":0.5,"feature_visibility":0.5,"marketing_suitability":0.5,"angle_value":0.5,"lighting_style_quality":0.5},"role":"banana","justification":"x"}'
    r = _parse_response(txt)
    assert r.role == "reject"


def test_parse_clips_out_of_range_scores():
    txt = '{"scores":{"subject_centering":5,"feature_visibility":-2,"marketing_suitability":0.5,"angle_value":0.5,"lighting_style_quality":0.5},"role":"hero_shot","justification":"x"}'
    r = _parse_response(txt)
    assert r.scores["subject_centering"] == 1.0
    assert r.scores["feature_visibility"] == 0.0


# ---- mock evaluation (deterministic, no API) ----
def test_mock_is_deterministic():
    os.environ["PQF_SEMANTIC_MOCK"] = "1"
    b = _img_bytes((200, 100, 50))
    r1 = evaluate_semantic(b)
    r2 = evaluate_semantic(b)
    assert r1.scores == r2.scores
    assert r1.sqs == r2.sqs
    del os.environ["PQF_SEMANTIC_MOCK"]


def test_mock_returns_valid_structure():
    os.environ["PQF_SEMANTIC_MOCK"] = "1"
    r = evaluate_semantic(_img_bytes())
    assert set(r.scores.keys()) == {k for k, _ in SEMANTIC_CRITERIA}
    assert 0.0 <= r.sqs <= 1.0
    assert r.role in ROLE_OPTIONS
    del os.environ["PQF_SEMANTIC_MOCK"]


def test_no_key_fails_visibly_not_mock():
    os.environ.pop("PQF_SEMANTIC_MOCK", None)
    os.environ.pop("GEMINI_API_KEY", None)
    r = evaluate_semantic(_img_bytes())
    assert not r.ok
    assert "GEMINI_API_KEY" in r.error
