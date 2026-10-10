"""
system_tests.py  -  quality of the software artefact itself, reported against
ISO/IEC 25010:2023 product quality characteristics (2026-10-07).

  Functional suitability / correctness   automated test suite: tests run and passed
  Performance efficiency / time behaviour  server-side time for live guidance on a
                                          reduced frame, full scoring per image
                                          (technical part), video render time
  Reliability / maturity                 determinism: the same photo scores the
                                          same twice; view signatures survive JPEG
                                          re-encoding (no false "different view")
Network time is NOT included (it depends on the connection); the device protocol
measures the round trip on the phone separately.

Usage: python research/evaluation/system_tests.py --images <folder> --out <dir> [--pytest]
"""
from __future__ import annotations

import argparse
import os
import re
import statistics as st
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("PQF_SEMANTIC_MOCK", "1")
os.environ["PQF_API_TOKEN"] = ""         # in-process test client: no token check
os.environ["PQF_RATE_LIMIT"] = "off"       # and no rate limit
from evalcommon import REPO, save_json, environment, platform_format  # noqa: E402


def pct(v, q):
    v = sorted(v)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def guidance_latency(paths, runs=3):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    c = TestClient(app)
    out = []
    for p in paths:
        img = cv2.imread(str(p))
        h, w = img.shape[:2]
        small = cv2.resize(img, (224, int(224 * h / w)))   # what the app sends
        data = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        for _ in range(runs):
            t = time.perf_counter()
            r = c.post("/guidance", files={"file": ("f.jpg", data, "image/jpeg")})
            out.append(1000 * (time.perf_counter() - t))
            assert r.status_code == 200, r.text[:200]
    return out


def scoring_time(paths):
    from backend.pqf.preprocess import standardise
    from backend.pqf.technical import compute_tqs
    out, same, worst = [], 0, 0.0
    for p in paths:
        img = standardise(platform_format(cv2.imread(str(p))))
        t = time.perf_counter()
        a = compute_tqs(img, check_gate=False)
        out.append(1000 * (time.perf_counter() - t))
        b = compute_tqs(img, check_gate=False)
        same += int(a.scores == b.scores)
        worst = max(worst, max(abs(a.scores[k] - b.scores[k]) for k in a.scores))
    return out, same, worst


def view_robustness(paths):
    from backend.pqf.preprocess import standardise
    from backend.pqf.pipeline.views import view_signature, view_distance, NEAR_DUPLICATE
    d = []
    for p in paths:
        img = standardise(cv2.imread(str(p)))
        re_enc = cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])[1], 1)
        d.append(view_distance(view_signature(img), view_signature(re_enc)))
    return d, sum(x >= NEAR_DUPLICATE for x in d)


def render_time(paths):
    try:
        from backend.video.builder import ffmpeg_binary
        ff = ffmpeg_binary()
    except Exception:
        import shutil
        ff = shutil.which("ffmpeg")
    if not ff or len(paths) < 4:
        return None
    from backend.video.plan import build_plan, ProductInfo
    from backend.video.promo import render_plan
    import tempfile
    roles = ["hero_shot", "angle_shot", "angle_shot", "detail_shot"]
    plan = build_plan(list(zip(roles, range(4))), ProductInfo(name="Test product", price="Rs. 450",
                      features=["Feature one", "Feature two"]), "vertical",
                      {"points": [(0.5, 0.4), None], "source": "test", "error": ""})
    out = Path(tempfile.mkdtemp()) / "v.mp4"
    t = time.perf_counter()
    r = render_plan(plan, paths[:4], out, ffmpeg_bin=ff)
    return {"seconds": round(time.perf_counter() - t, 1), "video_seconds": r.duration_seconds}


def run_pytest():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
                       cwd=REPO, capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    nums = {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error)", tail)}
    return {"summary": tail, **nums}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--pytest", action="store_true")
    a = ap.parse_args()
    paths = sorted(p for p in a.images.rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    g = guidance_latency(paths[:10])
    s, same, worst = scoring_time(paths)
    v, vfalse = view_robustness(paths)
    res = {
        "n_images": len(paths),
        "guidance_ms": {"n": len(g), "median": round(st.median(g), 1), "p90": round(pct(g, .9), 1)},
        "technical_scoring_ms": {"n": len(s), "median": round(st.median(s), 1), "p90": round(pct(s, .9), 1)},
        "determinism": {"identical_rescores": same, "of": len(s),
                        "max_abs_score_difference": worst},
        "view_signature_jpeg75": {"max_distance": round(max(v), 3), "false_different_views": vfalse,
                                  "of": len(v)},
        "video_render": render_time(paths),
        "tests": run_pytest() if a.pytest else None,
        "environment": environment(),
    }
    save_json(a.out / "summary.json", res)
    print(res)
