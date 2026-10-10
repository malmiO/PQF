"""View signature robustness (v1.4.0, 2026-10-09).

Found on 60 real lightbox photos: 9 JPEG re-encodes of the SAME photo were judged a
different view, for low-contrast products (white card, pale sheets) and pairs of items.
"""
import os

import cv2
import numpy as np

os.environ.setdefault("PQF_SEMANTIC_MOCK", "1")

from backend.pqf.pipeline.views import (view_signature, view_distance, NEAR_DUPLICATE,
                                        _view_mask_and_box)


def _lightbox(bg=200):
    rng = np.random.default_rng(7)
    img = np.full((1024, 819, 3), bg, np.float32)
    img += np.linspace(-6, 6, 819)[None, :, None]               # uneven light box
    img += rng.normal(0, 1.5, img.shape)                        # sensor noise
    return img


def _card_with_earrings():
    """A white card on a grey light box carrying a pair of textured earrings (the
    real failure: 20261009_000746 and _001945)."""
    img = _lightbox()
    cv2.rectangle(img, (230, 300), (590, 720), (238, 237, 234), -1)   # white card
    cv2.putText(img, "Pearl", (300, 660), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (90, 90, 90), 3)
    for cx, r in ((330, 40), (495, 34)):                               # a PAIR, not identical
        cv2.circle(img, (cx, 470), r, (40, 150, 200), -1)
        cv2.ellipse(img, (cx - 8, 460), (r // 2, r // 3), 30, 0, 360, (250, 250, 250), -1)
        cv2.line(img, (cx, 470 - r), (cx, 380), (60, 60, 60), 4)        # hook
    return np.clip(img, 0, 255).astype(np.uint8)


def _jpeg(img, q=75):
    return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], 1)


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
REAL = ["lightbox_20261009_000746.jpg",    # earrings on a white card
        "lightbox_20261009_001033.jpg",    # pale sticker sheet (old code: 0.73)
        "lightbox_20261009_001945.jpg"]    # charm on a printed card


def test_reencoded_real_lightbox_photos_keep_the_same_view():
    """Real photos (researcher's light box, 2026-10-09, standardised to 1024 px)."""
    for name in REAL:
        img = cv2.imread(os.path.join(FIXTURES, name))
        assert img is not None, name
        d = view_distance(view_signature(img), view_signature(_jpeg(img)))
        assert d < 0.05, (name, d)


def test_box_covers_both_items_of_a_pair():
    _, (x0, y0, x1, y1) = _view_mask_and_box(_card_with_earrings())
    assert x0 <= 295 and x1 >= 525


def test_turned_product_is_still_a_different_view():
    a = _card_with_earrings()
    b = cv2.rotate(a, cv2.ROTATE_90_CLOCKWISE)
    b = cv2.resize(b, (a.shape[1], a.shape[0]))
    assert view_distance(view_signature(a), view_signature(b)) >= NEAR_DUPLICATE
