"""
Phase B — calibration.

Derives the two calibration-dependent config values (CALIBRATED_SHARPNESS_SMAX
for T1, CALIBRATED_COLORCAST_CMAX for T6) from the CALIBRATION split ONLY.
The holdout split is never read here — enforced below.

Outputs a report and writes suggested values to research/results/calibration_v1.txt.
It does NOT auto-edit config.py: you review the report, then paste the values in
and log the change in decisions.md (calibration is a deliberate, logged step).

Usage (from repo root, venv active):
    python research/scripts/calibrate.py
"""
from __future__ import annotations
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

# allow running from anywhere
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.pqf import config
from backend.pqf.preprocess import load_image, standardise, to_gray

DATA = ROOT / "data"
SPLIT_CSV = DATA / "splits" / "split_v1.csv"
MANIFEST = DATA / "abo" / "dataset_manifest_final.csv"
OUT = ROOT / "research" / "results" / "calibration_v1.txt"

# High percentile used as the norm ceiling, so a few outliers don't distort the
# scale. 1.0 = "as good as the best real calibration images".
SHARPNESS_PERCENTILE = 90
COLORCAST_PERCENTILE = 90


def _norm_relpath(relpath: str) -> Path:
    """CSV uses Windows backslashes relative to data/. Normalise cross-platform."""
    return DATA / relpath.replace("\\", "/")


def load_split(which: str) -> list[Path]:
    """Return image paths for the requested split ('calibration' or 'holdout')."""
    if not SPLIT_CSV.exists():
        raise FileNotFoundError(f"Split file not found: {SPLIT_CSV}")
    paths = []
    with open(SPLIT_CSV, newline="") as f:
        for row in csv.DictReader(f):
            if row["split"].strip() == which:
                paths.append(_norm_relpath(row["relpath"].strip()))
    return paths


def load_roles() -> dict[str, str]:
    """filename -> role (good/degraded) from the ABO manifest, if present."""
    roles = {}
    if MANIFEST.exists():
        with open(MANIFEST, newline="") as f:
            for row in csv.DictReader(f):
                roles[row["filename"].strip()] = row.get("role", "").strip()
    return roles


def is_good(path: Path, roles: dict[str, str]) -> bool:
    """Good if manifest says so, or (phone images) if filename marks it CLEAN."""
    name = path.name
    if name in roles:
        return roles[name] == "good"
    # phone images: *_CLEAN good, *_V_* / *_V- degraded
    upper = name.upper()
    if "CLEAN" in upper:
        return True
    if "_V_" in upper or "_V-" in upper:
        return False
    return True  # default: treat unlabelled as good (reported below)


def raw_sharpness(img: np.ndarray) -> float:
    return float(cv2.Laplacian(to_gray(img), cv2.CV_64F).var())


def raw_colorcast(img: np.ndarray) -> float | None:
    """Raw cast magnitude in the near-white border region; None if it abstains."""
    from backend.pqf.technical import _border_mask
    mask = _border_mask(img.shape, config.T3_BORDER_FRACTION)
    border = img[mask]
    near_white = np.all(border >= config.T3_WHITE_THRESHOLD, axis=1)
    if not border.size or float(near_white.mean()) < config.T6_MIN_NEUTRAL_FRACTION:
        return None
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    a = lab[:, :, 1] - 128.0
    b = lab[:, :, 2] - 128.0
    full = np.zeros(img.shape[:2], dtype=bool)
    full[mask] = near_white
    return float(np.hypot(a[full].mean(), b[full].mean()))


def main() -> None:
    lines = []
    def log(s=""):
        print(s)
        lines.append(s)

    log("=" * 64)
    log("PQF Phase B — Calibration (calibration split ONLY)")
    log("=" * 64)

    cal = load_split("calibration")
    holdout_count = len(load_split("holdout"))
    roles = load_roles()

    log(f"Calibration images listed: {len(cal)}")
    log(f"Holdout images listed:     {holdout_count}  (NOT used here)")
    if not cal:
        log("ERROR: no calibration images found. Check split_v1.csv paths.")
        _write(lines)
        return

    # collect raw metrics over GOOD calibration images
    sharp_vals, cast_vals = [], []
    missing, degraded_skipped, cast_abstained = 0, 0, 0
    for p in cal:
        if not p.exists():
            missing += 1
            continue
        if not is_good(p, roles):
            degraded_skipped += 1
            continue
        img = standardise(load_image(str(p)))
        sharp_vals.append(raw_sharpness(img))
        c = raw_colorcast(img)
        if c is None:
            cast_abstained += 1
        else:
            cast_vals.append(c)

    log("")
    log(f"Good calibration images used:  {len(sharp_vals)}")
    log(f"  degraded (skipped):          {degraded_skipped}")
    log(f"  missing on disk:             {missing}")
    log(f"  T6 abstained (no neutral):   {cast_abstained}")

    if missing:
        log("  ⚠ some listed images not found — check paths before trusting values.")

    # --- T1 sharpness S_MAX ---
    if sharp_vals:
        arr = np.array(sharp_vals)
        smax = float(np.percentile(arr, SHARPNESS_PERCENTILE))
        log("")
        log("T1 — Sharpness (raw Laplacian variance over good calibration images)")
        log(f"  min/median/max: {arr.min():.1f} / {np.median(arr):.1f} / {arr.max():.1f}")
        log(f"  p{SHARPNESS_PERCENTILE} (suggested S_MAX): {smax:.1f}")
    else:
        smax = config.CALIBRATED_SHARPNESS_SMAX
        log("  no sharpness values — keeping existing S_MAX")

    # --- T6 colour-cast C_MAX ---
    if cast_vals:
        arr = np.array(cast_vals)
        cmax = float(np.percentile(arr, COLORCAST_PERCENTILE))
        # guard against a near-zero ceiling (all images very clean)
        cmax = max(cmax, 5.0)
        log("")
        log("T6 — Colour-cast (raw magnitude in neutral region, good images)")
        log(f"  min/median/max: {arr.min():.2f} / {np.median(arr):.2f} / {arr.max():.2f}")
        log(f"  p{COLORCAST_PERCENTILE} (suggested C_MAX, min 5.0): {cmax:.2f}")
        log("  NOTE: dataset has no dedicated cast-violation images (logged")
        log("        limitation) — this calibrates the SCALE, not detection accuracy.")
    else:
        cmax = config.CALIBRATED_COLORCAST_CMAX
        log("  no colour-cast values — keeping existing C_MAX")

    log("")
    log("-" * 64)
    log("PASTE THESE INTO backend/pqf/config.py (then log in decisions.md):")
    log(f"  CALIBRATED_SHARPNESS_SMAX = {smax:.1f}")
    log(f"  CALIBRATED_COLORCAST_CMAX = {cmax:.2f}")
    log("-" * 64)
    log("Holdout was not read. Calibration is complete.")

    _write(lines)


def _write(lines):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport written to {OUT}")


if __name__ == "__main__":
    main()
