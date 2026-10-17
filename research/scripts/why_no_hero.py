"""
Explain why images are, or are not, classified as hero shots.

WHY THIS EXISTS
---------------
"No hero shot" tells you the gate refused a set. It does not tell you which
criterion blocked it, and without that you are guessing at whether the problem is
the images, the thresholds, or a defect.

This scores a folder and reports, for every image, exactly how far each role rule
was from being satisfied. An image that missed hero by 0.02 on one criterion is a
different situation from one that missed by 0.4 on three, and the response
differs accordingly.

    python research/scripts/why_no_hero.py data/abo/cosmetics_care --limit 8
    python research/scripts/why_no_hero.py research/test_set

Each image costs one call to the semantic model, so keep the limit modest.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os

from backend.pqf import config
from backend.pqf.pipeline import score_image

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--limit", type=int, default=8)
    args = ap.parse_args()

    live = bool(os.environ.get("GEMINI_API_KEY")) and \
        os.environ.get("PQF_SEMANTIC_MOCK") != "1"
    print("=" * 74)
    print("MODE.  " + ("LIVE Gemini, results are real."
                       if live else "MOCK, semantic scores are NOT real."))
    print("=" * 74)

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Folder not found. {folder}")
        sys.exit(1)

    images = sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMG_EXT)
    images = images[: args.limit]
    if not images:
        print("No images found.")
        sys.exit(1)

    print(f"\nScoring {len(images)} images from {folder}\n")

    hero_rule = config.ROLE_RULES["hero_shot"]
    role_counts = {"hero_shot": 0, "angle_shot": 0, "detail_shot": 0, "reject": 0}
    blockers = {}

    for p in images:
        d = score_image(p.read_bytes(), path=p.name)
        role_counts[d.role] = role_counts.get(d.role, 0) + 1

        print(f"{p.name}")
        print(f"   TQS {d.tqs:.3f}   SQS {d.sqs:.3f}   FQS {d.fqs:.3f}"
              f"   -> {d.role}")

        if d.hard_rejected:
            print(f"   rejected before scoring. {d.reason}\n")
            blockers["hard reject"] = blockers.get("hard reject", 0) + 1
            continue

        # Distance from the hero rule, criterion by criterion.
        gaps = []
        need_fqs = hero_rule["fqs_min"]
        if d.fqs < need_fqs:
            gaps.append(("FQS", d.fqs, need_fqs))
        for k, v in hero_rule["criteria_min"].items():
            got = d.semantic_scores.get(k, 0.0)
            if got < v:
                gaps.append((k, got, v))

        if not gaps:
            print("   meets every hero condition\n")
        else:
            for name, got, need in gaps:
                short = need - got
                print(f"   blocks hero.  {name:<24} {got:.3f} "
                      f"needs {need:.2f}  short by {short:.3f}")
                blockers[name] = blockers.get(name, 0) + 1
            print()

    # Summary, which is what actually tells you what to do next.
    print("=" * 74)
    print("ROLES ASSIGNED")
    for role, n in role_counts.items():
        if n:
            print(f"   {role:<14} {n}")

    if role_counts.get("hero_shot", 0) == 0 and blockers:
        print("\nWHY NO HERO SHOT. Most common blocker first.")
        for name, n in sorted(blockers.items(), key=lambda kv: -kv[1]):
            print(f"   {name:<24} blocked {n} of {len(images)} images")

        top = max(blockers.items(), key=lambda kv: kv[1])[0]
        print("\nWHAT THIS MEANS")
        if top == "FQS":
            print("   Overall score is the constraint, not any single criterion.")
            print("   Look at whether TQS or SQS is dragging it down. If TQS is")
            print("   low across the board, the calibration is suspect. If SQS is")
            print("   low, the images may genuinely not read as marketing ready.")
        elif top == "subject_centering":
            print("   The product is not centred enough in these images. ABO")
            print("   catalogue images are usually well centred, so if this is")
            print("   blocking most of them, check whether the semantic evaluator")
            print("   is judging centring as expected before assuming the images")
            print("   are at fault.")
        elif top == "marketing_suitability":
            print("   The evaluator does not consider these ready to post. That is")
            print("   a judgement, so read the per criterion scores and decide")
            print("   whether you agree. If you disagree consistently, the prompt")
            print("   wording is the thing to examine.")
        elif top == "hard reject":
            print("   Images are failing before scoring, on T0 or on technical")
            print("   quality. Check resolution and aspect ratio first.")
        print("\n   Record whichever it is. A framework that cannot classify a")
        print("   professional catalogue image as a hero shot is either")
        print("   mis-calibrated or is telling you something real about the data,")
        print("   and both are Chapter 4 findings.")
    elif role_counts.get("hero_shot", 0):
        print("\n   At least one hero shot was found, so the gate should be")
        print("   satisfiable with a set that also covers angles and detail.")


if __name__ == "__main__":
    main()
