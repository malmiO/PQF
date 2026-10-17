"""
weight_sensitivity.py  -  how much do pass verdicts, roles and sets move if a weight is wrong
(2026-10-15). NO API CALLS: it re-combines scores that are already on disk (per-criterion
technical scores and cached semantic scores in the O1 per_image.csv files, and the re-scored
study photos). It never writes to config; the specification's weights stay as frozen.

Scenarios
  * each TQS criterion weight x1.2 and x0.8, the rest renormalised to sum 1 (a criterion
    already at weight 0, T4, cannot move and is reported as such);
  * each SQS criterion weight x1.2 and x0.8, renormalised;
  * alpha/beta (TQS share of FQS) 0.30/0.70, 0.35/0.65, 0.45/0.55, 0.50/0.50 (baseline 0.40/0.60).

Per scenario and dataset: % of images whose pass verdict is unchanged, % whose role is
unchanged, and the Jaccard overlap of the SET with the baseline set. A set is, for the O1
datasets, the images that pass within each product category (mean over categories with at
least one pass); for study sessions, the set the framework would select (process_batch).
Images without semantic scores (hard-rejected or T0 fail) cannot be re-combined and stay
rejects in every scenario; they are counted and reported.

  python research/evaluation/weight_sensitivity.py --out research/results/dryrun --label DRYRUN
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                                  # noqa: E402

from backend.pqf import config                                      # noqa: E402
from backend.pqf.combination import ImageDecision                   # noqa: E402
from backend.pqf.combination.combine import classify_role           # noqa: E402
from evalcommon import write_csv                                    # noqa: E402

TECH = list(config.TQS_WEIGHTS)
SEM = list(config.SQS_WEIGHTS)
HARD = getattr(config, "TQS_HARD_REJECT", 0.40)
BASE = {"tw": dict(config.TQS_WEIGHTS), "sw": dict(config.SQS_WEIGHTS),
        "alpha": config.FQS_ALPHA, "beta": config.FQS_BETA}


def scenarios() -> list:
    out = [("baseline", "baseline", dict(BASE))]
    for k in TECH:
        for f in (1.2, 0.8):
            tw = dict(BASE["tw"])
            tw[k] *= f
            s = sum(tw.values())
            out.append((f"TQS {k} x{f}", "tqs_weight",
                        {**BASE, "tw": {a: b / s for a, b in tw.items()},
                         "_noop": BASE["tw"][k] == 0.0}))
    for k in SEM:
        for f in (1.2, 0.8):
            sw = dict(BASE["sw"])
            sw[k] *= f
            s = sum(sw.values())
            out.append((f"SQS {k} x{f}", "sqs_weight",
                        {**BASE, "sw": {a: b / s for a, b in sw.items()}}))
    for a in (0.30, 0.35, 0.45, 0.50):
        out.append((f"alpha/beta {a:.2f}/{1 - a:.2f}", "alpha_beta",
                    {**BASE, "alpha": a, "beta": 1 - a}))
    return out


def decide(tech: dict, sem: dict | None, p: dict) -> dict:
    """role / passed / fqs for one image under scenario p. Needs the six technical scores
    and (unless hard-rejected) the five semantic ones."""
    tqs = sum(p["tw"][k] * tech[k] for k in TECH)
    if tqs < HARD or not sem:
        return {"role": "reject", "passed": False, "fqs": 0.0, "tqs": tqs, "sqs": 0.0}
    sqs = sum(p["sw"][k] * sem[k] for k in SEM)
    fqs = p["alpha"] * tqs + p["beta"] * sqs
    role = classify_role(fqs, sem)
    return {"role": role, "passed": fqs >= config.FQS_PASS_THRESHOLD and role != "reject",
            "fqs": fqs, "tqs": tqs, "sqs": sqs}


def load_o1(path: Path) -> list:
    rows = []
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        try:
            tech = {k: float(r[k]) for k in TECH}
        except (ValueError, KeyError):
            continue                        # T0 fail: no technical scores
        sem = None
        if r.get("subject_centering"):
            sem = {k: float(r[k]) for k in SEM}
        rows.append({"id": r["relpath"], "group": r.get("category", ""), "tech": tech,
                     "sem": sem, "n_logged_role": r.get("role")})
    return rows


def load_study(rescored: Path, log: Path) -> tuple:
    dec = json.loads((rescored / "rescored_decisions.json").read_text(encoding="utf-8"))
    rows, sessions = [], defaultdict(list)
    for line in log.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["event"] == "batch_result":
            key = (e["participant"], e["condition"])
            if key in sessions:
                continue
            for p in e["photos"]:
                if p["hash"] in dec:
                    sessions[key].append(p["hash"])
    for key, hs in sessions.items():
        for h in hs:
            d = dec[h]
            tech = d.get("technical_scores") or {}
            if len(tech) < len(TECH):
                continue
            rows.append({"id": h, "group": f"{key[0]}/{key[1]}", "tech": {k: tech[k] for k in TECH},
                         "sem": d["semantic_scores"] or None, "view_sig": d.get("view_sig")})
    return rows, sessions


def set_o1(rows: list, res: dict) -> dict:
    s = defaultdict(set)
    for r in rows:
        if res[r["id"]]["passed"]:
            s[r["group"]].add(r["id"])
    return s


def set_study(rows: list, res: dict) -> dict:
    """The set process_batch would pick from the passing photos of each session."""
    from backend.pqf.pipeline import process_batch
    by = defaultdict(list)
    for r in rows:
        by[r["group"]].append(r)
    out = {}
    for g, rs in by.items():
        decs = []
        for r in rs:
            x = res[r["id"]]
            d = ImageDecision(tqs=x["tqs"], sqs=x["sqs"], fqs=x["fqs"], role=x["role"],
                              passed=x["passed"], semantic_scores=r["sem"] or {})
            sig = r.get("view_sig")
            setattr(d, "view_sig", None if not sig else {
                "hash": np.asarray(sig["hash"]).astype(bool),
                "sil": np.asarray(sig["sil"]).astype(bool)})
            setattr(d, "path", r["id"])
            decs.append(d)
        out[g] = {d.path for d in process_batch(decs).selected}
    return out


def jaccard_mean(a: dict, b: dict) -> float | None:
    js = []
    for g in set(a) | set(b):
        x, y = a.get(g, set()), b.get(g, set())
        if x | y:
            js.append(len(x & y) / len(x | y))
    return st.mean(js) if js else None


def evaluate(name: str, rows: list, setfn) -> list:
    base_res = {r["id"]: decide(r["tech"], r["sem"], BASE) for r in rows}
    base_set = setfn(rows, base_res)
    n_no_sem = sum(1 for r in rows if not r["sem"])
    out = []
    for label, kind, p in scenarios():
        res = {r["id"]: decide(r["tech"], r["sem"], p) for r in rows}
        same_pass = sum(res[i]["passed"] == base_res[i]["passed"] for i in res)
        same_role = sum(res[i]["role"] == base_res[i]["role"] for i in res)
        j = jaccard_mean(base_set, setfn(rows, res))
        out.append({"dataset": name, "scenario": label, "kind": kind, "images": len(rows),
                    "no_semantic_scores": n_no_sem,
                    "pass_unchanged_pct": round(100 * same_pass / len(rows), 1),
                    "role_unchanged_pct": round(100 * same_role / len(rows), 1),
                    "set_jaccard_vs_baseline": None if j is None else round(j, 3),
                    "passes_baseline": sum(v["passed"] for v in base_res.values()),
                    "passes_scenario": sum(v["passed"] for v in res.values()),
                    "note": "weight is 0: cannot move" if p.get("_noop") else ""})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--calibration", type=Path,
                    default=REPO / "research/results/o1_calibration/per_image.csv")
    ap.add_argument("--holdout", type=Path,
                    default=REPO / "research/results/o1_holdout/per_image.csv")
    ap.add_argument("--rescored", type=Path, default=REPO / "research/results/dryrun/rescore")
    ap.add_argument("--study-log", type=Path,
                    default=REPO / "research/results/dryrun/study_dir/study_log.jsonl")
    a = ap.parse_args()
    rows = []
    for name, path in (("calibration", a.calibration), ("holdout", a.holdout)):
        if path.exists():
            rows += evaluate(name, load_o1(path), set_o1)
    if (a.rescored / "rescored_decisions.json").exists() and a.study_log.exists():
        srows, _ = load_study(a.rescored, a.study_log)
        if srows:
            rows += evaluate("study photos (dry run)", srows, set_study)
    pre = f"{a.label}_" if a.label else ""
    a.out.mkdir(parents=True, exist_ok=True)
    write_csv(a.out / f"{pre}weight_sensitivity.csv", rows)
    md = [("> **%s**: study rows are test data.\n" % a.label if a.label else ""),
          "# Weight sensitivity (no API calls; cached scores only)\n",
          "Baseline = config weights as frozen for v1.4.0 (T4 weight 0; alpha/beta 0.40/0.60). "
          "Each TQS and SQS weight is moved x1.2 and x0.8 with the rest renormalised; alpha/beta "
          "0.30/0.70 to 0.50/0.50. Config is not changed.\n"]
    for ds in dict.fromkeys(r["dataset"] for r in rows):
        sub = [r for r in rows if r["dataset"] == ds]
        md += [f"\n## {ds} (n = {sub[0]['images']} images, {sub[0]['no_semantic_scores']} without "
               "semantic scores)\n",
               "| scenario | pass unchanged % | role unchanged % | set Jaccard | passes (base -> scen.) | note |",
               "|---|---|---|---|---|---|"]
        md += [f"| {r['scenario']} | {r['pass_unchanged_pct']} | {r['role_unchanged_pct']} | "
               f"{r['set_jaccard_vs_baseline']} | {r['passes_baseline']} -> {r['passes_scenario']} | "
               f"{r['note']} |" for r in sub]
        worst = min(sub, key=lambda r: r["pass_unchanged_pct"])
        md.append(f"\nLeast stable: **{worst['scenario']}** "
                  f"({worst['pass_unchanged_pct']} % of verdicts unchanged).")
    (a.out / f"{pre}weight_sensitivity.md").write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:60]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
