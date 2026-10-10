"""
analysis_study.py  -  O2, O3, O4 from the REAL study data of PQF v1.3/v1.4 (2026-10-07).

Reads what the app and server actually record (no re-typing):
  study_log.jsonl            POST /study/log entries (server copy on the Railway volume,
                             or the phone's copy); one participant = two sessions,
                             GUIDED and UNGUIDED, in ABBA order (study_api.abba_order)
  rater_sheet.csv + blind_key.csv      photographers' blind A/B answers (make_blind_packs.py)
  expert_sheet.csv + expert_key.csv    experts' blind picks of 4 per GUIDED set
  o4_sus.csv, o4_tasks.csv             SUS and task observations (templates/)
Any input that is missing is skipped and reported as "not collected".

PRE-REGISTERED (decisions.md 2026-10-03 and 2026-10-07):
O2 (a) FQS, mean over ALL photos of the FIRST /batch of each session (before retakes),
       guided minus unguided per participant; one-sided Wilcoxon signed-rank, r, Hodges-
       Lehmann + bootstrap CI. TQS reported as secondary.
   (b) blind preference between the participant's OWN picks in each condition (slots as
       pre-registered in make_blind_packs.py --slots); majority of raters per pair, then
       majority per participant; exact one-sided binomial across participants; Wilson CI.
   (c) first set certified, guided vs unguided: exact McNemar.
   Claim "measurably improves" only if (a) p < 0.05 AND (b) p < 0.05.
O3 Jaccard and Cohen's kappa between the framework's set (first /batch) and (i) the
   participant's own four picks, (ii) each expert's blind picks. Fails if the mean
   Jaccard with participants (GUIDED sessions) is below 0.50.
O4 SUS mean, SD, 95 % CI, t-test vs 68, Bangor adjective; task completion with Wilson CI.

Usage: python research/evaluation/analysis_study.py --dir <folder with the files> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

from scipy import stats

from evalcommon import read_csv, save_json, wilson
from analysis_participants import hodges_lehmann, boot_ci, jaccard, kappa, o4, flag
from decode_blind import decode


def load_log(p: Path) -> list:
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            if not str(e.get("product", "")).upper().startswith("SMOKE"):
                out.append(e)
    return out


def sessions(log: list) -> dict:
    """(participant, condition) -> first batch, own picks, last batch."""
    by = defaultdict(list)
    for e in log:
        by[(e["participant"], e["condition"])].append(e)
    out = {}
    for k, ev in by.items():
        ev.sort(key=lambda e: e.get("timestamp", ""))
        batches = [e for e in ev if e["event"] == "batch_result"]
        picks = next((e.get("own_picks", {}) for e in ev if e["event"] == "own_picks"), {})
        out[k] = {"first": batches[0] if batches else None,
                  "last": batches[-1] if batches else None, "picks": picks,
                  "n_batches": len(batches)}
    return out


def o2a(S: dict) -> dict:
    res = {}
    parts = sorted({p for p, _ in S})
    for metric in ("fqs", "tqs"):
        d = []
        for p in parts:
            g, u = S.get((p, "GUIDED")), S.get((p, "UNGUIDED"))
            if not (g and u and g["first"] and u["first"]):
                continue
            mg = st.mean(x[metric] for x in g["first"]["photos"]) if g["first"]["photos"] else None
            mu = st.mean(x[metric] for x in u["first"]["photos"]) if u["first"]["photos"] else None
            if mg is not None and mu is not None:
                d.append(mg - mu)
        if len(d) < 2:
            res[metric] = {"n_participants": len(d), "note": "not enough complete participants"}
            continue
        w = stats.wilcoxon(d, alternative="greater")
        z = stats.norm.isf(w.pvalue) if 0 < w.pvalue < 1 else 0.0
        res[metric] = {"n_participants": len(d), "median_difference": round(st.median(d), 3),
                       "hodges_lehmann": round(hodges_lehmann(d), 3),
                       "hl_95ci": [round(x, 3) for x in boot_ci(d, hodges_lehmann)],
                       "p_one_sided": round(float(w.pvalue), 4),
                       "effect_size_r": round(z / math.sqrt(len(d)), 3),
                       "guided_better": sum(x > 0 for x in d)}
    pairs = [(S[(p, "GUIDED")]["first"]["gate"]["certified"],
              S[(p, "UNGUIDED")]["first"]["gate"]["certified"])
             for p in parts if S.get((p, "GUIDED")) and S.get((p, "UNGUIDED"))
             and S[(p, "GUIDED")]["first"] and S[(p, "UNGUIDED")]["first"]]
    if pairs:
        b = sum(1 for g, u in pairs if g and not u)
        c = sum(1 for g, u in pairs if u and not g)
        res["certified_first"] = {
            "pairs": len(pairs), "guided_only": b, "unguided_only": c,
            "mcnemar_exact_p": round(float(stats.binomtest(b, b + c, 0.5).pvalue), 4) if b + c else 1.0,
            "guided_rate": round(st.mean(int(g) for g, _ in pairs), 3),
            "unguided_rate": round(st.mean(int(u) for _, u in pairs), 3)}
    return res


def o2b(folder: Path) -> dict | None:
    if not (folder / "rater_sheet.csv").exists() or not (folder / "blind_key.csv").exists():
        return None
    ans = [r for r in read_csv(folder / "rater_sheet.csv") if r.get("preferred", "").strip()]
    if not ans:
        return None
    keyrows = read_csv(folder / "blind_key.csv")
    owner = {r["pair_id"]: r.get("participant", r["pair_id"]) for r in keyrows}
    dec = decode(ans, keyrows)
    by = defaultdict(dict)
    for r in dec:
        by[r["pair_id"]][r["rater"]] = r["preferred"]
    verdict = {}
    for pid, v in by.items():
        g = sum(x == "guided" for x in v.values())
        u = sum(x == "unguided" for x in v.values())
        verdict[pid] = "guided" if g > u else "unguided" if u > g else "none"
    # The TEST unit is the participant (one verdict each: the majority over their
    # pairs), so several pairs from one person are never counted as independent.
    per = defaultdict(list)
    for pid, v in verdict.items():
        per[owner.get(pid, pid)].append(v)
    pv = {p: ("guided" if v.count("guided") > v.count("unguided") else
              "unguided" if v.count("unguided") > v.count("guided") else "none")
          for p, v in per.items()}
    g = sum(x == "guided" for x in pv.values())
    u = sum(x == "unguided" for x in pv.values())
    multi = [v for v in by.values() if len(v) > 1]
    return {"pairs": len(verdict), "participants": len(pv), "raters": len({r["rater"] for r in dec}),
            "pairs_guided": sum(x == "guided" for x in verdict.values()),
            "pairs_unguided": sum(x == "unguided" for x in verdict.values()),
            "participants_guided": g, "participants_unguided": u,
            "participants_no_majority": len(pv) - g - u,
            "share_guided": round(g / (g + u), 3) if g + u else None,
            "wilson_95ci": [round(x, 3) for x in wilson(g, g + u)],
            "binomial_p_one_sided": round(float(stats.binomtest(g, g + u, 0.5,
                                                 alternative="greater").pvalue), 4) if g + u else 1.0,
            "rater_full_agreement": f"{sum(len(set(v.values())) == 1 for v in multi)}/{len(multi)}"
            if multi else None}


def o3(S: dict, folder: Path) -> dict:
    res = {}
    for cond in ("GUIDED", "UNGUIDED"):
        js, xs, ys = [], [], []
        for (p, c), s in S.items():
            if c != cond or not s["first"] or not s["picks"]:
                continue
            fw = {x["hash"] for x in s["first"].get("framework_selection", [])}
            own = set(s["picks"].values())
            js.append(jaccard(fw, own))
            for ph in s["first"]["photos"]:
                xs.append(int(ph["hash"] in fw))
                ys.append(int(ph["hash"] in own))
        if js:
            res[f"participants_{cond.lower()}"] = {
                "sessions": len(js), "mean_jaccard": round(st.mean(js), 3),
                "median_jaccard": round(st.median(js), 3), "min": round(min(js), 3),
                "cohen_kappa_photos": round(kappa(xs, ys), 3)}
    if (folder / "expert_sheet.csv").exists() and (folder / "expert_key.csv").exists():
        key = {(r["set_id"], r["image"]): r for r in read_csv(folder / "expert_key.csv")}
        fw_by_p = {p: {x["hash"] for x in s["first"].get("framework_selection", [])}
                   for (p, c), s in S.items() if c == "GUIDED" and s["first"]}
        picks = defaultdict(set)
        seen = defaultdict(set)
        for r in read_csv(folder / "expert_sheet.csv"):
            if flag(r.get("picked")) is None or not r.get("expert"):
                continue
            k = key[(r["set_id"], r["image"])]
            seen[(r["expert"], k["participant"])].add(k["sha256"])
            if flag(r["picked"]) == 1:
                picks[(r["expert"], k["participant"])].add(k["sha256"])
        js, xs, ys = [], [], []
        for (ex, p), allh in seen.items():
            fw = fw_by_p.get(p, set())
            js.append(jaccard(fw, picks[(ex, p)]))
            for h in allh:
                xs.append(int(h in fw))
                ys.append(int(h in picks[(ex, p)]))
        if js:
            res["experts"] = {"sets_rated": len(js), "experts": len({e for e, _ in seen}),
                              "mean_jaccard": round(st.mean(js), 3),
                              "median_jaccard": round(st.median(js), 3),
                              "cohen_kappa_photos": round(kappa(xs, ys), 3)}
    pg = res.get("participants_guided", {})
    res["preregistered_failure"] = (pg.get("mean_jaccard", 1.0) < 0.50) if pg else None
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    log = load_log(a.dir / "study_log.jsonl")
    S = sessions(log)
    load = lambda n: read_csv(a.dir / n) if (a.dir / n).exists() else []
    O2 = o2a(S)
    b = o2b(a.dir)
    O2["blind_preference"] = b if b else "not collected"
    O2["claim_measurably_improves"] = bool(
        O2.get("fqs", {}).get("p_one_sided", 1) < 0.05 and b and b["binomial_p_one_sided"] < 0.05)
    res = {"participants": len({p for p, _ in S}), "sessions": len(S),
           "O2": O2, "O3": o3(S, a.dir), "O4": o4(load("o4_sus.csv"), load("o4_tasks.csv"))}
    save_json(a.out / "study_summary.json", res)
    print(json.dumps(res, indent=1, default=float))
