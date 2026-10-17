"""Bounded Gemini retry + reason classification (B2/B3, 2026-10-13).

Pure-logic tests (no network): transient 429/503 are retried with backoff; a
timeout is NOT retried (we never auto-resubmit a slow call); reason codes are
classified for honest error messages.
"""
import pytest

from backend.pqf.semantic import gemini_common as gc


def test_reason_codes():
    assert gc.reason("some 503 UNAVAILABLE thing") == "UNAVAILABLE"
    assert gc.reason("RESOURCE_EXHAUSTED: quota") == "RESOURCE_EXHAUSTED"
    assert gc.reason("API_KEY_INVALID") == "API_KEY_INVALID"
    assert gc.reason("NOT_FOUND model") == "NOT_FOUND"
    assert gc.reason("429 Too Many Requests") == "RESOURCE_EXHAUSTED"
    assert gc.reason("nothing special") == "other"


def test_transient_is_only_429_503():
    assert gc.is_transient(Exception("503 UNAVAILABLE"))
    assert gc.is_transient(Exception("RESOURCE_EXHAUSTED"))
    assert gc.is_transient(Exception("HTTP 429"))
    assert not gc.is_transient(Exception("DEADLINE_EXCEEDED (timeout)"))
    assert not gc.is_transient(Exception("API_KEY_INVALID"))


def test_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(gc, "BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(gc, "MAX_BACKOFF_S", 0.0)
    monkeypatch.setattr(gc, "MAX_RETRIES", 2)
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        if calls["n"] < 2:
            raise Exception("503 UNAVAILABLE")
        return "ok"

    assert gc.call_with_retry(do) == "ok"
    assert calls["n"] == 2


def test_does_not_retry_a_timeout(monkeypatch):
    monkeypatch.setattr(gc, "BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(gc, "MAX_RETRIES", 2)
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise Exception("DEADLINE_EXCEEDED")

    with pytest.raises(Exception):
        gc.call_with_retry(do)
    assert calls["n"] == 1  # never resubmitted


def test_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(gc, "BASE_BACKOFF_S", 0.0)
    monkeypatch.setattr(gc, "MAX_BACKOFF_S", 0.0)
    monkeypatch.setattr(gc, "MAX_RETRIES", 2)
    calls = {"n": 0}

    def do():
        calls["n"] += 1
        raise Exception("503 UNAVAILABLE")

    with pytest.raises(Exception):
        gc.call_with_retry(do)
    assert calls["n"] == 3  # first try + 2 retries, then gives up
