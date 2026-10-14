"""v1.4.0-rc: the pinned model, the version that answered, and the release label."""
import os

import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.pqf import RELEASE, config

client = TestClient(app)


def _photo(offset=0):
    img = np.full((1000, 800, 3), 235, np.uint8)
    cv2.rectangle(img, (250 + offset, 250), (550 + offset, 750), (40, 60, 160), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


def test_model_is_pinned_to_a_fixed_name_not_the_alias():
    assert config.GEMINI_MODEL == "gemini-3.5-flash-lite"
    assert "latest" not in config.GEMINI_MODEL
    assert config.GEMINI_TIER == "free"


def test_release_is_the_release_candidate_and_spec_version_is_unchanged():
    assert RELEASE == "1.4.0-rc"
    h = client.get("/health").json()
    assert h["release"] == "1.4.0-rc"
    # The framework version is set separately from the release label (2026-10-15: "1.4").
    assert h["framework_version"] == config.SPEC_VERSION == "1.4"
    assert h["tier"] == "free"


def test_score_reports_the_model_that_answered():
    r = client.post("/score", files={"file": ("a.jpg", _photo(), "image/jpeg")})
    assert r.status_code == 200
    body = r.json()
    assert body["model_version"] == "mock"      # the mock reports "mock"
    assert body["tier"] == "free"
    assert client.get("/health").json()["last_model_version"] == "mock"


def test_batch_reports_the_first_semantic_model_version():
    files = [("files", (f"i{i}.jpg", _photo(i * 20), "image/jpeg")) for i in range(4)]
    r = client.post("/batch", files=files)
    assert r.status_code == 200
    assert r.json()["model_version"] == "mock"
    assert r.json()["tier"] == "free"
