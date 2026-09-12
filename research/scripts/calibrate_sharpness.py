"""
Sharpness calibration, separation based.

WHY THIS REPLACES THE PERCENTILE APPROACH
-----------------------------------------
Product-region Laplacian variance measures DETAIL, not only sharpness. A
patterned accessory produces very high variance, a smooth cosmetic bottle
produces low variance, even when both are perfectly in focus. On the calibration
split the spread was min 20, median 273, max 10475.

Taking a high percentile as the ceiling therefore made typical good images score
near zero. Taking a low percentile would make blurred images pass. Neither is
defensible.

Instead this script chooses the ceiling that best SEPARATES the good images from
the deliberately degraded ones, using the ground truth you already have by
construction, and it reports the separation quality so the choice is evidenced
rather than asserted.

It reads the calibration split only. The holdout is never touched.

    python research/scripts/calibrate_sharpness.py
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.pqf.preprocess import standardise
from backend.pqf import technical as T
from backend.pqf import config

DATA = ROOT / "data"
SPLIT_CSV = DATA / "splits" / "split_v1.csv"
MANIFEST = DATA / "master_manifest.csv"
OUT = ROOT / "research" / "results" / "calibration_sharpness.txt"

PASS_THRESHOLD = 0.20   # spec: sharpness_norm must reach this to pass


def is_degraded(path: Path, manifest: dict) -> bool:
    """True if the image is a deliberately degraded one.

    Uses the manifest role column when available, otherwise falls back to the
    filename convention used for phone captures.
    """
    key = path.name
    if key in manifest:
        return manifest[key].strip().lower() in {"degraded", "bad", "violation"}
    # phone captures encode the label in the filename
    return "_V_" in key or "_V" in key.replace("_CLEAN", "")


def load_manifest() -> dict:
    m = {}
    if MANIFEST.exists():
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                fn = row.get("filename") or row.get("file") or ""
                role = row.get("role") or row.get("class") or ""
                if fn:
                    m[fn.strip()] = role
    return m


def variance_of(path: Path) -> float | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    img = standardise(img)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    mask = T.product_mask(img)
    vals = lap[mask] if mask.any() else lap.ravel()
    return float(vals.var())


def main() -> None:
    if not SPLIT_CSV.exists():
        print(f"Split file not found. {SPLIT_CSV}")
        sys.exit(1)

    manifest = load_manifest()
    good, degraded = [], []

    with open(SPLIT_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("split", "").strip().lower() != "calibration":
                continue
            p = DATA / row["relpath"].replace("\\", "/")
            if not p.exists():
                continue
            v = variance_of(p)
            if v is None:
                continue
            (degraded if is_degraded(p, manifest) else good).append((p.name, v))

    if not good:
        print("No good calibration images identified. Check the manifest role column.")
        sys.exit(1)

    g = np.array([v for _, v in good])
    d = np.array([v for _, v in degraded]) if degraded else np.array([])

    print(f"Good images      {len(g):>4}   min {g.min():>9.1f}  median {np.median(g):>9.1f}  max {g.max():>9.1f}")
    if d.size:
        print(f"Degraded images  {len(d):>4}   min {d.min():>9.1f}  median {np.median(d):>9.1f}  max {d.max():>9.1f}")
    else:
        print("Degraded images     0   (no degraded images found in the calibration split)")

    # Candidate ceilings. For each, compute how many good images pass and how many
    # degraded images are correctly rejected, at the spec pass threshold.
    print()
    print("Candidate ceilings, judged by separation at the spec pass threshold of "
          f"{PASS_THRESHOLD}")
    print(f"  {'S_MAX':>10}{'good pass':>12}{'degraded rej':>15}{'separation':>13}")

    candidates = sorted({
        float(np.percentile(g, p)) for p in (10, 20, 25, 30, 40, 50, 60, 75, 90)
    })
    best, best_score = None, -1.0
    for smax in candidates:
        if smax <= 0:
            continue
        good_pass = float(np.mean(np.minimum(g / smax, 1.0) >= PASS_THRESHOLD))
        deg_rej = float(np.mean(np.minimum(d / smax, 1.0) < PASS_THRESHOLD)) if d.size else float("nan")
        # Separation. Reward passing good images and rejecting degraded ones equally.
        sep = good_pass if not d.size else (good_pass + deg_rej) / 2.0
        marker = ""
        if sep > best_score:
            best_score, best, marker = sep, smax, ""
        print(f"  {smax:>10.1f}{good_pass:>11.0%}{deg_rej:>14.0%}{sep:>12.0%}{marker}")

    print()
    print(f"SUGGESTED  CALIBRATED_SHARPNESS_SMAX = {best:.1f}")
    print(f"           separation quality {best_score:.0%}")
    print()
    gp = float(np.mean(np.minimum(g / best, 1.0) >= PASS_THRESHOLD))
    print(f"At this ceiling, {gp:.0%} of good calibration images pass the sharpness criterion,")
    if d.size:
        dr = float(np.mean(np.minimum(d / best, 1.0) < PASS_THRESHOLD))
        print(f"and {dr:.0%} of deliberately degraded images are correctly rejected by it.")
    print()
    print("Note for the write up. Product-region Laplacian variance measures detail as")
    print("well as focus, so a single global ceiling cannot fit every product texture.")
    print("The ceiling is therefore chosen for separation between known good and known")
    print("degraded images rather than as a percentile of good images alone. This is a")
    print("declared calibration decision and is reported with the separation achieved.")

    report = [
        "Sharpness calibration, separation based",
        f"good images {len(g)}, degraded images {len(d) if d.size else 0}",
        f"good      min {g.min():.1f} median {np.median(g):.1f} max {g.max():.1f}",
    ]
    if d.size:
        report.append(f"degraded  min {d.min():.1f} median {np.median(d):.1f} max {d.max():.1f}")
    report += [
        f"chosen CALIBRATED_SHARPNESS_SMAX = {best:.1f}",
        f"separation quality {best_score:.0%}",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(report), encoding="utf-8")
    print(f"Written to {OUT}")


if __name__ == "__main__":
    main()
