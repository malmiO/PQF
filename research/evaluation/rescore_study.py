"""rescore_study.py - READ-ONLY re-scoring analysis of an exported study zip
(item 4, 2026-10-14). Changes no framework code.

For every photo the study log scored it:
  1. reproduces the server's pipeline EXACTLY - the same _platform_format
     (orientation + 4:5 crop) then score_image - and checks the rescored TQS
     equals the logged TQS within 0.001, listing any mismatch. (TQS is
     deterministic, so this should always match.)
  2. with the score cache OFF, scores each photo N times (default 3) and reports
     per-criterion SD, the SQS range and role agreement - the non-determinism
     that the new cache removes - next to the August test-retest figures.

Usage (pinned venv, from the repo root):
    .venv/Scripts/python.exe research/evaluation/rescore_study.py \
        --dir path/to/unzipped_export --reps 3 [--max-photos N]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

# Re-scoring must be real and uncached, and must never use mock.
os.environ["PQF_SCORE_CACHE"] = "off"
os.environ.pop("PQF_SEMANTIC_MOCK", None)

from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv()

import cv2                                            # noqa: E402
import numpy as np                                     # noqa: E402

from backend.api.main import _platform_format        # noqa: E402  (server 4:5 crop)
from backend.pqf.preprocess import standardise        # noqa: E402
from backend.pqf.technical import compute_tqs, t0_compliance  # noqa: E402
from backend.pqf.semantic import evaluate_semantic    # noqa: E402


def _tqs_only(formatted_bytes: bytes) -> float:
    """TQS exactly as score_image computes it (decode -> t0 -> standardise ->
    compute_tqs), with NO semantic/Gemini call. Deterministic."""
    img = cv2.imdecode(np.frombuffer(formatted_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    if not t0_compliance(img):     # score_image returns a reject with tqs 0.0
        return 0.0
    return float(compute_tqs(standardise(img), check_gate=False).tqs)

# Coventry August 2026 test-retest baseline (from the dissertation appendix),
# shown alongside the new figures. Override with --august-sqs-range if needed.
AUGUST_SQS_RANGE = 0.092   # the observed same-image SQS spread that motivated this


def _logged_scores(log_path: Path) -> dict:
    """hash -> {tqs, sqs, role} from batch_result events (first occurrence)."""
    out = {}
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") != "batch_result":
            continue
        for p in e.get("photos", []):
            h = p.get("hash")
            if h and h not in out:
                out[h] = {"tqs": p.get("tqs"), "sqs": p.get("sqs"),
                          "role": p.get("role")}
    return out


def _photos(root: Path):
    photos_dir = root / "study" / "photos"
    if not photos_dir.is_dir():
        photos_dir = root / "photos" if (root / "photos").is_dir() else root
    for p in sorted(photos_dir.rglob("*.jpg")):
        yield p.parent.name, p.stem, p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="Unzipped export folder.")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--max-photos", type=int, default=0,
                    help="Limit the semantic variance pass (0 = all).")
    ap.add_argument("--august-sqs-range", type=float, default=AUGUST_SQS_RANGE)
    args = ap.parse_args()

    root = Path(args.dir)
    log_path = (root / "study_log.jsonl")
    if not log_path.exists():
        log_path = root / "study" / "study_log.jsonl"
    logged = _logged_scores(log_path)
    photos = list(_photos(root))
    print(f"photos on disk: {len(photos)}   logged (batch_result) photos: {len(logged)}")
    key = bool(os.environ.get("GEMINI_API_KEY"))
    print(f"semantic: LIVE (cache OFF), GEMINI_API_KEY present: {key}\n")

    # 1) TQS reproduction (deterministic, no Gemini) -------------------------
    print("== TQS reproduction (tolerance 0.001) ==")
    tqs_mismatch = []
    checked = 0
    for folder, h, path in photos:
        if h not in logged or logged[h].get("tqs") is None:
            continue
        formatted = _platform_format(path.read_bytes())
        rt = round(_tqs_only(formatted), 4)
        lt = round(float(logged[h]["tqs"]), 4)
        checked += 1
        if abs(rt - lt) > 0.001:
            tqs_mismatch.append((folder, h[:10], lt, rt))
    print(f"  checked {checked} photos; mismatches: {len(tqs_mismatch)}")
    for folder, hh, lt, rt in tqs_mismatch:
        print(f"    MISMATCH {folder}/{hh}  logged={lt}  rescored={rt}")
    if not tqs_mismatch and checked:
        print("  all rescored TQS match the logged TQS within 0.001.")

    # 2) SQS variance with cache OFF -----------------------------------------
    if args.reps <= 0:
        print("\n== SQS variance: skipped (--reps 0) ==")
        return 0
    sample = [(f, h, p) for (f, h, p) in photos]
    if args.max_photos:
        sample = sample[:args.max_photos]
    print(f"\n== SQS variance, {args.reps} reps, cache OFF "
          f"({len(sample)} photos) ==")
    per_crit_sds, sqs_ranges, role_disagreements = [], [], 0
    scored = 0
    for folder, h, path in sample:
        formatted = _platform_format(path.read_bytes())
        reps = []
        for _ in range(args.reps):
            r = evaluate_semantic(formatted, "image/jpeg")
            if r.ok:
                reps.append(r)
        if len(reps) < 2:
            print(f"  {folder}/{h[:10]}: only {len(reps)} ok reps "
                  f"(free-tier 503/slow) - skipped")
            continue
        scored += 1
        sqs_vals = [r.sqs for r in reps]
        rng = max(sqs_vals) - min(sqs_vals)
        sqs_ranges.append(rng)
        roles = {r.role for r in reps}
        if len(roles) > 1:
            role_disagreements += 1
        crits = reps[0].scores.keys()
        for c in crits:
            vals = [r.scores.get(c, 0.0) for r in reps]
            per_crit_sds.append(statistics.pstdev(vals))
        print(f"  {folder}/{h[:10]}: SQS range={rng:.3f} roles={roles}")

    print("\n== Summary ==")
    if sqs_ranges:
        print(f"  photos with >=2 ok reps: {scored}")
        print(f"  SQS range: mean={statistics.mean(sqs_ranges):.3f} "
              f"max={max(sqs_ranges):.3f}")
        print(f"  per-criterion SD: mean={statistics.mean(per_crit_sds):.3f} "
              f"max={max(per_crit_sds):.3f}")
        print(f"  role agreement: {scored - role_disagreements}/{scored} "
              f"photos agreed across reps")
        print(f"  August test-retest SQS range (baseline): "
              f"{args.august_sqs_range:.3f}")
        print("  NOTE: with the new score cache ON, an identical image returns "
              "an identical SQS, so this variance becomes 0 in production.")
    else:
        print("  no photos produced >=2 ok reps (free tier too slow/503). "
              "Re-run on the paid tier for the variance figures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
