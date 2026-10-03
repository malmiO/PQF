"""
Pick a test set from your own dataset, with known expected outcomes.

WHY USE LABELLED IMAGES RATHER THAN NEW PHOTOS
----------------------------------------------
Your dataset records which images are acceptable and which carry a single
deliberately introduced fault. That means you know the answer before you run the
app, so you can tell whether the framework is CORRECT rather than merely
consistent. New photographs tell you what the framework said; labelled ones tell
you whether it was right.

WHICH SPLIT THIS USES
---------------------
The CALIBRATION split only. The held out portion is left untouched, because
thresholds were tuned on calibration and scoring the holdout casually would
spend a set you may want later for a clean report.

    python research/scripts/pick_test_set.py
    python research/scripts/pick_test_set.py --category fashion_accessories

Selected images are copied to research/test_set/ with names describing what each
one is and what it should do, so the folder is self explanatory once it is on
your phone.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SPLIT_CSV = DATA / "splits" / "split_v1.csv"
MANIFEST = DATA / "master_manifest.csv"
OUT = ROOT / "research" / "test_set"


def load_roles() -> dict:
    """Maps filename to its recorded role, meaning good or degraded."""
    roles = {}
    if not MANIFEST.exists():
        return roles
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            fn = (row.get("filename") or row.get("file") or "").strip()
            role = (row.get("role") or row.get("class") or "").strip().lower()
            if fn:
                roles[fn] = role
    return roles


def is_degraded(name: str, roles: dict) -> bool:
    r = roles.get(name, "")
    if r:
        return r in {"degraded", "bad", "violation"}
    # Phone captures encode the label in the filename.
    return "_V_" in name or (name.endswith("_V.jpg"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--category", default=None,
                    help="restrict to one category folder")
    ap.add_argument("--good", type=int, default=4)
    ap.add_argument("--degraded", type=int, default=3)
    args = ap.parse_args()

    if not SPLIT_CSV.exists():
        print(f"Split file not found at {SPLIT_CSV}")
        sys.exit(1)

    roles = load_roles()
    good, degraded = [], []

    with open(SPLIT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split", "").strip().lower() != "calibration":
                continue
            rel = row["relpath"].replace("\\", "/")
            if args.category and args.category not in rel:
                continue
            p = DATA / rel
            if not p.exists():
                continue
            (degraded if is_degraded(p.name, roles) else good).append(p)

    if not good:
        print("No acceptable images found. Check the manifest role column.")
        sys.exit(1)

    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.jpg"):
        old.unlink()

    picked = []
    for i, p in enumerate(good[: args.good], start=1):
        dest = OUT / f"PASS_{i}_expect_accepted__{p.name}"
        shutil.copy2(p, dest)
        picked.append((dest.name, "should be ACCEPTED"))

    for i, p in enumerate(degraded[: args.degraded], start=1):
        dest = OUT / f"FAIL_{i}_expect_rejected__{p.name}"
        shutil.copy2(p, dest)
        picked.append((dest.name, "should be REJECTED, one known fault"))

    print(f"Copied {len(picked)} images to {OUT}\n")
    for name, expectation in picked:
        print(f"  {name}")
        print(f"      {expectation}")

    print("""
HOW TO USE THESE

Test one, the accepted set.
  Upload only the PASS images. Every one should be accepted. The set may still
  fail the gate if the roles do not cover main, two angles and a detail, and
  that is the gate working, not a fault.

Test two, the rejected set.
  Upload the FAIL images alongside two PASS ones. The FAIL images should be
  rejected, and the reason given should match the fault that was introduced.
  Check the reason, not just the verdict. A right answer for the wrong reason is
  still a defect.

Test three, the gate.
  Upload four PASS images that are all similar front views. The set should NOT
  certify, and the reason should name the missing coverage. Nothing has verified
  the set level gate on real images yet, so this is the most informative test
  of the three.

RECORD WHAT HAPPENS
  For each image, note what you expected and what the framework said. Where they
  disagree, that is either a defect to fix or a limitation to declare, and both
  belong in Chapter 4.
""")


if __name__ == "__main__":
    main()
