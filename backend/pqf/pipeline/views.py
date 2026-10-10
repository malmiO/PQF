"""
views.py  -  where the product is, and how different two views of it are (2026-10-06).

Two small, deterministic helpers used AFTER scoring. Neither changes any criterion,
weight or threshold of the framework.

product_box(img)
    The product's bounding box. Built on the framework's own product finder
    (technical.product_mask), then keeps the main connected region near the centre
    plus small parts close to it (a keychain's clasp). Lightbox corners and shadows
    that touch the frame edge are ignored. Used to frame the product in the video
    and to build the view signature.

view_signature(img) / view_distance(a, b)
    How different two photographs of the same product look, 0 (same view) to about
    0.7 (clearly different side or tilt). Half a perceptual hash of the product's
    appearance (background whitened), half the difference in its outline
    (1 - IoU of the silhouettes), both measured on a square crop around the product,
    so the SAME view taken closer or further away still counts as the same view.

WHY (the selection rule it serves). Fan et al. (KDD 2022) select a product image
sequence under the rule that two images should not present the product from
similar viewing angles, and the PQF gate itself (spec v1.3, Section 7) requires
"at least two angle shots with DISTINCT angles". Until now the code counted angle
shots but never checked that they differed. Measured on 18 real lightbox photos
of three keychains (J6+, 2026-10-05): repeated front views scored 0.03 to 0.08;
clearly different tilts or sides 0.55 to 0.68. NEAR_DUPLICATE = 0.15 sits in the
gap with margin on both sides.
"""
from __future__ import annotations

import numpy as np

NEAR_DUPLICATE = 0.15     # below this, two photos show the same view
SIG_SIZE = 32             # perceptual hash input size
SIL_SIZE = 24             # silhouette grid
VIEW_SMOOTH_SIGMA = 3.0   # px, smoothing of the background difference (signature only)
VIEW_DIFF_LEVEL = 24      # grey levels from the background = product (signature only)
VIEW_MIN_REGION = 0.002   # share of the frame a region needs to count (signature only)


def _mask(img):
    from ..technical import product_mask
    return product_mask(img) > 0


def product_box(img, mask=None) -> tuple:
    """(x0, y0, x1, y1) of the product in `img` pixel coordinates."""
    import cv2
    h, w = img.shape[:2]
    m = (_mask(img) if mask is None else mask).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, _, st, cen = cv2.connectedComponentsWithStats(m, 8)

    def touches(x, y, bw, bh):
        return x == 0 or y == 0 or x + bw >= w or y + bh >= h

    best, best_s = None, -1.0
    for i in range(1, n):
        x, y, bw, bh, a = st[i]
        if a < 0.001 * h * w:
            continue
        cx, cy = cen[i]
        off = np.hypot((cx - w / 2) / w, (cy - h / 2) / h)
        s = a * (1 - off) * (0.25 if touches(x, y, bw, bh) else 1.0)
        if s > best_s:
            best, best_s = i, s
    if best is None:
        return (int(w * 0.25), int(h * 0.25), int(w * 0.75), int(h * 0.75))
    x, y, bw, bh, _ = st[best]
    x0, y0, x1, y1 = x, y, x + bw, y + bh
    reach = 0.25 * max(bw, bh)
    for i in range(1, n):
        if i == best:
            continue
        x, y, bw, bh, a = st[i]
        if a < 0.0003 * h * w or touches(x, y, bw, bh):
            continue
        if x >= x0 - reach and y >= y0 - reach and x + bw <= x1 + reach and y + bh <= y1 + reach:
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x + bw), max(y1, y + bh)
    return (int(x0), int(y0), int(x1), int(y1))


def _view_mask_and_box(img):
    """Product mask and box FOR THE VIEW SIGNATURE ONLY (v1.4.0, 2026-10-09).

    The framework's product_mask thresholds a hard pixel difference, which is right for
    measuring the criteria but flips at faint edges when the same photo is re-encoded:
    on 60 real lightbox photos 9 re-encoded copies were judged a "different view" (white
    card, pale sticker sheets, pairs of earrings boxed one at a time). Here the difference
    from the estimated background is smoothed first (Gaussian sigma 3 px) and the box
    covers every significant region that does not touch the frame, so a pair or a card
    is framed whole. Criteria, product_box (video framing) and NEAR_DUPLICATE unchanged.
    """
    import cv2
    from .. import config
    h, w = img.shape[:2]
    b = max(2, int(min(h, w) * config.T3_BORDER_FRACTION))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                             img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0).astype(np.float32)
    diff = np.abs(img.astype(np.float32) - bg).max(axis=2)
    m = cv2.GaussianBlur(diff, (0, 0), VIEW_SMOOTH_SIGMA) > VIEW_DIFF_LEVEL
    n, _, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    keep = [i for i in range(1, n) if st[i][4] >= VIEW_MIN_REGION * h * w]
    inner = [i for i in keep if not (st[i][0] == 0 or st[i][1] == 0 or
                                     st[i][0] + st[i][2] >= w or st[i][1] + st[i][3] >= h)]
    use = inner or keep
    if not use:
        return m, (w // 4, h // 4, 3 * w // 4, 3 * h // 4)
    x0 = min(st[i][0] for i in use); y0 = min(st[i][1] for i in use)
    x1 = max(st[i][0] + st[i][2] for i in use); y1 = max(st[i][1] + st[i][3] for i in use)
    return m, (int(x0), int(y0), int(x1), int(y1))


def view_signature(img) -> dict:
    """A compact description of the view, stored on the image's decision."""
    import cv2
    m, (x0, y0, x1, y1) = _view_mask_and_box(img)
    s = max(x1 - x0, y1 - y0, 8)
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    g[~m] = 255.0                                    # appearance of the product only
    G = np.pad(g, s, constant_values=255.0)
    M = np.pad(m, s)
    ty, tx = cy - s // 2 + s, cx - s // 2 + s
    gc, mc = G[ty:ty + s, tx:tx + s], M[ty:ty + s, tx:tx + s]
    d = cv2.dct(cv2.resize(gc, (SIG_SIZE, SIG_SIZE), interpolation=cv2.INTER_AREA))
    d = d[:8, :8].flatten()[1:]
    sil = cv2.resize(mc.astype(np.uint8) * 255, (SIL_SIZE, SIL_SIZE),
                     interpolation=cv2.INTER_AREA) > 127
    return {"hash": (d > np.median(d)), "sil": sil}


def view_distance(a, b) -> float:
    """0 = same view. Missing signatures count as different (1.0), so tests and
    callers without pixels keep the previous behaviour."""
    if not a or not b:
        return 1.0
    ham = float(np.mean(a["hash"] != b["hash"]))
    union = float((a["sil"] | b["sil"]).sum())
    iou = float((a["sil"] & b["sil"]).sum()) / union if union else 0.0
    return round(0.5 * ham + 0.5 * (1.0 - iou), 3)
