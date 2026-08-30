"""
Phase C — semantic evaluator test-retest reliability.

Methodology requires establishing that the semantic evaluator is RELIABLE
(consistent for the same input) BEFORE it is used for scoring — a validity
claim on an inconsistent instrument is meaningless.

Runs each of N images K times through the evaluator and reports:
  - mean per-criterion standard deviation across repeats (lower = more stable)
  - mean SQS standard deviation
  - role agreement rate (how often the role is identical across repeats)

At temperature 0 the model should be near-deterministic; this quantifies it.
Run this on a ~30-image subset (methodology spec) with the REAL API before
trusting the evaluator. Uses whatever mode evaluate_semantic resolves to
(real Gemini if GEMINI_API_KEY set; mock otherwise — mock is perfectly stable
by construction, so a mock run only tests the plumbing, not the model).

Usage:
    python research/scripts/reliability.py <image_dir> [--repeats 3] [--limit 30]
"""
from __future__ import annotations
import argparse
import statistics
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Load .env so GEMINI_API_KEY is available (without this, the evaluator silently
# falls back to MOCK mode and produces trivially-perfect 0.0 SDs).
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os as _os
from backend.pqf.semantic.evaluator import evaluate_semantic
from backend.pqf.semantic.prompt import SEMANTIC_CRITERIA

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("image_dir")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds to wait between API calls (free-tier pacing)")
    args = ap.parse_args()

    img_dir = Path(args.image_dir)
    images = sorted(p for p in img_dir.rglob("*") if p.suffix.lower() in IMG_EXT)[: args.limit]
    if not images:
        print(f"No images found under {img_dir}")
        return

    # Announce the ACTUAL mode loudly so a silent mock fallback can never be mistaken
    # for a real API run (real run = non-zero SDs; mock = perfect 0.0 SDs).
    _mock_forced = _os.environ.get("PQF_SEMANTIC_MOCK") == "1"
    _has_key = bool(_os.environ.get("GEMINI_API_KEY"))
    if _mock_forced or not _has_key:
        print("*** MODE: MOCK (no live API) - results are NOT valid reliability evidence ***")
        print("*** Set GEMINI_API_KEY in .env and ensure PQF_SEMANTIC_MOCK is unset.    ***\n")
    else:
        print("MODE: LIVE Gemini API - these results are real reliability evidence.\n")
    print(f"Reliability check: {len(images)} images x {args.repeats} repeats\n")

    per_crit_sds = {k: [] for k, _ in SEMANTIC_CRITERIA}
    sqs_sds = []
    role_agreements = []
    failures = 0
    _errors_shown = 0

    for img in images:
        data = img.read_bytes()
        runs = []
        for _ in range(args.repeats):
            r = evaluate_semantic(data)
            runs.append(r)
            # Print the FIRST few real errors so quota/model problems are obvious
            if not r.ok and _errors_shown < 3:
                print(f"   [error on {img.name}] {r.error}")
                _errors_shown += 1
            # Pace requests to stay under the free-tier per-minute limit.
            time.sleep(args.delay)
        if any(not r.ok for r in runs):
            failures += 1
            continue
        for k, _ in SEMANTIC_CRITERIA:
            vals = [r.scores[k] for r in runs]
            per_crit_sds[k].append(statistics.pstdev(vals))
        sqs_sds.append(statistics.pstdev([r.sqs for r in runs]))
        roles = [r.role for r in runs]
        role_agreements.append(1.0 if len(set(roles)) == 1 else 0.0)

    n_ok = len(sqs_sds)
    print(f"\nEvaluated OK: {n_ok}/{len(images)}  (failures: {failures})\n")
    if n_ok == 0:
        print("No successful evaluations — check API key / model / images.")
        return

    print("Mean per-criterion score SD across repeats (0 = perfectly stable):")
    for k, _ in SEMANTIC_CRITERIA:
        vals = per_crit_sds[k]
        m = sum(vals) / len(vals) if vals else float("nan")
        print(f"  {k:24s}: {m:.4f}")

    print(f"\nMean SQS SD across repeats:   {sum(sqs_sds)/len(sqs_sds):.4f}")
    print(f"Role agreement rate:          {sum(role_agreements)/len(role_agreements):.1%}")
    print("\nInterpretation: at temperature 0, SDs near 0 and role agreement near")
    print("100% indicate the evaluator is reliable enough to use for scoring.")
    print("Report these figures in the methodology's reliability section.")


if __name__ == "__main__":
    main()
