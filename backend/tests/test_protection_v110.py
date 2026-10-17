"""Access token and per-IP rate limits (v1.1.0, Part D)."""
import os

import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api import protection as P
from backend.api.main import app

client = TestClient(app)


def _frame():
    img = np.full((1000, 800, 3), 235, np.uint8)
    cv2.rectangle(img, (250, 250), (550, 750), (40, 60, 160), -1)
    return cv2.imencode(".jpg", img)[1].tobytes()


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("PQF_API_TOKEN", "s3cret-token")
    return "s3cret-token"


def test_no_token_configured_means_open():
    os.environ.pop("PQF_API_TOKEN", None)
    assert client.get("/auth/check").status_code == 200


def test_wrong_or_missing_token_is_refused_with_a_clear_message(token):
    for headers in ({}, {"X-PQF-Token": "wrong"}):
        r = client.get("/auth/check", headers=headers)
        assert r.status_code == 401
        assert r.json()["code"] == "bad_token"
        assert "access token" in r.json()["detail"]
    assert client.get("/auth/check", headers={"X-PQF-Token": token}).status_code == 200


def test_health_stays_open_for_the_host_health_check(token):
    assert client.get("/health").status_code == 200


def test_music_preview_accepts_the_token_as_a_query_parameter(token):
    tracks = client.get("/music", headers={"X-PQF-Token": token}).json()["tracks"]
    if not tracks:
        pytest.skip("no music installed")
    tid = tracks[0]["id"]
    assert client.get(f"/music/preview/{tid}").status_code == 401
    assert client.get(f"/music/preview/{tid}?token={token}").status_code == 200


def test_rate_limit_returns_429_with_retry_after(monkeypatch):
    monkeypatch.setenv("PQF_RATE_LIMIT", "on")
    monkeypatch.setitem(P.LIMITS, "/guidance", 3)
    P.reset()
    try:
        codes = [client.post("/guidance", files={"file": ("f.jpg", _frame(), "image/jpeg")},
                             headers={"X-Forwarded-For": "203.0.113.7"}).status_code
                 for _ in range(4)]
        assert codes == [200, 200, 200, 429]
        r = client.post("/guidance", files={"file": ("f.jpg", _frame(), "image/jpeg")},
                        headers={"X-Forwarded-For": "203.0.113.7"})
        assert r.json()["code"] == "rate_limited" and int(r.headers["retry-after"]) > 0
        # another address is counted separately
        other = client.post("/guidance", files={"file": ("f.jpg", _frame(), "image/jpeg")},
                            headers={"X-Forwarded-For": "198.51.100.9"})
        assert other.status_code == 200
    finally:
        P.reset()


def test_expensive_endpoints_have_hourly_limits():
    assert P.LIMITS["/batch"] == 20 and P.LIMITS["/video/plan"] == 20
    assert P.LIMITS["/guidance"] >= 3600


# --- v1.4.0-rc: study sessions are never stopped by the per-IP limits -------------
def _guidance_codes(headers, n=4):
    return [client.post("/guidance", files={"file": ("f.jpg", _frame(), "image/jpeg")},
                        headers=headers).status_code for _ in range(n)]


def test_study_header_with_valid_token_skips_the_per_ip_limit(monkeypatch, token):
    monkeypatch.setenv("PQF_RATE_LIMIT", "on")
    monkeypatch.setitem(P.LIMITS, "/guidance", 3)
    P.reset()
    try:
        # limited without the study header (token alone does not exempt)
        plain = {"X-PQF-Token": token, "X-Forwarded-For": "203.0.113.20"}
        assert _guidance_codes(plain) == [200, 200, 200, 429]
        # not limited with the header and a valid token
        study = {"X-PQF-Token": token, "X-PQF-Study": "1", "X-Forwarded-For": "203.0.113.21"}
        assert _guidance_codes(study, n=6) == [200] * 6
    finally:
        P.reset()


def test_study_header_without_a_server_token_does_not_exempt(monkeypatch):
    monkeypatch.delenv("PQF_API_TOKEN", raising=False)
    monkeypatch.setenv("PQF_RATE_LIMIT", "on")
    monkeypatch.setitem(P.LIMITS, "/guidance", 3)
    P.reset()
    try:
        study = {"X-PQF-Study": "1", "X-Forwarded-For": "203.0.113.22"}
        assert _guidance_codes(study) == [200, 200, 200, 429]
    finally:
        P.reset()


def test_study_header_with_a_wrong_token_is_refused_not_exempted(monkeypatch, token):
    monkeypatch.setenv("PQF_RATE_LIMIT", "on")
    P.reset()
    r = client.post("/guidance", files={"file": ("f.jpg", _frame(), "image/jpeg")},
                    headers={"X-PQF-Token": "wrong", "X-PQF-Study": "1"})
    assert r.status_code == 401 and r.json()["code"] == "bad_token"
