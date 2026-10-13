"""Deterministic semantic-score cache (item 2, 2026-10-14).

An identical image returns the identical SQS and makes NO new Gemini call;
failures are never cached; the key depends on bytes + prompt + model; the cache
can be turned off. Gemini is faked so the tests are deterministic and offline.
"""
from backend.pqf.semantic import evaluator as ev
from backend.pqf.semantic import score_cache as sc
from backend.pqf.semantic.evaluator import SemanticResult


def _reset(tmp_path, monkeypatch):
    monkeypatch.setenv("PQF_SCORE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("PQF_SCORE_CACHE", "on")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-used")
    monkeypatch.delenv("PQF_SEMANTIC_MOCK", raising=False)
    sc._MEM.clear()
    sc._HITS = 0
    sc._MISSES = 0


def test_identical_image_is_cached_and_makes_no_new_call(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake(_bytes, mime="image/jpeg"):
        calls["n"] += 1
        return SemanticResult(scores={"marketing_suitability": 0.5}, sqs=0.5,
                              role="hero_shot", ok=True,
                              model_version="gemini-3.5-flash-lite")

    monkeypatch.setattr(ev, "_gemini_evaluate", fake)
    r1 = ev.evaluate_semantic(b"IMAGE-BYTES", "image/jpeg")
    r2 = ev.evaluate_semantic(b"IMAGE-BYTES", "image/jpeg")
    assert calls["n"] == 1, "second identical image must be served from cache"
    assert r1.sqs == r2.sqs == 0.5
    assert r1.role == r2.role == "hero_shot"
    assert sc.stats()["hits"] >= 1


def test_failed_calls_are_never_cached(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    calls = {"n": 0}

    def fake(_bytes, mime="image/jpeg"):
        calls["n"] += 1
        return SemanticResult(ok=False, error="gemini call failed [UNAVAILABLE]")

    monkeypatch.setattr(ev, "_gemini_evaluate", fake)
    ev.evaluate_semantic(b"X")
    ev.evaluate_semantic(b"X")
    assert calls["n"] == 2, "a failed call must not be cached"


def test_key_depends_on_bytes_prompt_and_model():
    a = sc.key_for(b"A", "v1", "m1")
    assert a == sc.key_for(b"A", "v1", "m1")
    assert a != sc.key_for(b"B", "v1", "m1")
    assert a != sc.key_for(b"A", "v2", "m1")
    assert a != sc.key_for(b"A", "v1", "m2")


def test_cache_can_be_disabled(tmp_path, monkeypatch):
    _reset(tmp_path, monkeypatch)
    monkeypatch.setenv("PQF_SCORE_CACHE", "off")
    calls = {"n": 0}

    def fake(_bytes, mime="image/jpeg"):
        calls["n"] += 1
        return SemanticResult(sqs=0.4, role="detail_shot", ok=True,
                              model_version="m")

    monkeypatch.setattr(ev, "_gemini_evaluate", fake)
    ev.evaluate_semantic(b"Z")
    ev.evaluate_semantic(b"Z")
    assert calls["n"] == 2, "no caching when PQF_SCORE_CACHE=off"
