"""
diagnose.py  -  prints exactly what the framework sees and does, so faults are
found by measurement, not by guessing.

Run from the REPO ROOT:
    python diagnose.py                          environment checks only
    python diagnose.py photo1.jpg photo2.jpg    + full scoring of each photo
    python diagnose.py --url https://YOUR-APP.up.railway.app
                                                + checks a deployed server
    python diagnose.py --build-check            exit 1 if BRISQUE or PIQE abstain
                                                (Railway runs it in every build; no key needed)

Scoring a photo makes ONE real Gemini call per photo.
"""
from __future__ import annotations

import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.getcwd())


def line(ok, text):
    print(("  OK    " if ok else "  FAIL  ") + text)


def environment():
    print("\nENVIRONMENT")
    import numpy as np
    import cv2
    line(np.__version__.startswith("1."),
         f"numpy {np.__version__}  (must be below 2, or BRISQUE crashes)")
    img = (np.random.default_rng(0).random((256, 256, 3)) * 255).astype("uint8")
    try:
        from brisque import BRISQUE
        line(True, f"BRISQUE scores  (test value {BRISQUE().score(img):.1f})")
    except Exception as e:
        line(False, f"BRISQUE broken: {e!r}  -> T4 would silently score 1.0")
    try:
        import pypiqe
        v = pypiqe.piqe(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY))
        line(True, f"PIQE scores     (test value {(v[0] if isinstance(v, tuple) else v):.1f})")
    except Exception as e:
        line(False, f"PIQE broken: {e!r}  -> T5 would silently score 1.0")
    line(shutil.which("ffmpeg") is not None, "ffmpeg on PATH (needed for video)")
    key = os.environ.get("GEMINI_API_KEY", "")
    mock = os.environ.get("PQF_SEMANTIC_MOCK") == "1"
    line(bool(key) and not mock,
         f"Gemini key loaded: {'yes, ' + str(len(key)) + ' chars' if key else 'NO'}"
         f"{'   BUT PQF_SEMANTIC_MOCK=1 is set, scores will be FAKE' if mock else ''}")
    from backend.pqf import config
    print(f"        model {config.GEMINI_MODEL}   S_MAX {config.CALIBRATED_SHARPNESS_SMAX}"
          f"   T0 aspect {config.T0_ASPECT_MIN}-{config.T0_ASPECT_MAX}"
          f"   T0 min {config.T0_MIN_RESOLUTION}")


def score(path):
    import numpy as np
    import cv2
    from backend.pqf.technical import t0_compliance
    from backend.pqf.pipeline import score_image
    try:
        from backend.api.main import _platform_format
    except Exception:
        _platform_format = None

    print(f"\nPHOTO  {path}")
    data = open(path, "rb").read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        print("  cannot decode this file")
        return
    h, w = img.shape[:2]
    print(f"  original {w}x{h}  aspect {w/h:.3f}  T0 on original: {t0_compliance(img)}")
    if _platform_format:
        data2 = _platform_format(data)
        if data2 is not data:
            im2 = cv2.imdecode(np.frombuffer(data2, np.uint8), cv2.IMREAD_COLOR)
            print(f"  platform formatted to {im2.shape[1]}x{im2.shape[0]}  "
                  f"T0: {t0_compliance(im2)}")
        data = data2
    d = score_image(data, path=path)
    print(f"  reason {d.reason}   role {d.role}   passed {d.passed}")
    print(f"  TQS {d.tqs:.3f}   SQS {d.sqs:.3f}   FQS {d.fqs:.3f}")
    for k, v in (getattr(d, "technical_scores", {}) or {}).items():
        flag = "   <- exactly 1.0, check it is not abstaining" if k in ("brisque", "piqe") and v == 1.0 else ""
        print(f"    tech  {k:24s} {v:.3f}{flag}")
    for k, v in (d.semantic_scores or {}).items():
        print(f"    sem   {k:24s} {v:.3f}")
    j = getattr(d, "justification", "") or ""
    if "mock" in j.lower():
        print("  !! SEMANTIC SCORES ARE MOCK. They are not real judgements.")


def remote(url):
    import json
    import urllib.request
    print(f"\nSERVER {url}")
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=90) as r:
            h = json.load(r)
        print("  " + json.dumps(h, indent=2).replace("\n", "\n  "))
        line(h.get("semantic_mode") == "LIVE", f"semantic mode: {h.get('semantic_mode')}")
        ab = (h.get("metrics") or {}).get("abstaining", [])
        line(not ab, f"metrics abstaining: {ab or 'none'}")
    except Exception as e:
        line(False, f"cannot reach /health: {e}")


VERIFY_IMAGE = "research/test_set/PASS_1_expect_accepted__511VodekMvL.jpg"
BASELINE_TQS = 0.590         # corrected 2026-10-03 baseline, numpy 1.26.4 + real BRISQUE


def build_check() -> int:
    """Score the verification image's technical criteria exactly as the pipeline
    does (semantic mocked: TQS does not depend on it) and FAIL if any metric
    abstained. Prints the TQS so every build shows it against the baseline."""
    os.environ["PQF_SEMANTIC_MOCK"] = "1"
    import numpy as np
    from backend.pqf.pipeline import score_image
    from backend.pqf.technical import metric_status
    print(f"\nBUILD CHECK  numpy {np.__version__}")
    if os.path.exists(VERIFY_IMAGE):
        data, name = open(VERIFY_IMAGE, "rb").read(), VERIFY_IMAGE
    else:
        # The verification photo is not in this copy: a synthetic product photo
        # still proves BRISQUE and PIQE run; only the TQS comparison is skipped.
        import cv2
        img = np.full((1350, 1080, 3), 225, np.uint8)
        cv2.rectangle(img, (380, 350), (700, 1000), (40, 60, 200), -1)
        cv2.putText(img, "PQF", (430, 700), cv2.FONT_HERSHEY_SIMPLEX, 3, (250, 250, 250), 8)
        data, name = cv2.imencode(".jpg", img)[1].tobytes(), "synthetic"
        print(f"  {VERIFY_IMAGE} not found: checking the metrics on a synthetic photo")
    d = score_image(data, path=name)
    tech = getattr(d, "technical_scores", {}) or {}
    for k in ("brisque", "piqe"):
        print(f"  {k:8s} {tech.get(k, float('nan')):.3f}")
    ab = metric_status().get("abstaining") or []
    if name != "synthetic":
        print(f"  TQS {d.tqs:.3f}   baseline {BASELINE_TQS}   difference {d.tqs - BASELINE_TQS:+.3f}")
    line(not ab, f"metrics abstaining: {ab or 'none'}")
    return 1 if ab else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--build-check" in args:
        sys.exit(build_check())
    if "--url" in args:
        i = args.index("--url")
        remote(args[i + 1])
        args = args[:i] + args[i + 2:]
    environment()
    for p in args:
        score(p)
