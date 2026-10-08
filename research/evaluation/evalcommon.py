"""
evalcommon.py  -  shared pieces of the PQF evaluation harness (2026-10-07).

Everything that decides a NUMBER in the report lives here, so it is defined once:
dataset discovery and labels, the per-criterion pass thresholds taken from the
specification, and the statistics (Wilson intervals, AUC, rank tests).

Pass thresholds (SPEC_PASS) are the specification's own, PQF Specification v1.3:
  T1 sharpness   sharpness_norm >= 0.20                      (s3.2)
  T2 exposure    mean luminance in [0.30, 0.80] of full scale (s3.3). The code scores
                 distance outside the ideal band [100, 180] with a 60 level tolerance,
                 so the spec band edges 76.5 and 204 correspond to exposure_norm 0.61
                 and 0.60; the equivalent threshold is exposure_norm >= 0.60.
  T3 background  border white ratio >= 0.55                   (s3.4)
  T4 BRISQUE     raw <= 40  ->  brisque_norm >= 0.60          (s3.5)
  T5 PIQE        raw <= 45  ->  piqe_norm >= 0.55             (s3.6)
  T6 colour cast colorcast_norm >= 0.60                       (s3.7)
  S1-S3 >= 0.60, S4-S5 >= 0.50                                (s4.2, config.SQS_PASS_THRESHOLDS)
No threshold here is tuned on evaluation data.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from backend.pqf import config  # noqa: E402

SPEC_PASS = {"sharpness": 0.20, "exposure": 0.60, "background": 0.55,
             "brisque": 0.60, "piqe": 0.55, "colorcast": 0.60,
             **config.SQS_PASS_THRESHOLDS}
TECH = list(config.TQS_WEIGHTS)
SEM = list(config.SQS_WEIGHTS)
LABEL = {"sharpness": "T1 Sharpness", "exposure": "T2 Exposure", "background": "T3 Background",
         "brisque": "T4 BRISQUE", "piqe": "T5 PIQE", "colorcast": "T6 Colour cast",
         "subject_centering": "S1 Centring", "feature_visibility": "S2 Feature visibility",
         "marketing_suitability": "S3 Marketing suitability", "angle_value": "S4 Angle value",
         "lighting_style_quality": "S5 Lighting and style"}

# Constructed violations (frozen dataset, decisions.md 2026-08-05) -> target criterion
VIOLATION = {"BLUR": "sharpness", "DARK": "exposure", "BRIGHT": "exposure",
             "CLUTTER": "background", "OFFCENTRE": "subject_centering", "ANGLE": "angle_value"}
_NAME = re.compile(r"^(p\d{2})[_-](CLEAN|V[_-](BLUR|DARK|BRIGHT|CLUTTER|OFFCENTRE|ANGLE))\b",
                   re.IGNORECASE)
IMG_EXT = {".jpg", ".jpeg", ".png", ".webp"}


def discover(root: Path) -> list:
    """Every image under root with its label.
    Researcher captures: pNN_CLEAN / pNN_V-<FAULT> (either separator).
    Anything under a folder named 'abo' is a professional catalogue image (good)."""
    rows = []
    for p in sorted(root.rglob("*")):
        if p.suffix.lower() not in IMG_EXT or p.name.startswith("."):
            continue
        m = _NAME.match(p.name)
        parts = [x.lower() for x in p.parts]
        if m:
            code = m.group(2).upper().replace("_", "-")
            fault = m.group(3).upper() if m.group(3) else ""
            rows.append({"path": str(p), "relpath": str(p.relative_to(root)),
                         "category": p.parent.name, "source": "researcher_capture",
                         "product": f"{p.parent.name}/{m.group(1).lower()}",
                         "label": "good" if code == "CLEAN" else "degraded",
                         "fault": fault, "target": VIOLATION.get(fault, "")})
        elif "abo" in parts:
            rows.append({"path": str(p), "relpath": str(p.relative_to(root)),
                         "category": p.parent.name, "source": "ABO",
                         "product": f"abo/{p.stem}", "label": "good", "fault": "",
                         "target": ""})
    return rows


def apply_split(rows: list, split_csv: Path | None, subset: str | None) -> list:
    """Keep only rows in the chosen part of the frozen split (splits/split_v1.csv,
    columns relpath,split,seed). Matching is by category + file stem, ignoring the
    separator style, because files were renamed between capture and assembly."""
    if subset and not split_csv:
        raise SystemExit("--subset needs --split (the frozen split file); refusing to score "
                         "every image under a subset label.")
    if not subset:
        return rows
    norm = lambda s: re.sub(r"[_-]", "", Path(s).stem.lower())
    keep = {}
    with open(split_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rp = Path(r["relpath"])
            keep[(rp.parent.name, norm(rp.name))] = r["split"]
    out = [r for r in rows if keep.get((r["category"], norm(r["path"]))) == subset]
    missing = [r for r in rows if (r["category"], norm(r["path"])) not in keep]
    if missing:
        print(f"WARNING: {len(missing)} images are not in the split file, e.g. {missing[0]['relpath']}")
    return out


def platform_format(img):
    """The API's platform formatting step (backend/api/main.py _platform_format,
    2026-10-01), applied so the harness scores exactly what the app scores: an image
    outside the 4:5 to 1.91:1 range is capped at 2048 px and centre cropped to the
    nearest edge of the range; in-range images are unchanged."""
    import cv2
    lo, hi = config.T0_ASPECT_MIN, config.T0_ASPECT_MAX
    h, w = img.shape[:2]
    if lo <= w / h <= hi:
        return img
    if max(h, w) > 2048:
        k = 2048 / max(h, w)
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    if w / h < lo:
        nh = int(w / lo); t = (h - nh) // 2
        return img[t:t + nh, :]
    nw = int(h * hi); l = (w - nw) // 2
    return img[:, l:l + nw]


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for a proportion (Wilson, 1927), robust at small n."""
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def auc(pos: list, neg: list) -> float:
    """Probability a random GOOD image scores higher than a random VIOLATING one
    (Mann-Whitney U / (n1 n2)); 0.5 = no discrimination, 1.0 = perfect."""
    if not pos or not neg:
        return float("nan")
    gt = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a in pos for b in neg)
    return gt / (len(pos) * len(neg))


