"""Pre-processing: standardise every image before any metric is computed."""
from __future__ import annotations
import cv2
import numpy as np
from . import config


def load_image(path: str) -> np.ndarray:
    """Load an image as BGR (OpenCV convention). Raises on failure."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return img


def standardise(img: np.ndarray, longest_side: int = config.WORKING_LONGEST_SIDE) -> np.ndarray:
    """Resize so the longest side == longest_side, preserving aspect ratio.

    Thresholds (e.g. sharpness S_max) are only meaningful at this working size,
    so calibration and validation images are all processed identically.
    """
    h, w = img.shape[:2]
    scale = longest_side / max(h, w)
    if scale == 1.0:
        return img.copy()
    new_w, new_h = int(round(w * scale)), int(round(h * scale))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(img, (new_w, new_h), interpolation=interp)


def to_gray(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
