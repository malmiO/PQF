"""
PQF Technical IQA Engine — Technical Quality Score (TQS)
==========================================================

    T1  Sharpness          (OpenCV Laplacian variance)      weight 0.25
    T2  Exposure           (grayscale histogram mean)        weight 0.20
    T3  Background purity  (HSV white-pixel border ratio)    weight 0.20
    T4  BRISQUE            (global perceptual distortion)    weight 0.15
    T5  NIQE               (natural-image statistics)        weight 0.10
    T6  PIQE               (local region quality)            weight 0.10

    TQS = 0.25*T1 + 0.20*T2 + 0.20*T3 + 0.15*T4 + 0.10*T5 + 0.10*T6
    HARD REJECT: TQS < 0.40

Design notes (see accompanying explanation document for full reasoning):
  - T1-T3 use OpenCV / scikit-image: fast, deterministic, no model download.
  - T4-T6 use the `pyiqa` library: a single, actively maintained PyTorch-based
    toolbox that provides BRISQUE, NIQE and PIQE behind one consistent API.
    On first use, pyiqa downloads small pretrained model files (~5MB) — this
    requires one-time internet access and is cached afterwards.
  - Every per-criterion score is normalised to the 0.0-1.0 range where
    1.0 = best possible quality, regardless of the metric's native scale.
  - If a pyiqa metric is unavailable (e.g. no internet on first run), the
    engine degrades gracefully: that criterion is scored as None and the
    TQS is recomputed using only the available criteria (re-weighted).
"""

import warnings
warnings.filterwarnings("ignore")

import cv2
import numpy as np
from PIL import Image
from skimage import io as skio

# ── PQF weight configuration  ─────────
WEIGHTS = {
    "sharpness":  0.25,
    "exposure":   0.20,
    "background": 0.20,
    "brisque":    0.15,
    "niqe":       0.10,
    "piqe":       0.10,
}

# ── PQF threshold configuration ─────────────────────────────────────────────
THRESHOLDS = {
    "sharpness_raw_min":   100.0,   # Laplacian variance raw cutoff
    "exposure_min":        0.30,    # histogram mean lower bound
    "exposure_max":        0.80,    # histogram mean upper bound
    "background_min":      0.55,    # border white-pixel ratio
    "brisque_raw_max":     40.0,    # lower = better; PQF accepts <= 40
    "niqe_raw_max":        35.0,    # lower = better
    "piqe_raw_max":        45.0,    # lower = better
    "tqs_hard_reject":     0.40,    # below this -> hard reject
}

# Normalisation denominators (raw_score / denom, clipped to [0,1])
SHARPNESS_NORM_DENOM = 500.0
PERCEPTUAL_NORM_DENOM = 100.0   # BRISQUE / NIQE / PIQE are all roughly 0-100


# ─────────────────────────────────────────────────────────────────────────────
# T1 — SHARPNESS  (OpenCV Laplacian variance)
# ─────────────────────────────────────────────────────────────────────────────
def score_sharpness(bgr_image: np.ndarray) -> dict:
    """
    WHY Laplacian variance:
    The Laplacian operator is a second-derivative edge filter. A sharp,
    in-focus image has many strong edges -> high-variance Laplacian
    response. A blurry image has soft transitions -> low variance.
    This is the standard, citable blur-detection method referenced in
    Abdinias & Dadrass Javan (2024) and widely used because it requires
    no training data and runs in milliseconds.
    """
    gray = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2GRAY)
    raw = cv2.Laplacian(gray, cv2.CV_64F).var()
    norm = min(raw / SHARPNESS_NORM_DENOM, 1.0)
    return {"raw": round(float(raw), 2), "norm": round(float(norm), 4)}


