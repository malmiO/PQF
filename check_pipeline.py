"""
End-to-end framework check.

Runs ONE image through the complete PQF pipeline and reports every stage, so you
can see exactly what each criterion contributed rather than only the final score.

Loads .env first, and states plainly whether it is using the live model or the
mock evaluator, so a silent fallback can never be mistaken for a real result.

Usage
    python check_pipeline.py <path_to_image>
    python check_pipeline.py <path_to_image> --mock     (force mock, no API call)
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Load .env BEFORE importing the evaluator, otherwise the key is not visible.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv is not installed. Run  pip install python-dotenv")

ap = argparse.ArgumentParser()
ap.add_argument("image")
ap.add_argument("--mock", action="store_true", help="force mock mode, no API call")
args = ap.parse_args()

if args.mock:
    os.environ["PQF_SEMANTIC_MOCK"] = "1"

# Announce the real mode loudly.
forced_mock = os.environ.get("PQF_SEMANTIC_MOCK") == "1"
has_key = bool(os.environ.get("GEMINI_API_KEY"))
if forced_mock:
    mode = "MOCK, forced by flag. Semantic scores are NOT real."
elif not has_key:
    mode = "MOCK, no GEMINI_API_KEY found. Semantic scores are NOT real."
else:
    mode = "LIVE Gemini. Semantic scores are real."

print("=" * 66)
print("MODE.  " + mode)
print("=" * 66)

img_path = Path(args.image)
if not img_path.exists():
    print(f"Image not found. {img_path}")
    sys.exit(1)

data = img_path.read_bytes()

from backend.pqf import config
from backend.pqf.pipeline import score_image

d = score_image(data, path=str(img_path))

print(f"\nImage.  {img_path.name}   ({len(data)/1024:.0f} KB)\n")

# ---- technical breakdown ----
tech = getattr(d, "technical_scores", {})
if tech:
    print("TECHNICAL CRITERIA, normalised 0 to 1, with weight and contribution")
    print(f"  {'criterion':<14}{'score':>8}{'weight':>9}{'contrib':>10}")
    total = 0.0
    for k, w in config.TQS_WEIGHTS.items():
        s = tech.get(k, 0.0)
        c = s * w
        total += c
        flag = "  <-- low" if s < 0.40 else ""
        print(f"  {k:<14}{s:>8.3f}{w:>9.2f}{c:>10.3f}{flag}")
    print(f"  {'TQS':<14}{'':>8}{'':>9}{total:>10.3f}")
else:
    print("No technical breakdown available. The image stopped before scoring.")

# ---- semantic breakdown ----
if d.semantic_scores:
    print("\nSEMANTIC CRITERIA, normalised 0 to 1, with weight and contribution")
    print(f"  {'criterion':<24}{'score':>8}{'weight':>9}{'contrib':>10}")
    total = 0.0
    for k, w in config.SQS_WEIGHTS.items():
        s = d.semantic_scores.get(k, 0.0)
        c = s * w
        total += c
        thr = config.SQS_PASS_THRESHOLDS.get(k, 0.0)
        flag = "  <-- below pass" if s < thr else ""
        print(f"  {k:<24}{s:>8.3f}{w:>9.2f}{c:>10.3f}{flag}")
    print(f"  {'SQS':<24}{'':>8}{'':>9}{total:>10.3f}")
else:
    print("\nNo semantic scores. The image was rejected before the semantic stage.")

# ---- decision ----
print("\nDECISION")
print(f"  TQS                 {d.tqs:.3f}")
print(f"  SQS                 {d.sqs:.3f}")
print(f"  FQS = {config.FQS_ALPHA}*TQS + {config.FQS_BETA}*SQS   {d.fqs:.3f}")
print(f"  pass threshold      {config.FQS_PASS_THRESHOLD}")
print(f"  role                {d.role}")
print(f"  passed              {d.passed}")
print(f"  hard rejected       {d.hard_rejected}")
print(f"  reason              {d.reason}")

# ---- why this role ----
print("\nROLE RULES, and whether this image met them")
for role in config.ROLE_PRIORITY:
    rule = config.ROLE_RULES[role]
    ok_fqs = d.fqs >= rule["fqs_min"]
    parts = [f"FQS>={rule['fqs_min']} {'yes' if ok_fqs else 'no'}"]
    all_ok = ok_fqs
    for k, v in rule["criteria_min"].items():
        got = d.semantic_scores.get(k, 0.0)
        ok = got >= v
        all_ok = all_ok and ok
        parts.append(f"{k}>={v} {'yes' if ok else f'no ({got:.2f})'}")
    print(f"  {role:<12} {'MATCH' if all_ok else '     '}  " + ",  ".join(parts))

if forced_mock or not has_key:
    print("\nReminder. Semantic numbers above are mock and mean nothing.")
    print("Run without --mock, with GEMINI_API_KEY set in .env, for a real result.")