def fmt_ci(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100*k/n:.0f}%, 95% CI {100*lo:.0f}-{100*hi:.0f}%)" if n else "n/a"


def write_csv(path: Path, rows: list):
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> list:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, default=lambda o: sorted(o) if isinstance(o, set) else float(o)), encoding="utf-8")


def model_version() -> str:
    """The model version that actually answers for config.GEMINI_MODEL (an alias such
    as gemini-flash-lite-latest can move), from one tiny text call."""
    import os
    try:
        from google import genai
        r = genai.Client(api_key=os.environ["GEMINI_API_KEY"]).models.generate_content(
            model=config.GEMINI_MODEL, contents="Reply with OK.")
        return getattr(r, "model_version", None) or "not reported"
    except Exception as e:
        return f"unknown ({type(e).__name__})"


def environment() -> dict:
    """What produced the numbers: library versions, metric status, model name."""
    import platform
    import numpy, cv2, scipy
    from backend.pqf.technical import metric_status
    env = {"python": platform.python_version(), "numpy": numpy.__version__,
           "opencv": cv2.__version__, "scipy": scipy.__version__,
           "metric_status": metric_status(), "gemini_model": config.GEMINI_MODEL,
           "prompt_version": config.PROMPT_VERSION}
    from importlib.metadata import version
    for mod in ("brisque", "pypiqe", "scikit-image", "google-genai"):
        try:
            env[mod] = version(mod)
        except Exception as e:
            env[mod] = f"unavailable ({type(e).__name__})"
    return env