# ─────────────────────────────────────────────────────────────────────────────
# T2 — EXPOSURE  (grayscale histogram mean)
# ─────────────────────────────────────────────────────────────────────────────
def score_exposure(rgb_image_float: np.ndarray) -> dict:
    """
    WHY histogram mean with a target band (not a single ideal value):
    Exposure quality is not "brighter is better" or "darker is better" —
    it is about staying within a usable mid-range. A mean near 0.0 means
    a mostly black (underexposed) frame; a mean near 1.0 means a mostly
    blown-out (overexposed) frame. The PQF defines an acceptable band
    [0.30, 0.80]. Deviation outside the band is penalised proportionally,
    so an image at 0.82 loses a little, but an image at 0.20 loses a lot.
    This soft-penalty design (rather than a hard pass/fail) lets the
    overall TQS still reflect "how close" an image was to acceptable,
    which matters for the live on-screen guidance in Layer 1.
    """
    if rgb_image_float.ndim == 3:
        gray = rgb_image_float.mean(axis=2)
    else:
        gray = rgb_image_float
    mean = float(gray.mean())  # already 0-1 if image was loaded as float

    lo, hi = THRESHOLDS["exposure_min"], THRESHOLDS["exposure_max"]
    over = max(0.0, mean - hi)
    under = max(0.0, lo - mean)
    norm = max(0.0, min(1.0, 1.0 - (over + under) * 2))
    return {"raw": round(mean, 4), "norm": round(norm, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# T3 — BACKGROUND PURITY  (HSV white-pixel ratio, border region only)
# ─────────────────────────────────────────────────────────────────────────────
def score_background(bgr_image: np.ndarray) -> dict:
    """
    WHY HSV instead of RGB, and WHY the border region instead of the
    whole frame:

    HSV separates colour (Hue/Saturation) from brightness (Value), which
    makes "is this pixel white/near-white" a simple low-saturation +
    high-value test that is robust to mild colour-temperature shifts from
    different phone cameras. RGB thresholds are far more sensitive to
    those shifts.

    The PQF only checks the OUTER 25% border of the frame, not the whole
    image. The product itself sits in the centre and is (correctly) NOT
    white — checking the whole frame would penalise every product photo
    for having a non-white subject. Restricting the check to the border
    isolates the *background* and matches how RangeMe (2023) and Adobe
    (2024) define a "clean background" requirement: the area AROUND the
    product must be neutral, the product itself is exempt.
    """
    h, w = bgr_image.shape[:2]
    hsv = cv2.cvtColor(bgr_image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([0, 0, 185]), np.array([180, 35, 255]))

    bw, bh = w // 4, h // 4
    border_mask = np.zeros_like(mask)
    border_mask[:bh, :] = mask[:bh, :]          # top strip
    border_mask[-bh:, :] = mask[-bh:, :]        # bottom strip
    border_mask[:, :bw] = mask[:, :bw]          # left strip
    border_mask[:, -bw:] = mask[:, -bw:]        # right strip

    # Avoid double counting overlapping corner regions
    border_pixel_count = (
        bh * w * 2 + bw * (h - 2 * bh) * 2
    )
    white_count = int(np.count_nonzero(border_mask))
    ratio = white_count / border_pixel_count if border_pixel_count > 0 else 0.0
    norm = max(0.0, min(1.0, ratio))
    return {"raw": round(ratio, 4), "norm": round(norm, 4)}


# ─────────────────────────────────────────────────────────────────────────────
# T4-T6 — BRISQUE, NIQE, PIQE  (via pyiqa)
# ─────────────────────────────────────────────────────────────────────────────
class PerceptualScorer:
    """
    WHY a class with lazy-loaded models:
    BRISQUE/NIQE/PIQE models are loaded once (each load takes 1-3 seconds
    and may trigger a one-time download of pretrained statistics). Loading
    them per-image would make batch processing of 20-50 images extremely
    slow. A single PerceptualScorer instance is created once per batch and
    reused for every image.

    WHY pyiqa specifically:
    pyiqa provides BRISQUE, NIQE and PIQE behind one consistent PyTorch
    API with a single `pip install pyiqa`. This avoids needing three
    separate libraries (pybrisque, a NIQE-only package, a PIQE-only
    package) that each have their own dependency quirks. All three
    metrics in pyiqa are "lower is better", on roughly a 0-100 scale,
    which is normalised here to 0-1 "higher is better" to match the other
    PQF criteria.
    """

    def __init__(self, device: str = "cpu"):
        self.device = device
        self._brisque = None
        self._niqe = None
        self._piqe = None
        self._brisque_error = None
        self._niqe_error = None
        self._piqe_error = None

    def _get_metric(self, name: str):
        import pyiqa
        return pyiqa.create_metric(name, device=self.device)

    def _ensure_loaded(self, name: str):
        attr = f"_{name}"
        err_attr = f"_{name}_error"
        if getattr(self, attr) is None and getattr(self, err_attr) is None:
            try:
                setattr(self, attr, self._get_metric(name))
            except Exception as e:  # pragma: no cover - network/env dependent
                setattr(self, err_attr, str(e))

    def score(self, pil_image: Image.Image) -> dict:
        import torch
        import torchvision.transforms as T

        tensor = T.ToTensor()(pil_image.convert("RGB")).unsqueeze(0)
        results = {}

        for name, raw_max in [
            ("brisque", THRESHOLDS["brisque_raw_max"]),
            ("niqe",    THRESHOLDS["niqe_raw_max"]),
            ("piqe",    THRESHOLDS["piqe_raw_max"]),
        ]:
            self._ensure_loaded(name)
            metric = getattr(self, f"_{name}")
            if metric is None:
                results[name] = {"raw": None, "norm": None,
                                  "error": getattr(self, f"_{name}_error")}
                continue
            with torch.no_grad():
                raw = float(metric(tensor).item())
            norm = max(0.0, min(1.0, 1.0 - raw / PERCEPTUAL_NORM_DENOM))
            results[name] = {"raw": round(raw, 3), "norm": round(norm, 4)}

        return results


# ─────────────────────────────────────────────────────────────────────────────
# TQS COMBINATION
# ─────────────────────────────────────────────────────────────────────────────
def compute_tqs(image_path: str, perceptual_scorer: "PerceptualScorer") -> dict:
    """
    Runs all 6 PQF technical criteria on a single image and returns:
      - per-criterion raw + normalised scores
      - the combined TQS
      - pass/reject decision against the hard-reject threshold
      - a list of which individual criteria fell below their own threshold
        (used to build the re-capture instruction in Section 5 of the PQF
        Specification)

    WHY re-weighting on missing criteria:
    If BRISQUE/NIQE/PIQE could not be computed (e.g. first-run model
    download failed without internet), the engine does NOT crash or
    silently treat the missing score as 0. Instead it recomputes TQS using
    only the available criteria, re-normalising their weights to sum to
    1.0. This keeps the pipeline usable in degraded environments while
    making the limitation visible in the output ("available_criteria").
    """
    bgr = cv2.imread(image_path)
    if bgr is None:
        raise ValueError(f"Could not read image: {image_path}")

    pil = Image.open(image_path)
    rgb_float = skio.imread(image_path) / 255.0

    sharp = score_sharpness(bgr)
    expo = score_exposure(rgb_float)
    bg = score_background(bgr)
    perceptual = perceptual_scorer.score(pil)

    scores = {
        "sharpness":  sharp,
        "exposure":   expo,
        "background": bg,
        "brisque":    perceptual["brisque"],
        "niqe":       perceptual["niqe"],
        "piqe":       perceptual["piqe"],
    }

    # Build weighted sum over available criteria, re-normalising weights
    available = {k: v for k, v in scores.items() if v["norm"] is not None}
    weight_sum = sum(WEIGHTS[k] for k in available)
    tqs = sum(WEIGHTS[k] * available[k]["norm"] for k in available) / weight_sum
    tqs = round(tqs, 4)

    # Per-criterion threshold checks (for the re-capture instruction builder)
    failed_criteria = []
    if sharp["raw"] < THRESHOLDS["sharpness_raw_min"]:
        failed_criteria.append("sharpness")
    if not (THRESHOLDS["exposure_min"] <= expo["raw"] <= THRESHOLDS["exposure_max"]):
        failed_criteria.append("exposure")
    if bg["raw"] < THRESHOLDS["background_min"]:
        failed_criteria.append("background")
    for key, raw_max_key in [("brisque", "brisque_raw_max"),
                              ("niqe", "niqe_raw_max"),
                              ("piqe", "piqe_raw_max")]:
        val = scores[key]["raw"]
        if val is not None and val > THRESHOLDS[raw_max_key]:
            failed_criteria.append(key)

    return {
        "image": image_path,
        "tqs": tqs,
        "pass": tqs >= THRESHOLDS["tqs_hard_reject"],
        "available_criteria": list(available.keys()),
        "failed_criteria": failed_criteria,
        "scores": scores,
    }


def compute_tqs_batch(image_paths: list, device: str = "cpu") -> list:
    """Convenience wrapper: load the perceptual models ONCE, score MANY images."""
    scorer = PerceptualScorer(device=device)
    return [compute_tqs(p, scorer) for p in image_paths]


if __name__ == "__main__":
    import sys
    import json

    paths = sys.argv[1:]
    if not paths:
        print("Usage: python tqs_engine.py image1.jpg image2.jpg ...")
        sys.exit(1)

    results = compute_tqs_batch(paths)
    print(json.dumps(results, indent=2))
