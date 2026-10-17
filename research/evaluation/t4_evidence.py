"""
t4_evidence.py  -  one table of the evidence for excluding T4 (BRISQUE) from the TQS
(2026-10-15). Recomputes everything from files already on disk; no scoring, no API calls,
no config change. Rule and bootstrap are those of calibrate_t4t5.py (P10, linear
interpolation, seed 20261008, B = 5000, brisque first so the random stream is the same).

Sources (all relative to the repo root):
  research/results/t4t5_calibration/per_image.csv      good n = 125 + synthetic NOISE/JPEG
  research/results/t4t5_calibration/calibration.json   the recorded P10 / CI, cross-checked
  research/results/o1_calibration/per_image.csv        calibration split (good images)
  research/results/o1_holdout/per_image.csv            holdout (good images): false alarms
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics as st
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evalcommon import wilson  # noqa: E402

SEED, B, SPEC_T4 = 20261008, 5000, 0.60
SRC = {"cal": "research/results/t4t5_calibration/per_image.csv",
       "calj": "research/results/t4t5_calibration/calibration.json",
       "o1c": "research/results/o1_calibration/per_image.csv",
       "o1h": "research/results/o1_holdout/per_image.csv"}


def pct(vals, q):
    v = sorted(vals)
    k = (len(v) - 1) * q / 100
    f, c = math.floor(k), math.ceil(k)
    return v[f] if f == c else v[f] + (v[c] - v[f]) * (k - f)


def rows(rel):
    return list(csv.DictReader(open(REPO / rel, newline="", encoding="utf-8")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    cal = rows(SRC["cal"])
    good = [r for r in cal if r["label"] == "good"]
    g = [float(r["brisque"]) for r in good]
    p10 = pct(g, 10)
    rng = random.Random(SEED)
    boots = sorted(pct([rng.choice(g) for _ in g], 10) for _ in range(B))
    ci = (boots[int(0.025 * B)], boots[int(0.975 * B) - 1])
    zero = sum(1 for v in g if v == 0.0)
    rec = json.loads((REPO / SRC["calj"]).read_text())["criteria"]["brisque"]
    # noise: pair every noisy image with its clean original (same product)
    clean = {r["product"]: float(r["brisque"]) for r in good}
    noise = {}
    for lv in ("1", "2", "3"):
        pairs = [(clean[r["product"]], float(r["brisque"])) for r in cal
                 if r["fault"] == "NOISE" and r["level"] == lv and r["product"] in clean]
        noise[lv] = {"n": len(pairs),
                     "median_clean": round(st.median(c for c, _ in pairs), 3),
                     "median_noisy": round(st.median(n for _, n in pairs), 3),
                     "median_change": round(st.median(n - c for c, n in pairs), 3),
                     "noisy_lower_than_clean": sum(1 for c, n in pairs if n < c)}
    tot_pairs = sum(v["n"] for v in noise.values())
    tot_lower = sum(v["noisy_lower_than_clean"] for v in noise.values())
    # splits
    def split(rel):
        r = [x for x in rows(rel) if x["label"] == "good" and x.get("brisque")]
        v = [float(x["brisque"]) for x in r]
        fa = sum(1 for x in v if x < SPEC_T4)
        return {"good_images": len(v), "median_t4": round(st.median(v), 3),
                "exactly_0.0": sum(1 for x in v if x == 0.0),
                "false_alarms_at_spec_0.60": fa,
                "false_alarm_rate_wilson95": [round(x, 3) for x in wilson(fa, len(v))],
                "false_alarms_at_calibrated_0.0": sum(1 for x in v if x < 0.0)}
    o1c, o1h = split(SRC["o1c"]), split(SRC["o1h"])
    out = {"n_good_pooled": len(g), "p10": round(p10, 4), "bootstrap_95ci": [round(x, 3) for x in ci],
           "recorded_p10": rec["percentile_value"], "recorded_ci": rec["bootstrap_95ci_of_percentile"],
           "reproduces_recorded": abs(p10 - rec["percentile_value"]) < 1e-3
           and [round(x, 3) for x in ci] == rec["bootstrap_95ci_of_percentile"],
           "exactly_0.0": zero, "median_good": round(st.median(g), 3),
           "false_alarms_at_spec_0.60": sum(1 for v in g if v < SPEC_T4),
           "noise": noise, "noise_pairs": tot_pairs, "noisy_lower_than_clean": tot_lower,
           "calibration_split": o1c, "holdout": o1h}
    pre = f"{a.label}_" if a.label else ""
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{pre}t4_evidence.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    md = [("> **%s** (computed from the existing calibration outputs).\n" % a.label if a.label else ""),
          "# T4 (BRISQUE) evidence table\n",
          "T4 is computed and reported but carries weight 0 in v1.4.0 (decisions.md 2026-10-11).\n",
          "## Pooled good calibration set (ABO + ABO extension)\n",
          "| quantity | value |", "|---|---|",
          f"| good images (n) | {len(g)} |",
          f"| T4 10th percentile (normalised) | {out['p10']} |",
          f"| bootstrap 95% CI of the P10 (B={B}, seed {SEED}) | {out['bootstrap_95ci'][0]} - {out['bootstrap_95ci'][1]} |",
          f"| reproduces calibration.json | {out['reproduces_recorded']} |",
          f"| images scoring exactly 0.0 | {zero} / {len(g)} ({100 * zero / len(g):.1f} %) |",
          f"| median T4 of good images | {out['median_good']} |",
          f"| good images below the specification's 0.60 (false alarms) | {out['false_alarms_at_spec_0.60']} / {len(g)} |",
          "\n## Synthetic NOISE (does a noisier photo score LOWER, as a quality metric must?)\n",
          "| level | pairs | median T4 clean | median T4 noisy | median change | noisy lower than clean |",
          "|---|---|---|---|---|---|"]
    md += [f"| L{lv} | {v['n']} | {v['median_clean']} | {v['median_noisy']} | {v['median_change']:+} "
           f"| {v['noisy_lower_than_clean']} / {v['n']} |" for lv, v in noise.items()]
    md += [f"\nAll levels: **{tot_lower} / {tot_pairs}** noisy images scored lower than their clean "
           "original (a valid noise metric would be near all of them).\n",
           "## Good images in the two splits (false alarms of T4 at the specification's 0.60)\n",
           "| split | good n | median T4 | exactly 0.0 | false alarms at 0.60 | Wilson 95% CI | false alarms at calibrated 0.0 |",
           "|---|---|---|---|---|---|---|"]
    for name, s in (("calibration", o1c), ("holdout", o1h)):
        md.append(f"| {name} | {s['good_images']} | {s['median_t4']} | {s['exactly_0.0']} | "
                  f"{s['false_alarms_at_spec_0.60']} | {s['false_alarm_rate_wilson95'][0]}-"
                  f"{s['false_alarm_rate_wilson95'][1]} | {s['false_alarms_at_calibrated_0.0']} |")
    md += ["\n## Sources\n"] + [f"- `{v}`" for v in SRC.values()]
    (a.out / f"{pre}t4_evidence.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
