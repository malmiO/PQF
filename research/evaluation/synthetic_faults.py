"""
synthetic_faults.py  -  controlled, known faults made from good ABO catalogue images
(O1 construct validity, 2026-10-08).

WHY. The standard way to build an image-quality test set is to take pristine reference
images and add each distortion at known strengths (e.g. LIVE, TID2013, KADID-10k). That
gives faults whose type and strength are known BY CONSTRUCTION, on the SAME image as the
clean original, so a criterion can be tested without the source confound of comparing
studio photos with room photos. It also gives T4, T5 and T6 their first constructed faults.

WHAT. For every ABO image (the frozen 62, or any folder of good catalogue images):

| fault       | target criterion | levels (pre-registered, 2026-10-08)                          |
|-------------|------------------|--------------------------------------------------------------|
| BLUR        | T1 sharpness     | Gaussian sigma 1.5 / 3.0 / 5.0 px at a 1024 px longest side   |
| DARK        | T2 exposure      | pixel values x 0.55 / 0.40 / 0.25                             |
| BRIGHT      | T2 exposure      | product region brightened: x 1.5 / 1.9 / 2.4 (clipped)        |
| GREYBG      | T3 background    | white background replaced by flat grey 205 / 185 / 160        |
| CLUTTER     | T3 background    | white background replaced by a random textured scene          |
| CAST        | T6 colour cast   | warm tint (R x1.06/1.10/1.16, B x0.94/0.90/0.84)              |
| NOISE       | T4 BRISQUE       | Gaussian noise sd 8 / 16 / 28                                 |
| JPEG        | T5 PIQE          | JPEG re-encode quality 30 / 15 / 6                            |
| OFFCENTRE   | S1 centring      | product moved by 22 / 32 / 40 % of the width (white fill)     |
"Level 3" is the strength at which a capture is clearly unusable for a listing; the
pre-registered expectation is that the target criterion flags level 3 in most images, and
fewer at levels 1-2. Strengths were set by eye on ABO CALIBRATION images only.

The background is found INDEPENDENTLY of the framework: near-white pixels (all channels
>= 240) connected to the image border (flood fill), so the test does not reuse the
framework's own product finder.

Each output keeps its source's split (calibration / holdout), so the holdout is never used
for tuning. Output: <out>/<fault>_L<level>/<source>.png (lossless) + manifest.csv with
relpath, source, category, split, fault, level, target, params. o1_detection.py reads it
with --manifest.

Usage:
  python research/evaluation/synthetic_faults.py --data <dataset root> --split <split_v1.csv> --out <dir>
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np

from evalcommon import discover, apply_split, write_csv

LEVELS = (1, 2, 3)
TARGET = {"BLUR": "sharpness", "DARK": "exposure", "BRIGHT": "exposure",
          "GREYBG": "background", "CLUTTER": "background", "CAST": "colorcast",
          "NOISE": "brisque", "JPEG": "piqe", "OFFCENTRE": "subject_centering"}


def background_mask(img: np.ndarray) -> np.ndarray:
    """Near-white pixels connected to the border (independent of PQF's finder)."""
    white = (img.min(axis=2) >= 240).astype(np.uint8)
    h, w = white.shape
    ff = white.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for x, y in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1),
                 (w // 2, 0), (w // 2, h - 1), (0, h // 2), (w - 1, h // 2)]:
        if ff[y, x] == 1:
            cv2.floodFill(ff, mask, (x, y), 2)
    return ff == 2


def _scale(img):
    return max(img.shape[:2]) / 1024.0


def blur(img, lv, rng):
    s = {1: 1.5, 2: 3.0, 3: 5.0}[lv] * _scale(img)
    return cv2.GaussianBlur(img, (0, 0), s), f"sigma={s:.2f}"


def dark(img, lv, rng):
    k = {1: 0.55, 2: 0.40, 3: 0.25}[lv]
    return np.clip(img.astype(np.float32) * k, 0, 255).astype(np.uint8), f"x{k}"


def bright(img, lv, rng):
    k = {1: 1.5, 2: 1.9, 3: 2.4}[lv]
    bg = background_mask(img)
    out = img.astype(np.float32)
    out[~bg] = out[~bg] * k
    return np.clip(out, 0, 255).astype(np.uint8), f"product x{k}"


def greybg(img, lv, rng):
    g = {1: 205, 2: 185, 3: 160}[lv]
    bg = background_mask(img)
    out = img.copy()
    out[bg] = g
    return out, f"grey={g}"


def clutter(img, lv, rng):
    h, w = img.shape[:2]
    bg = background_mask(img)
    scene = np.zeros((h, w, 3), np.uint8)
    n = {1: 6, 2: 14, 3: 30}[lv]
    scene[:] = rng.randint(120, 200)
    for _ in range(n):
        c = tuple(int(rng.randint(30, 230)) for _ in range(3))
        x, y = rng.randint(0, w), rng.randint(0, h)
        r = rng.randint(max(4, w // 30), max(8, w // 8))
        cv2.circle(scene, (x, y), r, c, -1) if rng.random() < 0.5 else \
            cv2.rectangle(scene, (x, y), (x + r * 2, y + r), c, -1)
    scene = cv2.GaussianBlur(scene, (0, 0), 2 * _scale(img))
    out = img.copy()
    out[bg] = scene[bg]
    return out, f"shapes={n}"


def cast(img, lv, rng):
    r, b = {1: (1.06, 0.94), 2: (1.10, 0.90), 3: (1.16, 0.84)}[lv]
    out = img.astype(np.float32)
    out[..., 2] *= r
    out[..., 0] *= b
    return np.clip(out, 0, 255).astype(np.uint8), f"R x{r}, B x{b}"


def noise(img, lv, rng):
    sd = {1: 8, 2: 16, 3: 28}[lv]
    n = np.random.default_rng(rng.randint(0, 2**31)).normal(0, sd, img.shape)
    return np.clip(img.astype(np.float32) + n, 0, 255).astype(np.uint8), f"sd={sd}"


def jpeg(img, lv, rng):
    q = {1: 30, 2: 15, 3: 6}[lv]
    return cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1], 1), f"q={q}"


def offcentre(img, lv, rng):
    f = {1: 0.22, 2: 0.32, 3: 0.40}[lv]
    h, w = img.shape[:2]
    dx = int(w * f) * (1 if rng.random() < 0.5 else -1)
    M = np.float32([[1, 0, dx], [0, 1, 0]])
    return cv2.warpAffine(img, M, (w, h), borderValue=(255, 255, 255)), f"shift={dx}px"


FAULTS = {"BLUR": blur, "DARK": dark, "BRIGHT": bright, "GREYBG": greybg,
          "CLUTTER": clutter, "CAST": cast, "NOISE": noise, "JPEG": jpeg,
          "OFFCENTRE": offcentre}


def make(rows: list, out: Path, seed: int = 20261008) -> list:
    manifest = []
    for r in rows:
        img = cv2.imread(r["path"], cv2.IMREAD_COLOR)
        if img is None:
            continue
        stem = Path(r["path"]).stem
        for fault, fn in FAULTS.items():
            for lv in LEVELS:
                rng = random.Random(f"{seed}-{stem}-{fault}-{lv}")
                im, params = fn(img, lv, rng)
                rel = Path(f"{fault}_L{lv}") / f"{r['category']}__{stem}.png"
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(out / rel), im)
                manifest.append({"relpath": str(rel), "source": r["relpath"],
                                 "category": r["category"], "split": r.get("split", ""),
                                 "fault": fault, "level": lv, "target": TARGET[fault],
                                 "params": params, "seed": seed})
    write_csv(out / "manifest.csv", manifest)
    return manifest


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--split", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    rows = []
    for subset in ("calibration", "holdout"):
        part = [dict(r, split=subset) for r in apply_split(discover(a.data), a.split, subset)
                if r["source"] == "ABO"]
        rows += part
    m = make(rows, a.out)
    print(f"{len(rows)} ABO sources -> {len(m)} faulty images in {a.out}")
