"""
calibrate_t4t5.py  -  the PRE-REGISTERED calibration of the T4 BRISQUE and T5 PIQE pass
thresholds (decisions.md 2026-10-08). Run ONCE, on calibration images only, before the
v1.4.0 freeze.

WHY. On v1.3.0 the specification thresholds (BRISQUE raw <= 40, PIQE raw <= 45) flag
24/29 and 18/29 GOOD calibration images. Both metrics were trained on natural scenes,
not white-background product photos, so their raw scale does not transfer (formative
finding, 2026-10-07). The other criteria keep their specification thresholds.

THE RULE (fixed before looking at any holdout image):
  threshold = the 10th percentile of the normalised score over GOOD calibration
              images (ABO calibration split + the ABO calibration extension),
              rounded DOWN to 2 decimals.
  Expected false-alarm rate on good images is therefore about 10%; the holdout
  false-alarm rate is reported against that expectation.
  Weights are NOT changed. Only the pass thresholds used for feedback and for O1.

Also reported, for information only (NOT used to choose the threshold): a bootstrap
95% interval of the percentile, and, if --manifest is given, how many calibration
NOISE / JPEG synthetic faults fall below the proposed thresholds.

Usage (repo root, pinned environment: Railway image or the Python 3.11 .venv-eval):
  python research/evaluation/calibrate_t4t5.py --data data --split data/splits/split_v1.csv \
         --extra data/abo_extension --manifest research/results/synthetic/manifest.csv \
         --out research/results/t4t5_calibration
"""
from __future__ import annotations

import argparse
import math
import random
from pathlib import Path

from evalcommon import (SPEC_PASS, LABEL, discover, apply_split, write_csv, save_json,
                        environment, IMG_EXT, wilson)
from o1_detection import score_all, load_manifest

PERCENTILE = 10
SEED = 20261008
B = 5000


def pct(vals: list, q: float) -> float:
    """Linear-interpolation percentile (numpy's default), written out for transparency."""
    v = sorted(vals)
    k = (len(v) - 1) * q / 100
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def floor2(x: float) -> float:
    return math.floor(x * 100 + 1e-9) / 100


def extra_rows(folder: Path) -> list:
    rows = []
    for p in sorted(folder.rglob("*")):
        if p.suffix.lower() in IMG_EXT and not p.name.startswith("."):
            rows.append({"path": str(p), "relpath": str(p.relative_to(folder)),
                         "category": p.parent.name, "source": "ABO_extension",
                         "product": f"abo/{p.stem}", "label": "good", "fault": "",
                         "target": ""})
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--split", required=True, type=Path)
    ap.add_argument("--extra", type=Path, help="ABO calibration extension folder (all good)")
    ap.add_argument("--manifest", type=Path, help="synthetic_faults.py manifest.csv")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()

    good = [r for r in apply_split(discover(a.data), a.split, "calibration")
            if r["source"] == "ABO"]
    if a.extra:
        good += extra_rows(a.extra)
    syn = [r for r in load_manifest(a.manifest, "calibration")
           if r["fault"] in ("NOISE", "JPEG")] if a.manifest else []
    print(f"{len(good)} good calibration images, {len(syn)} NOISE/JPEG synthetic faults")
    a.out.mkdir(parents=True, exist_ok=True)
    rec = score_all(good + syn, False, a.out / "unused_cache.json", 0)
    write_csv(a.out / "per_image.csv", rec)
    env = environment()
    if set(env["metric_status"]["abstaining"]) & {"brisque", "piqe"}:
        raise SystemExit(f"BRISQUE/PIQE abstained in this environment {env['metric_status']}. "
                         "Use the pinned environment (Railway image or .venv-eval); "
                         "nothing was calibrated.")

    rng = random.Random(SEED)
    result = {"rule": f"P{PERCENTILE} of normalised score over good calibration images, "
                      "rounded down to 2 decimals", "seed": SEED, "bootstrap_B": B,
              "n_good": len(good), "sources": sorted({r["source"] for r in good}),
              "criteria": {}}
    for c, target in (("brisque", "NOISE"), ("piqe", "JPEG")):
        g = [r[c] for r in rec if r["label"] == "good" and c in r]
        p = pct(g, PERCENTILE)
        thr = floor2(p)
        boots = sorted(pct([rng.choice(g) for _ in g], PERCENTILE) for _ in range(B))
        fa = sum(1 for v in g if v < thr)
        row = {"label": LABEL[c], "spec_threshold": SPEC_PASS[c],
               "spec_false_alarms": sum(1 for v in g if v < SPEC_PASS[c]),
               "percentile_value": round(p, 4),
               "proposed_threshold": thr,
               "proposed_raw_equivalent": round(100 * (1 - thr), 1),
               "bootstrap_95ci_of_percentile": [round(boots[int(0.025 * B)], 3),
                                                round(boots[int(0.975 * B) - 1], 3)],
               "calibration_false_alarms": fa, "n_good": len(g),
               "calibration_false_alarm_ci": [round(x, 3) for x in wilson(fa, len(g))],
               "median_good": round(pct(g, 50), 3)}
        s = [r for r in rec if r.get("fault") == target and c in r]
        if s:
            row["synthetic_" + target] = {
                lv: f"{sum(1 for r in s if r['level'] == lv and r[c] < thr)}/"
                    f"{sum(1 for r in s if r['level'] == lv)}" for lv in (1, 2, 3)}
        result["criteria"][c] = row
    result["environment"] = env
    save_json(a.out / "calibration.json", result)

    L = ["# T4 / T5 threshold calibration (pre-registered rule, 2026-10-08)", "",
         f"Good calibration images: {len(good)} ({', '.join(result['sources'])}). "
         f"Rule: {result['rule']}.", "",
         "| Criterion | Spec threshold (false alarms) | P10 | Bootstrap 95% CI | "
         "Proposed threshold | Raw equivalent | Calibration false alarms | Synthetic faults below (L1/L2/L3) |",
         "|---|---|---|---|---|---|---|---|"]
    for c, r in result["criteria"].items():
        sk = next((k for k in r if k.startswith("synthetic_")), None)
        sy = " / ".join(r[sk][lv] for lv in (1, 2, 3)) if sk else "-"
        L.append(f"| {r['label']} | {r['spec_threshold']} ({r['spec_false_alarms']}/{r['n_good']}) | "
                 f"{r['percentile_value']} | {r['bootstrap_95ci_of_percentile']} | "
                 f"**{r['proposed_threshold']}** | raw <= {r['proposed_raw_equivalent']} | "
                 f"{r['calibration_false_alarms']}/{r['n_good']} | {sy} |")
    L += ["", "Copy the two proposed thresholds into backend/pqf/config.py as "
          "T4_PASS_THRESHOLD and T5_PASS_THRESHOLD (logged exception, v1.4.0). "
          "Do not adjust them after seeing the synthetic row: it is reported, not used."]
    md = "\n".join(L) + "\n"
    (a.out / "calibration.md").write_text(md, encoding="utf-8")
    print(md)
