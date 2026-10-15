"""v1.4.0 (2026-10-15): the server accepts every study event the app now sends.

mobile/test/fixtures/study_payloads.jsonl holds the bodies the phone's own log code
builds (captured from StudyLog by mobile/test/study_payloads_test.dart). Before this
change the validator refused session_start (extra fields) and photo_captured,
help_card_shown, setup_check_shown and restart (unknown events): the study log on the
server would have been missing them. Unknown fields and secret-like values are still
refused."""
import json
from pathlib import Path

import pytest

import os
os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.study_api import validate

client = TestClient(app)
FIXTURE = Path(__file__).resolve().parents[2] / "mobile" / "test" / "fixtures" / "study_payloads.jsonl"
PAYLOADS = [json.loads(l) for l in FIXTURE.read_text(encoding="utf-8").splitlines() if l.strip()]
HASH = "ab" * 32


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "study_log.jsonl"
    monkeypatch.setenv("PQF_STUDY_LOG", str(p))
    return p


def _by_event(name, n=0):
    return [dict(p) for p in PAYLOADS if p["event"] == name][n]


def test_the_fixture_covers_every_event_the_app_logs():
    assert {p["event"] for p in PAYLOADS} == {
        "session_start", "photo_captured", "help_card_shown", "setup_check_shown",
        "restart", "capture_end", "own_picks", "batch_result", "video_ready"}


@pytest.mark.parametrize("i", range(len(PAYLOADS)))
def test_each_exact_app_payload_is_accepted(log, i):
    r = client.post("/study/log", content=json.dumps(PAYLOADS[i]))
    assert r.status_code == 200, (PAYLOADS[i]["event"], r.text)


def test_the_new_fields_are_stored(log):
    for p in PAYLOADS:
        assert client.post("/study/log", content=json.dumps(p)).status_code == 200
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == len(PAYLOADS)
    start = next(r for r in rows if r["event"] == "session_start")
    for k in ("group", "device_model", "app_version", "app_build", "apk_version",
              "condition_order", "same_product_as_first"):
        assert k in start
    photos = [r for r in rows if r["event"] == "photo_captured"]
    assert len(photos) == 2
    assert photos[1]["retake_of"] == photos[0]["hash"]
    assert photos[0]["width"] == 3096 and photos[0]["exif_orientation"] == 1
    assert photos[1]["width"] is None
    assert next(r for r in rows if r["event"] == "restart")["role"] is None


# ---- unknown fields and secrets are still refused -----------------------------------
def test_an_unknown_field_is_still_rejected(log):
    bad = _by_event("session_start")
    bad["email"] = "someone@example.com"
    r = client.post("/study/log", content=json.dumps(bad))
    assert r.status_code == 400 and "not allowed" in r.text
    assert not log.exists()


@pytest.mark.parametrize("event,field,value", [
    ("batch_result", "hash", HASH),                     # a photo field on the wrong event
    ("session_start", "shot_requested", "main"),
    ("capture_end", "group", "seller"),
    ("photo_captured", "device_model", "SM-J610F"),
])
def test_a_new_field_on_the_wrong_event_is_rejected(log, event, field, value):
    bad = _by_event(event)
    bad[field] = value
    assert client.post("/study/log", content=json.dumps(bad)).status_code == 400


@pytest.mark.parametrize("field,value", [
    ("device_model", "AIzaSyD-FAKE-KEY-0123456789abcdef"),
    ("device_model", "sk-live-0123456789abcdef0123"),
    ("device_model", "Bearer abc"),
    ("device_model", "api_key=1234"),
    ("app_version", "1.0.0; password=hunter2"),
])
def test_anything_that_looks_like_a_secret_is_rejected(log, field, value):
    bad = _by_event("session_start")
    bad[field] = value
    r = client.post("/study/log", content=json.dumps(bad))
    assert r.status_code == 400
    assert not log.exists()


@pytest.mark.parametrize("field,value", [
    ("group", "teacher"), ("condition_order", ["GUIDED", "GUIDED"]),
    ("same_product_as_first", "yes"), ("app_version", "one"),
])
def test_session_start_field_values_are_checked(log, field, value):
    bad = _by_event("session_start")
    bad[field] = value
    assert client.post("/study/log", content=json.dumps(bad)).status_code == 400


@pytest.mark.parametrize("field,value", [
    ("hash", "not-a-hash"), ("shot_requested", "selfie"), ("source", "camera_roll"),
    ("width", -5), ("width", "3096"), ("exif_orientation", 99), ("retake_of", "xyz"),
])
def test_photo_captured_field_values_are_checked(log, field, value):
    bad = _by_event("photo_captured")
    bad[field] = value
    assert client.post("/study/log", content=json.dumps(bad)).status_code == 400


def test_image_data_is_still_refused_in_a_photo_entry(log):
    bad = _by_event("photo_captured")
    bad["image"] = "/9j/4AAQSkZJRgABAQ..."
    assert client.post("/study/log", content=json.dumps(bad)).status_code == 400


def test_validate_returns_only_known_fields():
    out = validate(_by_event("photo_captured"))
    assert set(out) <= {"event", "timestamp", "participant", "condition", "product",
                        "session", "times", "hash", "shot_requested", "retake_of",
                        "source", "width", "height", "exif_orientation"}
