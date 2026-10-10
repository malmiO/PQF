"""
ai_enhancement.py  -  does phone-style automatic enhancement change PQF's verdicts?
(robustness / threat-to-validity experiment, 2026-10-07)

WHY. Recent phone camera apps apply automatic processing after capture: detail
sharpening, noise reduction and skin smoothing, "vivid" saturation, multi-frame HDR
tone mapping, brightening, scene-dependent white balance, AI super-resolution
(Samsung's own description of Scene Optimizer: a "deep learning-based AI detail
enhancement engine"; Masud et al. 2026 on generative processing inside the camera
pipeline). A quality framework that measures sharpness, exposure and colour can be
FOOLED by such processing (a blurred photo sharpened afterwards may pass T1) or can
miss what it changed (a saturation boost alters the product's true colour while the
background stays neutral, so T6 sees no cast).

METHOD. Each photo is processed by simulated enhancement operators at three
strengths. For every operator and strength we report, against the original:
  * mean change in each criterion score (T1-T6),
  * verdict flips at the specification thresholds: fail->pass (MASKING: enhancement
    hides a real fault) and pass->fail,
  * colour change of the PRODUCT region, CIEDE2000 mean delta E (perceptible above
    about 2.3, Sharma et al. 2005), which no PQF criterion measures.
The operators are simulations of the documented processing classes, not any vendor's
algorithm; real-device confirmation is the paired on-device test in the protocol.

Usage:
  python research/evaluation/ai_enhancement.py --images <folder> [<folder> ...] --out <dir>
Filenames containing V-BLUR / V_BLUR are reported as a separate "blurred" group.
"""
from __future__ import annotations

import argparse
import statistics as st
from pathlib import Path

import cv2
import numpy as np

from evalcommon import SPEC_PASS, TECH, LABEL, write_csv, save_json, environment, platform_format

LEVELS = (1, 2, 3)


def _unsharp(img, amount):
    blur = cv2.GaussianBlur(img, (0, 0), 2.0)
    return cv2.addWeighted(img, 1 + amount, blur, -amount, 0)


def _sat(img, k):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[..., 1] = np.clip(hsv[..., 1] * k, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)


def _clahe(img, clip):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _gamma(img, g):
    lut = np.clip(((np.arange(256) / 255.0) ** g) * 255, 0, 255).astype(np.uint8)
    return cv2.LUT(img, lut)


def _warm(img, shift):
    out = img.astype(np.int16)
    out[..., 2] += shift          # red up
    out[..., 0] -= shift          # blue down
    return np.clip(out, 0, 255).astype(np.uint8)


def _superres(img, f):
    h, w = img.shape[:2]
    small = cv2.resize(img, (int(w / f), int(h / f)), interpolation=cv2.INTER_AREA)
    up = cv2.resize(small, (w, h), interpolation=cv2.INTER_LANCZOS4)
    return _unsharp(up, 1.0)


OPERATORS = {
    # name: (description, {level: function})
    "sharpen":   ("Detail sharpening (unsharp mask)",
                  {1: lambda i: _unsharp(i, 0.5), 2: lambda i: _unsharp(i, 1.0), 3: lambda i: _unsharp(i, 2.0)}),
    "smooth":    ("Noise reduction / skin smoothing (bilateral)",
                  {1: lambda i: cv2.bilateralFilter(i, 7, 30, 7), 2: lambda i: cv2.bilateralFilter(i, 9, 60, 9),
                   3: lambda i: cv2.bilateralFilter(i, 11, 90, 11)}),
    "vivid":     ("Saturation boost ('vivid' / scene optimiser)",
                  {1: lambda i: _sat(i, 1.15), 2: lambda i: _sat(i, 1.30), 3: lambda i: _sat(i, 1.50)}),
    "hdr":       ("Local tone mapping (HDR-like, CLAHE)",
                  {1: lambda i: _clahe(i, 1.5), 2: lambda i: _clahe(i, 2.5), 3: lambda i: _clahe(i, 4.0)}),
    "brighten":  ("Auto brightening (gamma)",
                  {1: lambda i: _gamma(i, 0.9), 2: lambda i: _gamma(i, 0.8), 3: lambda i: _gamma(i, 0.65)}),
    "warm":      ("Scene white-balance shift (warmer)",
                  {1: lambda i: _warm(i, 6), 2: lambda i: _warm(i, 12), 3: lambda i: _warm(i, 20)}),
    "superres":  ("Upscaling + sharpening (super-resolution-like)",
                  {1: lambda i: _superres(i, 1.5), 2: lambda i: _superres(i, 2.0), 3: lambda i: _superres(i, 3.0)}),
}


