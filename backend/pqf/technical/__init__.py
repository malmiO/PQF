"""
Technical IQA engine: T0 compliance gate + T1-T6 weighted criteria -> TQS.

Each criterion returns a normalised score in [0, 1] (1 = best). Deterministic,
offline, no network. Spec v1.2.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import cv2
import numpy as np

from .. import config
from ..preprocess import to_gray


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


# ---------------------------------------------------------------------------
# T0 — platform compliance gate (binary)
# ---------------------------------------------------------------------------
def t0_compliance(img: np.ndarray) -> bool:
    """True if the image passes the mandatory platform gate."""
    h, w = img.shape[:2]
    if w < config.T0_MIN_RESOLUTION[0] or h < config.T0_MIN_RESOLUTION[1]:
        return False
    aspect = w / h
    return config.T0_ASPECT_MIN <= aspect <= config.T0_ASPECT_MAX


# ---------------------------------------------------------------------------
# T1 — sharpness (Laplacian variance)
# ---------------------------------------------------------------------------
def t1_sharpness(img: np.ndarray) -> float:
    gray = to_gray(img)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    return _clip01(variance / config.CALIBRATED_SHARPNESS_SMAX)


# ---------------------------------------------------------------------------
# T2 — exposure (mean luminance distance from ideal band)
# ---------------------------------------------------------------------------
def t2_exposure(img: np.ndarray) -> float:
    gray = to_gray(img)
    mean = float(gray.mean())
    if config.T2_IDEAL_LOW <= mean <= config.T2_IDEAL_HIGH:
        return 1.0
    dist = (config.T2_IDEAL_LOW - mean) if mean < config.T2_IDEAL_LOW else (mean - config.T2_IDEAL_HIGH)
    return _clip01(1.0 - dist / config.T2_TOLERANCE)


# ---------------------------------------------------------------------------
# T3 — background purity (near-white border fraction) + reusable neutral mask
# ---------------------------------------------------------------------------
def _border_mask(shape, frac: float) -> np.ndarray:
    """Boolean mask: True on the outer `frac` frame (the background region)."""
    h, w = shape[:2]
    bh, bw = max(1, int(h * frac)), max(1, int(w * frac))
    mask = np.zeros((h, w), dtype=bool)
    mask[:bh, :] = True
    mask[-bh:, :] = True
    mask[:, :bw] = True
    mask[:, -bw:] = True
    return mask


def t3_background(img: np.ndarray) -> float:
    """Fraction of border pixels that are near-white (all channels >= threshold)."""
    mask = _border_mask(img.shape, config.T3_BORDER_FRACTION)
    border = img[mask]  # (N, 3) BGR
    near_white = np.all(border >= config.T3_WHITE_THRESHOLD, axis=1)
    return _clip01(float(near_white.mean()))


# ---------------------------------------------------------------------------
# T4 — BRISQUE (lower raw is better)
# ---------------------------------------------------------------------------
def t4_brisque(img: np.ndarray) -> float:
    try:
        from brisque import BRISQUE
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        raw = BRISQUE().score(rgb)
    except Exception:
        # If the library/model is unavailable, abstain neutrally (documented).
        return 1.0
    return _clip01(1.0 - raw / config.T4_BRISQUE_MAX)


# ---------------------------------------------------------------------------
# T5 — PIQE (lower raw is better)
# ---------------------------------------------------------------------------
def t5_piqe(img: np.ndarray) -> float:
    try:
        import pypiqe
        gray = to_gray(img)
        raw = pypiqe.piqe(gray)[0] if isinstance(pypiqe.piqe(gray), tuple) else pypiqe.piqe(gray)
    except Exception:
        return 1.0
    return _clip01(1.0 - float(raw) / config.T5_PIQE_MAX)


# ---------------------------------------------------------------------------
# T6 — colour-cast detection (v1.2): grey-world in the T3 neutral region only
# ---------------------------------------------------------------------------
def t6_colorcast(img: np.ndarray) -> float:
    """Detect a colour CAST (not verify colour accuracy).

    Measures mean (a*, b*) deviation from neutral in the near-white background
    region only, so a legitimately colourful product does not trigger a cast.
    Abstains (returns 1.0) if too little neutral region exists.
    """
    mask = _border_mask(img.shape, config.T3_BORDER_FRACTION)
    # restrict to near-white (neutral) border pixels
    border = img[mask]
    near_white = np.all(border >= config.T3_WHITE_THRESHOLD, axis=1)
    neutral_frac = float(near_white.mean()) if border.size else 0.0
    if neutral_frac < config.T6_MIN_NEUTRAL_FRACTION:
        return 1.0  # abstain: not enough neutral region to judge

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    # OpenCV LAB: a,b in [0,255] centred at 128 → shift to centre 0
    a = lab[:, :, 1] - 128.0
    b = lab[:, :, 2] - 128.0
    full_mask = np.zeros(img.shape[:2], dtype=bool)
    full_mask[mask] = near_white  # neutral border pixels only
    mean_a = float(a[full_mask].mean())
    mean_b = float(b[full_mask].mean())
    cast_magnitude = float(np.hypot(mean_a, mean_b))
    return _clip01(1.0 - cast_magnitude / config.CALIBRATED_COLORCAST_CMAX)


# ---------------------------------------------------------------------------
# TQS aggregation
# ---------------------------------------------------------------------------
@dataclass
class TechnicalResult:
    passed_gate: bool
    scores: dict = field(default_factory=dict)   # per-criterion normalised
    tqs: float = 0.0
    hard_reject: bool = False


def compute_tqs(img: np.ndarray) -> TechnicalResult:
    """Run the full technical engine on a standardised image."""
    if not t0_compliance(img):
        return TechnicalResult(passed_gate=False, hard_reject=True)

    scores = {
        "sharpness":  t1_sharpness(img),
        "exposure":   t2_exposure(img),
        "background": t3_background(img),
        "brisque":    t4_brisque(img),
        "piqe":       t5_piqe(img),
        "colorcast":  t6_colorcast(img),
    }
    tqs = sum(config.TQS_WEIGHTS[k] * scores[k] for k in config.TQS_WEIGHTS)
    return TechnicalResult(
        passed_gate=True,
        scores=scores,
        tqs=float(tqs),
        hard_reject=tqs < config.TQS_HARD_REJECT,
    )
