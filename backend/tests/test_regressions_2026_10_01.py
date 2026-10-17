"""Regression tests for the three faults found on 2026-10-01."""
import os
import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"

from backend.pqf.pipeline import score_image
from backend.pqf.technical import t0_compliance


def _product(w, h):
    img = np.full((h, w, 3), 245, np.uint8)
    cx, cy, r = w // 2, h // 2, min(w, h) // 5
    cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), (40, 90, 160), -1)
    cv2.putText(img, "LABEL", (cx - r + 10, cy), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_wide_16_9_image_is_not_rejected_by_t0():
    # 1920x1080 passes T0 on the original. Standardising to 1024 px gives a
    # 576 px short side, and the old internal re-check rejected it.
    d = score_image(_product(1920, 1080))
    assert d.reason != "t0_platform_spec_fail"
    assert d.tqs > 0


def test_platform_format_makes_upright_phone_photos_compliant():
    from backend.api.main import _platform_format
    for w, h in [(720, 1280), (3000, 4000), (1080, 1920)]:
        out = _platform_format(_product(w, h))
        img = cv2.imdecode(np.frombuffer(out, np.uint8), cv2.IMREAD_COLOR)
        assert t0_compliance(img), (w, h, img.shape)


def test_platform_format_leaves_compliant_images_byte_identical():
    from backend.api.main import _platform_format
    for w, h in [(1024, 1024), (1080, 1350), (1920, 1080)]:
        b = _product(w, h)
        assert _platform_format(b) == b