def _scores(img):
    from backend.pqf.technical import compute_tqs
    r = compute_tqs(img, check_gate=False)
    return {k: float(v) for k, v in r.scores.items()}, float(r.tqs)


def _delta_e_product(a, b):
    from skimage.color import rgb2lab, deltaE_ciede2000
    from backend.pqf.technical import product_mask
    m = product_mask(a) > 0
    la = rgb2lab(cv2.cvtColor(a, cv2.COLOR_BGR2RGB)[m][None].astype(np.float64) / 255.0)
    lb = rgb2lab(cv2.cvtColor(b, cv2.COLOR_BGR2RGB)[m][None].astype(np.float64) / 255.0)
    return float(np.mean(deltaE_ciede2000(la, lb)))


def run(paths, out: Path):
    from backend.pqf.preprocess import standardise
    rows = []
    for n, p in enumerate(paths, 1):
        base = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if base is None:
            continue
        group = "blurred" if ("BLUR" in p.name.upper()) else "unblurred"
        img = standardise(platform_format(base))   # what the app scores
        s0, t0 = _scores(img)
        for op, (_, fns) in OPERATORS.items():
            for lv in LEVELS:
                e = fns[lv](img)
                s1, t1 = _scores(e)
                row = {"image": p.name, "group": group, "operator": op, "level": lv,
                       "tqs0": round(t0, 4), "tqs1": round(t1, 4),
                       "product_deltaE": round(_delta_e_product(img, e), 3)}
                for c in TECH:
                    row[f"{c}0"], row[f"{c}1"] = round(s0[c], 4), round(s1[c], 4)
                rows.append(row)
        print(f"\r{n}/{len(paths)}", end="", flush=True)
    print()
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "per_image.csv", rows)

    summary = []
    for op, (desc, _) in OPERATORS.items():
        for lv in LEVELS:
            for group in ("all", "blurred"):
                rs = [r for r in rows if r["operator"] == op and r["level"] == lv
                      and (group == "all" or r["group"] == group)]
                if not rs:
                    continue
                item = {"operator": op, "description": desc, "level": lv, "group": group,
                        "n": len(rs),
                        "median_product_deltaE": round(st.median(r["product_deltaE"] for r in rs), 2),
                        "share_deltaE_over_2_3": round(sum(r["product_deltaE"] > 2.3 for r in rs) / len(rs), 3),
                        "mean_delta_tqs": round(st.mean(r["tqs1"] - r["tqs0"] for r in rs), 4)}
                for c in TECH:
                    thr = SPEC_PASS[c]
                    item[f"d_{c}"] = round(st.mean(r[f"{c}1"] - r[f"{c}0"] for r in rs), 4)
                    item[f"masked_{c}"] = sum(r[f"{c}0"] < thr <= r[f"{c}1"] for r in rs)
                    item[f"broken_{c}"] = sum(r[f"{c}1"] < thr <= r[f"{c}0"] for r in rs)
                    item[f"failing_before_{c}"] = sum(r[f"{c}0"] < thr for r in rs)
                summary.append(item)
    save_json(out / "summary.json", {"summary": summary, "n_images": len(paths),
                                     "environment": environment()})
    L = ["# Phone-style enhancement vs PQF verdicts", "",
         f"{len(paths)} photos; each operator at 3 strengths. 'Masked' = a criterion that FAILED "
         "on the original PASSES after enhancement; 'Broken' = the reverse. Product colour change "
         "is CIEDE2000 delta E in the product region (above 2.3 is perceptible).", "",
         "| Operator | Level | Group | n | T1 masked / failing | T1 mean change | T2 masked | "
         "T6 mean change | Product colour change, median dE | Share dE > 2.3 |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for i in summary:
        L.append(f"| {i['description']} | {i['level']} | {i['group']} | {i['n']} | "
                 f"{i['masked_sharpness']} / {i['failing_before_sharpness']} | {i['d_sharpness']:+.3f} | "
                 f"{i['masked_exposure']} | {i['d_colorcast']:+.3f} | {i['median_product_deltaE']} | "
                 f"{100*i['share_deltaE_over_2_3']:.0f}% |")
    (out / "summary.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", nargs="+", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    paths = sorted(p for d in a.images for p in (d.rglob("*") if d.is_dir() else [d])
                   if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    run(paths, a.out)
    print((a.out / "summary.md").read_text())
