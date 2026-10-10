"""
device_qualification.py  -  is this phone, in this environment, fit for PQF?
Device Qualification (DQ) and Environment Qualification (EQ) tests (2026-10-07).

A device is CERTIFIED for PQF when it passes DQ1-DQ6 in an environment that passes
EQ1-EQ4. Acceptance limits and their sources are in LIMITS below and in
Device_and_Environment_Specification (research documentation).

Folder layout, one folder per device (all photos taken IN THE PQF APP unless noted):
  <device>/device_report.json   written by the app's "Device check" screen
  <device>/repeat/              5 captures of the reference product, phone on the stand,
                                nothing moved between shots
  <device>/empty/               1-3 captures of the EMPTY light box (environment test)
  <device>/inapp/ + <device>/default_camera/   OPTIONAL: the same scene taken in the PQF
                                app and in the phone's own camera app with its AI scene
                                optimisation ON; files paired by sorted order
  <device>/environment.json     REQUIRED for EQ4: {"lux": 1450, "lux_method": "...", "cct_k": 6000}

Usage: python research/evaluation/device_qualification.py --devices <root> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

import cv2
import numpy as np

from evalcommon import SPEC_PASS, TECH, save_json, write_csv, platform_format

LIMITS = {
    "min_api": 29,                 # Android 10: lowest version tested (Samsung J6+)
    "repeats": 5,                  # DQ4/DQ5 need exactly five identical captures
    "min_ev": 2.0,                 # exposure compensation range +/-2 EV (brightness assist)
    "min_photo": (1080, 1350),     # 4:5 photo; >= Meta 1080 px width, >= GS1 900 px web minimum
    "tqs_range": 0.05,             # repeatability across 5 identical captures
    "criterion_range": 0.10,
    "repeat_pass_share": 0.80,     # T1,T2,T3,T6 pass in >= 4 of 5 reference captures
    "guidance_median_ms": 1000,    # live guidance round trip on the phone
    "bg_luminance": 220,           # EQ1: T3 white basis (GS1: background RGB 255)
    "uniformity_cv": 0.05,         # EQ2: FADGI 2023 lightness uniformity, lowest tier < 5 %
    "colorcast": 0.60,             # EQ3: T6 pass threshold
    "lux": 1000,                   # EQ4: IEEE 1858 CPIQ bright condition (1000 lux)
}
IMG = {".jpg", ".jpeg", ".png"}


def _imgs(d: Path):
    return sorted(p for p in d.glob("*") if p.suffix.lower() in IMG) if d.exists() else []


def _tech(img):
    from backend.pqf.preprocess import standardise
    from backend.pqf.technical import compute_tqs
    r = compute_tqs(standardise(platform_format(img)), check_gate=False)
    return r.scores, r.tqs


def check(name, ok, measured, limit, note=""):
    status = "PASS" if ok is True else "FAIL" if ok is False else "NOT MEASURED"
    return {"test": name, "status": status, "measured": measured, "limit": limit, "note": note}


def environment_tests(dev: Path):
    out = []
    empties = _imgs(dev / "empty")
    if not empties:
        return [check(n, None, "-", l) for n, l in (
            ("EQ1 Background luminance", f">= {LIMITS['bg_luminance']}"),
            ("EQ2 Lighting uniformity (CV of L*)", f"<= {LIMITS['uniformity_cv']}"),
            ("EQ3 Colour cast (T6)", f">= {LIMITS['colorcast']}"))] + [lux_test(dev)]
    lum, cv, cast = [], [], []
    from backend.pqf.technical import t6_colorcast
    from backend.pqf.preprocess import standardise
    for p in empties:
        img = standardise(platform_format(cv2.imread(str(p))))
        L = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32) * 100 / 255
        h, w = L.shape
        cells = [L[i * h // 8:(i + 1) * h // 8, j * w // 8:(j + 1) * w // 8].mean()
                 for i in range(8) for j in range(8)]
        lum.append(float(np.median(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))))
        cv.append(float(np.std(cells) / np.mean(cells)))
        cast.append(float(t6_colorcast(img)))
    out.append(check("EQ1 Background luminance", min(lum) >= LIMITS["bg_luminance"],
                     round(min(lum), 1), f">= {LIMITS['bg_luminance']}",
                     "median grey level of the empty box, after the app's brightness assist"))
    out.append(check("EQ2 Lighting uniformity (CV of L*)", max(cv) <= LIMITS["uniformity_cv"],
                     round(max(cv), 3), f"<= {LIMITS['uniformity_cv']}", "8x8 grid over the frame"))
    out.append(check("EQ3 Colour cast (T6)", min(cast) >= LIMITS["colorcast"],
                     round(min(cast), 3), f">= {LIMITS['colorcast']}"))
    out.append(lux_test(dev))
    return out


def lux_test(dev: Path):
    f = dev / "environment.json"
    if not f.exists():
        return check("EQ4 Illuminance at the product", None, "-", f">= {LIMITS['lux']} lux")
    e = json.loads(f.read_text())
    return check("EQ4 Illuminance at the product", e.get("lux", 0) >= LIMITS["lux"],
                 e.get("lux"), f">= {LIMITS['lux']} lux", e.get("lux_method", ""))


def device_tests(dev: Path):
    out, rep = [], {}
    f = dev / "device_report.json"
    if f.exists():
        rep = json.loads(f.read_text())
    api = rep.get("android_api")
    out.append(check("DQ1 Android version", api >= LIMITS["min_api"] if api else None,
                     f"API {api}" if api else "-", f"API >= {LIMITS['min_api']} (Android 10)"))
    lvl = rep.get("camera_hardware_level")         # recorded, not a pass condition
    ev = rep.get("exposure_offset_range")          # [min, max] in EV
    af = rep.get("autofocus")
    ok2 = None if (af is None or ev is None) else (bool(af) and ev[0] <= -LIMITS["min_ev"]
                                                   and ev[1] >= LIMITS["min_ev"])
    out.append(check("DQ2 Camera controls", ok2, f"AF {af}, EV {ev} (Camera2 level {lvl})",
                     "autofocus and exposure compensation at least -2..+2 EV",
                     "the app uses only these two controls; any Camera2 level that offers them passes"))
    reps = _imgs(dev / "repeat")
    if reps and len(reps) != LIMITS["repeats"]:
        out += [check("DQ3 Photo resolution", None, f"{len(reps)} photos", "exactly 5 repeat photos"),
                check("DQ4 Repeatability", None, f"{len(reps)} photos", "exactly 5 repeat photos"),
                check("DQ5 Reference captures pass T1, T2, T3, T6", None, f"{len(reps)} photos",
                      "exactly 5 repeat photos")]
        reps = None
    if reps:
        sizes = [cv2.imread(str(p)).shape[1::-1] for p in reps]
        ok3 = all(w >= LIMITS["min_photo"][0] and h >= LIMITS["min_photo"][1] for w, h in sizes)
        out.append(check("DQ3 Photo resolution", ok3, f"{min(sizes)}", f">= {LIMITS['min_photo']}"))
        sc = [_tech(cv2.imread(str(p))) for p in reps]
        tqs = [t for _, t in sc]
        rng = {c: max(s[c] for s, _ in sc) - min(s[c] for s, _ in sc) for c in TECH}
        ok4 = (max(tqs) - min(tqs) <= LIMITS["tqs_range"]
               and max(rng.values()) <= LIMITS["criterion_range"])
        out.append(check("DQ4 Repeatability", ok4,
                         f"TQS range {max(tqs) - min(tqs):.3f}; worst criterion "
                         f"{max(rng, key=rng.get)} {max(rng.values()):.3f}",
                         f"TQS <= {LIMITS['tqs_range']}, each criterion <= {LIMITS['criterion_range']}"))
        core = ("sharpness", "exposure", "background", "colorcast")
        passing = sum(all(s[c] >= SPEC_PASS[c] for c in core) for s, _ in sc)
        out.append(check("DQ5 Reference captures pass T1, T2, T3, T6", passing / len(sc)
                         >= LIMITS["repeat_pass_share"], f"{passing}/{len(sc)}",
                         f">= {int(LIMITS['repeat_pass_share'] * 100)} %"))
    elif reps is not None:
        out += [check("DQ3 Photo resolution", None, "-", f">= {LIMITS['min_photo']}"),
                check("DQ4 Repeatability", None, "-", "5 captures"),
                check("DQ5 Reference captures pass T1, T2, T3, T6", None, "-", ">= 80 %")]
    gl = rep.get("guidance_round_trip_ms")         # list from the app's session log
    out.append(check("DQ6 Live guidance speed", st.median(gl) <= LIMITS["guidance_median_ms"]
                     if gl else None, f"median {st.median(gl):.0f} ms" if gl else "-",
                     f"median <= {LIMITS['guidance_median_ms']} ms",
                     f"server {rep.get('server_url', '?')}, network {rep.get('network', '?')}"))
    return out, rep


def ai_processing(dev: Path):
    """Informational: how much the phone's own camera (AI scene optimisation ON)
    changes the photo compared with the PQF app's capture of the same scene."""
    a, b = _imgs(dev / "inapp"), _imgs(dev / "default_camera")
    if not a or len(a) != len(b):
        return None
    from skimage.color import rgb2lab, deltaE_ciede2000
    from backend.pqf.preprocess import standardise
    from backend.pqf.technical import product_mask
    rows = []
    for pa, pb in zip(a, b):
        ia = standardise(platform_format(cv2.imread(str(pa))))
        ib = cv2.resize(standardise(platform_format(cv2.imread(str(pb)))), ia.shape[1::-1])
        sa, ta = _tech(cv2.imread(str(pa)))
        sb, tb = _tech(cv2.imread(str(pb)))
        m = product_mask(ia) > 0
        de = deltaE_ciede2000(rgb2lab(cv2.cvtColor(ia, cv2.COLOR_BGR2RGB)[m][None] / 255.0),
                              rgb2lab(cv2.cvtColor(ib, cv2.COLOR_BGR2RGB)[m][None] / 255.0))
        sat = lambda im: float(cv2.cvtColor(im, cv2.COLOR_BGR2HSV)[..., 1][m].mean())
        rows.append({"pair": f"{pa.name} | {pb.name}", "d_sharpness": round(sb["sharpness"] - sa["sharpness"], 3),
                     "d_tqs": round(tb - ta, 3), "product_deltaE_median": round(float(np.median(de)), 2),
                     "d_saturation": round(sat(ib) - sat(ia), 1)})
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    results = {}
    for dev in sorted(d for d in a.devices.iterdir() if d.is_dir()):
        dq, rep = device_tests(dev)
        eq = environment_tests(dev)
        ai = ai_processing(dev)
        st_ = [t["status"] for t in dq + eq]
        verdict = ("NOT CERTIFIED" if "FAIL" in st_ else "INCOMPLETE" if "NOT MEASURED" in st_
                   else "CERTIFIED")
        results[dev.name] = {"device": rep.get("model", dev.name), "report": rep, "device_tests": dq,
                             "environment_tests": eq, "ai_processing": ai, "verdict": verdict}
        print(f"{dev.name}: {results[dev.name]['verdict']}")
        for t in dq + eq:
            print(f"   {t['status']:<13} {t['test']}: {t['measured']} (limit {t['limit']})")
        if ai:
            print("   default camera vs PQF app:", ai)
    save_json(a.out / "device_qualification.json", {"limits": LIMITS, "devices": results})
