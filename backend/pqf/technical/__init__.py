"""
Technical IQA engine: T0 compliance gate + T1-T6 weighted criteria -> TQS.

Each criterion returns a normalised score in [0, 1] (1 = best). Deterministic,
offline, no network. Spec v1.2.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import threading
import cv2
import numpy as np

from .. import config
from ..preprocess import to_gray

# BRISQUE (libsvm) and PIQE use native code that is NOT thread-safe: loading the
# SVM model from more than one thread corrupts the heap (crash 0xc0000374).
# When /batch scores images concurrently (bounded concurrency, 2026-10-13) these
# native metrics are serialised with this lock. It changes no score - only one
# thread runs the native metric at a time; the slow part (the Gemini network
# call) still overlaps across threads.
_NATIVE_METRIC_LOCK = threading.Lock()


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
# Product-region localisation
# ---------------------------------------------------------------------------
def product_mask(img: np.ndarray) -> np.ndarray:
    """Boolean mask, True on pixels judged to belong to the product.

    The background colour is ESTIMATED from the image border (median of the
    border band) and pixels that differ clearly from it are taken as product.
    The first version used a fixed near-white threshold, which failed on a real
    budget lightbox: its background reads light grey (about 200 of 255), so 99
    percent of the frame was taken as "product" and sharpness and exposure were
    measured over the smooth background (found 2026-10-05). On a true white
    background the estimate is near white and the result matches the old rule.

    This changes only WHERE the product is measured. Whether the background is
    acceptably white is still judged by T3 against the fixed platform standard.

    Falls back to the central region when segmentation finds too little or
    nearly everything, so a failed segmentation is never silently measured.
    """
    h, w = img.shape[:2]
    b = max(2, int(min(h, w) * config.T3_BORDER_FRACTION))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                             img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)                                # estimated background
    spread = np.median(np.abs(border - bg), axis=0).max()         # how uneven it is
    delta = min(config.PRODUCT_BG_DELTA_MAX,
                max(config.PRODUCT_BG_DELTA_MIN, config.PRODUCT_BG_DELTA_K * float(spread)))
    matching = (np.abs(border.astype(np.int16) - bg.astype(np.int16)).max(axis=1)
                <= config.PRODUCT_BG_DELTA_MIN).mean()
    if matching < config.PRODUCT_BG_MIN_MATCH:
        # The border is not a plain background (a close up whose product covers
        # the edges). The estimate is meaningless, so use the original rule.
        prod = ~np.all(img >= config.T3_WHITE_THRESHOLD, axis=2)
    else:
        diff = np.abs(img.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
        prod = diff > delta

    # Close small holes so highlights inside the product are not lost.
    kernel = np.ones((7, 7), np.uint8)
    prod = cv2.morphologyEx(prod.astype(np.uint8), cv2.MORPH_CLOSE, kernel).astype(bool)

    # Guards. An implausibly small or large product means segmentation failed;
    # measure the central area rather than almost nothing or the whole frame.
    frac = prod.mean()
    if frac < config.PRODUCT_MIN_FRACTION or frac > config.PRODUCT_MAX_FRACTION:
        prod = _central_mask(img.shape, config.PRODUCT_FALLBACK_FRACTION)

    return prod


def _central_mask(shape, frac: float) -> np.ndarray:
    """Boolean mask, True on a centred rectangle covering `frac` of each side."""
    h, w = shape[:2]
    ch, cw = int(h * frac), int(w * frac)
    top, left = (h - ch) // 2, (w - cw) // 2
    mask = np.zeros((h, w), dtype=bool)
    mask[top:top + ch, left:left + cw] = True
    return mask


def product_bbox(img: np.ndarray) -> tuple[int, int, int, int]:
    """Bounding box (top, left, height, width) of the product region.

    Used where a criterion needs a rectangular crop rather than a mask, for
    example a published metric that expects a normal image array.
    """
    mask = product_mask(img)
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        h, w = img.shape[:2]
        return 0, 0, h, w
    top, bottom = np.where(rows)[0][[0, -1]]
    left, right = np.where(cols)[0][[0, -1]]
    # Small margin so the crop is not tight against the product edge.
    h, w = img.shape[:2]
    m = config.PRODUCT_CROP_MARGIN_PX
    top = max(0, top - m)
    left = max(0, left - m)
    bottom = min(h - 1, bottom + m)
    right = min(w - 1, right + m)
    return int(top), int(left), int(bottom - top + 1), int(right - left + 1)


def _clip01(x: float) -> float:
    return float(max(0.0, min(1.0, x)))


def _to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)


# ---------------------------------------------------------------------------
# T1 — sharpness (Laplacian variance)
# ---------------------------------------------------------------------------
def t1_sharpness(img: np.ndarray) -> float:
    """Laplacian variance over the product region only.

    Measuring the whole frame let a large flat background suppress the variance,
    so a sharp product on white scored as though it were blurred.
    """
    gray = _to_gray(img)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    mask = product_mask(img)
    vals = lap[mask]
    if vals.size == 0:
        vals = lap.ravel()
    variance = float(vals.var())
    return _clip01(variance / config.CALIBRATED_SHARPNESS_SMAX)


# ---------------------------------------------------------------------------
# T2 — exposure (mean luminance distance from ideal band)
# ---------------------------------------------------------------------------
def t2_exposure(img: np.ndarray) -> float:
    """Mean luminance of the product region against the ideal band.

    Measuring the whole frame meant a bright background pushed the mean past the
    upper tolerance, so a correctly exposed product on white scored zero. What
    matters is whether the PRODUCT is well exposed.
    """
    gray = _to_gray(img)
    mask = product_mask(img)
    vals = gray[mask]
    if vals.size == 0:
        vals = gray.ravel()
    mean = float(vals.mean())

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
_WARNED: set = set()


def _warn_abstain(metric: str, err: Exception) -> None:
    """Abstaining scores 1.0 and inflates TQS, so it must never be silent."""
    if metric not in _WARNED:
        _WARNED.add(metric)
        import logging
        logging.getLogger("pqf").warning(
            "%s is ABSTAINING (scoring 1.0) because it failed: %r. "
            "Fix the install before reporting any TQS.", metric, err)


def metric_status() -> dict:
    return {"abstaining": sorted(_WARNED)}


def t4_brisque(img: np.ndarray) -> float:
    try:
        from brisque import BRISQUE
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        with _NATIVE_METRIC_LOCK:  # libsvm model load is not thread-safe
            raw = BRISQUE().score(rgb)
    except Exception as e:
        _warn_abstain("T4 BRISQUE", e)
        # If the library/model is unavailable, abstain neutrally (documented).
        return 1.0
    return _clip01(1.0 - raw / config.T4_BRISQUE_MAX)


# ---------------------------------------------------------------------------
# T5 — PIQE (lower raw is better)
# ---------------------------------------------------------------------------
def t5_piqe(img: np.ndarray) -> float:
    """PIQE on a crop of the product region.

    PIQE penalises flat, low-texture blocks. A large uniform background is
    exactly that, so whole-frame PIQE reported degradation that was not present
    in the product. The published metric is not modified, it is simply given the
    region that matters.
    """
    try:
        import pypiqe
    except Exception as e:
        _warn_abstain("T5 PIQE", e)
        return 1.0

    top, left, h, w = product_bbox(img)
    crop = img[top:top + h, left:left + w]

    # PIQE needs a workable block size. Fall back to the full image if the crop
    # is too small to be meaningful.
    if crop.shape[0] < config.PIQE_MIN_CROP_PX or crop.shape[1] < config.PIQE_MIN_CROP_PX:
        crop = img

    try:
        gray = _to_gray(crop)
        with _NATIVE_METRIC_LOCK:  # keep native metric calls single-threaded
            out = pypiqe.piqe(gray)
        raw = out[0] if isinstance(out, tuple) else out
    except Exception as e:
        _warn_abstain("T5 PIQE", e)
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


def compute_tqs(img: np.ndarray, check_gate: bool = True) -> TechnicalResult:
    """Run the full technical engine on a standardised image.

    T0 is a rule about the ORIGINAL image, so the pipeline checks it there and
    calls this with check_gate=False. Re-checking on the standardised image
    rejected every image wider than 1.6:1 (fixed 2026-10-01).
    """
    if check_gate and not t0_compliance(img):
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
