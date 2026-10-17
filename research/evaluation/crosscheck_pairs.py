"""
crosscheck_pairs.py  -  PART A of the human cross-check: the 24 fault-vs-clean pairs of the
HOLDOUT researcher captures (2026-10-16). READS research/results/o1_holdout/per_image.csv ONLY:
no holdout image is scored or re-scored here; images are only paired for display.

Pair = a fault photo (label 'degraded') against the same product's CLEAN photo (label
'reference'); 4 researcher products x 6 faults = 24 pairs.

Framework ordering rule (fixed before anyone rates):
  * higher FQS wins;
  * if exactly one photo has no FQS (hard reject or T0 fail) that one is lower;
  * if neither has an FQS, the higher TQS wins (no TQS counts as lowest).
Left/right is random with a fixed seed, recorded in the private key.

Output (private, git-ignored): research/results/crosscheck/pair_key.csv
  pair_id, left_is (fault|clean), fault_type, fqs_fault, fqs_clean, framework_pick (fault|clean|tie),
  source (holdout_real), product, tqs_fault, tqs_clean, left_path, right_path, seed
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED = 20261016


def num(v):
    try:
        return float(v) if str(v).strip() != "" else None
    except ValueError:
        return None


def framework_pick(f_fault, f_clean, t_fault, t_clean) -> str:
    """'fault' | 'clean' | 'tie' - which photo the framework puts higher."""
    if f_fault is not None and f_clean is not None:
        return "fault" if f_fault > f_clean else "clean" if f_clean > f_fault else "tie"
    if (f_fault is None) != (f_clean is None):
        return "clean" if f_fault is None else "fault"      # the one WITHOUT an FQS is lower
    a = -1.0 if t_fault is None else t_fault
    b = -1.0 if t_clean is None else t_clean
    return "fault" if a > b else "clean" if b > a else "tie"


def build(per_image: Path, seed: int = SEED) -> list:
    rows = list(csv.DictReader(open(per_image, newline="", encoding="utf-8")))
    by = {}
    for r in rows:
        if r["source"] == "researcher_capture":
            by.setdefault(r["product"], {"clean": None, "faults": []})
            if r["label"] == "reference":
                by[r["product"]]["clean"] = r
            elif r["label"] == "degraded":
                by[r["product"]]["faults"].append(r)
    rng = random.Random(seed)
    out = []
    for product in sorted(by):
        clean = by[product]["clean"]
        for f in sorted(by[product]["faults"], key=lambda r: r["fault"]):
            ff, fc = num(f["fqs"]), num(clean["fqs"])
            left_is = rng.choice(["fault", "clean"])
            lp, rp = (f, clean) if left_is == "fault" else (clean, f)
            out.append({
                "pair_id": "%06x" % rng.randrange(16 ** 6), "left_is": left_is,
                "fault_type": f["fault"], "fqs_fault": "" if ff is None else ff,
                "fqs_clean": "" if fc is None else fc,
                "framework_pick": framework_pick(ff, fc, num(f["tqs"]), num(clean["tqs"])),
                "source": "holdout_real", "product": product,
                "tqs_fault": f["tqs"], "tqs_clean": clean["tqs"],
                "left_path": lp["relpath"], "right_path": rp["relpath"], "seed": seed})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-image", type=Path, default=REPO / "research/results/o1_holdout/per_image.csv")
    ap.add_argument("--out", type=Path, default=REPO / "research/results/crosscheck/pair_key.csv")
    ap.add_argument("--seed", type=int, default=SEED)
    a = ap.parse_args()
    rows = build(a.per_image, a.seed)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    import collections
    print(len(rows), "pairs;", dict(collections.Counter(r["fault_type"] for r in rows)))
    print("framework picks:", dict(collections.Counter(r["framework_pick"] for r in rows)))
    print("by fault x pick:", dict(collections.Counter((r["fault_type"], r["framework_pick"]) for r in rows)))
