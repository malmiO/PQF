"""
normalize.py  -  consistent background brightness across the video's shots,
without changing the product's colour (v1.1.0, 2026-10-06).

VIDEO ONLY. Applied to in-memory copies of certified photos while a video is
rendered. The certified files themselves are never touched, and nothing here runs
before scoring.

Why CIELAB. Brightening each RGB channel and clipping shifts hue and saturation
(a red goes orange or pale when one channel saturates). Here only L* (lightness)
is scaled; a* and b* (the colour) are kept as they are. Above KNEE_L the gain rolls
off smoothly towards 100 instead of clipping, so highlights keep their shape.

Fidelity guard. After the correction, the mean CIEDE2000 difference (Sharma et al.,
2005) on the PRODUCT pixels must stay at or below MAX_PRODUCT_DE00. If it does
not, the gain is reduced by binary search until it does. A gain of 1.0 is the
original, so the guard can always be met.
"""
from __future__ import annotations

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, lab2rgb, rgb2lab

from .settings import DE_SAMPLE, KNEE_L, MAX_PRODUCT_DE00, TARGET_BG_L_MIN


# --------------------------------------------------------------------------- colour
def to_lab(img_bgr: np.ndarray) -> np.ndarray:
    return rgb2lab(img_bgr[..., ::-1].astype(np.float64) / 255.0)


def from_lab(lab: np.ndarray) -> np.ndarray:
    rgb = np.clip(lab2rgb(lab), 0.0, 1.0)
    return np.round(rgb[..., ::-1] * 255.0).astype(np.uint8)


def product_mask_for(img_bgr: np.ndarray) -> np.ndarray:
    """The framework's own product finder (technical.product_mask), run on a
    reduced copy for speed and scaled back up. No new segmentation."""
    from ..pqf.technical import product_mask
    h, w = img_bgr.shape[:2]
    k = min(1.0, 1024 / max(h, w))
    small = cv2.resize(img_bgr, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA) \
        if k < 1 else img_bgr
    m = product_mask(small).astype(np.uint8)
    if k < 1:
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    return m.astype(bool)


def background_white(img_bgr: np.ndarray, product_mask: np.ndarray,
                     lab: np.ndarray | None = None) -> float:
    """Median L* of the background pixels (everything that is not product)."""
    L = (to_lab(img_bgr) if lab is None else lab)[..., 0]
    bg = L[~product_mask]
    return float(np.median(bg if bg.size else L))


# --------------------------------------------------------------------------- gain
MAX_GAIN = 1.15     # keeps the knee curve monotonic (see _lift)


def _lift(L: np.ndarray, gain: float) -> np.ndarray:
    """L* times `gain`, with a soft knee above KNEE_L.

    Brightening (gain > 1): below the knee, L * gain. Above it, the range
    [KNEE_L, 100 * gain] is rolled off onto [KNEE_L, 100] by h(s) = s / (1 + c s^2)
    (s measured from the knee in units of 100 - KNEE_L), chosen so that the slope
    is continuous at the knee, white stays white (no clipping) and gain 1.0 is
    exactly the identity. Darkening (gain <= 1) cannot clip and is a plain scale.
    """
    y = L * gain
    if gain <= 1.0:
        return y
    span = 100.0 - KNEE_L
    s_max = (100.0 * gain - KNEE_L) / span
    c = (s_max - 1.0) / (s_max * s_max)
    hi = y > KNEE_L
    s = (y[hi] - KNEE_L) / span
    y[hi] = KNEE_L + span * s / (1.0 + c * s * s)
    return y


def apply_gain(lab: np.ndarray, gain: float) -> np.ndarray:
    """Scale L* by `gain` (soft knee above KNEE_L); a* and b* unchanged."""
    out = lab.copy()
    out[..., 0] = np.clip(_lift(lab[..., 0], gain), 0.0, 100.0)
    return out


def gain_for(bg_l: float, target_l: float) -> float:
    """The L* gain that brings a background of `bg_l` to `target_l`, through the
    soft knee (found by bisection; the lift is monotonic in the gain)."""
    if bg_l <= 0 or abs(target_l - bg_l) < 1e-6:
        return 1.0
    if target_l < bg_l:
        return target_l / bg_l
    lo, hi = 1.0, MAX_GAIN
    if _lift(np.array([bg_l]), hi)[0] <= target_l:
        return hi
    for _ in range(40):
        mid = (lo + hi) / 2
        if _lift(np.array([bg_l]), mid)[0] < target_l:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _sample(mask: np.ndarray) -> np.ndarray:
    idx = np.flatnonzero(mask.ravel())
    if idx.size > DE_SAMPLE:
        idx = idx[np.linspace(0, idx.size - 1, DE_SAMPLE).astype(int)]
    return idx


def product_de00(product_lab: np.ndarray, gain: float) -> float:
    """Mean CIEDE2000 on product pixels (an N x 3 Lab sample) between the
    original and the copy corrected with `gain`."""
    if product_lab.size == 0:
        return 0.0
    return float(np.mean(deltaE_ciede2000(product_lab, apply_gain(product_lab, gain))))


def correct(img_bgr: np.ndarray, mask: np.ndarray, target_l: float) -> tuple:
    """Correct one image towards `target_l`. Returns (corrected_bgr, record)."""
    lab = to_lab(img_bgr)
    before = background_white(img_bgr, mask, lab)
    want = gain_for(before, target_l)
    sample = lab.reshape(-1, 3)[_sample(mask)]
    gain, de = want, product_de00(sample, want)
    guarded = False
    if de > MAX_PRODUCT_DE00:
        guarded = True
        lo, hi = 1.0, want                   # 1.0 always passes (no change)
        for _ in range(14):
            mid = (lo + hi) / 2
            if product_de00(sample, mid) <= MAX_PRODUCT_DE00:
                lo = mid
            else:
                hi = mid
        gain = lo
        de = product_de00(sample, gain)
    if de > MAX_PRODUCT_DE00:                # should never happen
        return img_bgr, {"bg_l_before": round(before, 2), "bg_l_after": round(before, 2),
                         "gain_wanted": round(want, 4), "gain": 1.0, "product_de00": 0.0,
                         "guard_limited": True, "original_used": True}
    corrected_lab = apply_gain(lab, gain)
    out = from_lab(corrected_lab)
    after = float(np.median(corrected_lab[..., 0][~mask])) if (~mask).any() else before
    return out, {"bg_l_before": round(before, 2), "bg_l_after": round(after, 2),
                 "gain_wanted": round(want, 4), "gain": round(gain, 4),
                 "product_de00": round(de, 3), "guard_limited": guarded,
                 "original_used": False}


def match_set(images: list, masks: list | None = None, main_index: int = 0) -> tuple:
    """Bring every image's background to one lightness.

    Target: the MAIN shot's background L*, but at least TARGET_BG_L_MIN. Returns
    (corrected_images, records, target). records[i] holds bg L* before/after, the
    gain wanted and used, the product CIEDE2000, and whether the guard limited it.
    """
    if masks is None:
        masks = [product_mask_for(im) for im in images]
    main_bg = background_white(images[main_index], masks[main_index])
    target = max(main_bg, TARGET_BG_L_MIN)
    out, records = [], []
    for im, m in zip(images, masks):
        c, r = correct(im, m, target)
        out.append(c)
        records.append(r)
    return out, records, round(target, 2)
