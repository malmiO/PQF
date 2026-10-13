"""/batch scores images with bounded concurrency (B3, 2026-10-13). This proves
the concurrent run gives IDENTICAL results to the serial run - same order, same
per-image role/pass/fqs, same selection and gate - so concurrency only changes
wall-clock time, never a score or decision.

Semantic scoring is mocked (PQF_SEMANTIC_MOCK=1) so the comparison is
deterministic and independent of the live Gemini tier.
"""
import os
import pathlib

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)

_FX = pathlib.Path(__file__).parent / "fixtures"


def _images():
    paths = sorted(_FX.glob("*.jpg"))
    assert paths, "expected fixture images"
    # A small multi-photo set (duplicate to exercise the selection/diversity path).
    files = [("files", (p.name, p.read_bytes(), "image/jpeg")) for p in paths]
    files += [("files", ("dup_" + p.name, p.read_bytes(), "image/jpeg")) for p in paths]
    return files


def _normalise(body: dict):
    """Keep only the fields a score/decision determines (drop timings etc.)."""
    def img(e):
        return {k: (round(e[k], 6) if isinstance(e.get(k), float) else e.get(k))
                for k in ("index", "role", "passed", "selected", "status", "fqs")}
    return {
        "certified": body.get("certified"),
        "images": [img(e) for e in body.get("images", [])],
        "selected": [{"index": s.get("index"), "role": s.get("role"),
                      "fqs": round(s.get("fqs", 0.0), 6), "passed": s.get("passed")}
                     for s in body.get("selected", [])],
    }


def _run(concurrency: str):
    os.environ["PQF_BATCH_CONCURRENCY"] = concurrency
    r = client.post("/batch", files=_images())
    assert r.status_code == 200, r.text
    return _normalise(r.json())


def test_concurrent_batch_matches_serial():
    serial = _run("1")
    concurrent = _run("3")
    assert concurrent == serial, (
        "concurrent /batch must produce identical results to serial")


def test_order_is_preserved():
    # indices come back 0..n-1 in upload order regardless of concurrency.
    body = _run("3")
    idx = [e["index"] for e in body["images"]]
    assert idx == sorted(idx) == list(range(len(idx)))
