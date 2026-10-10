"""
analysis_participants.py  -  O2, O3 and O4 from the participant sessions (2026-10-07).
All analyses and decision rules here are PRE-REGISTERED: fixed before the first
session and reported whatever the result (decisions.md 2026-10-03).

O2  Guided capture improves photographs (within participant, counterbalanced)
    a) framework score FQS (primary; TQS reported as secondary): for each condition the
       MEAN over all photos taken (not the best one, which would favour the condition
       with more shots), then per participant the mean over products, guided minus unguided;
       Wilcoxon signed-rank test, one-sided (H1 guided > unguided), effect size
       r = Z / sqrt(N), Hodges-Lehmann median difference with bootstrap 95 % CI.
    b) INDEPENDENT blind pairwise preference by photographers who do not know which
       photo was guided. Each pair = the participant's OWN pick of their best photo in
       each condition (made without seeing scores). One verdict per pair = the raters'
       majority (ties and split votes excluded); exact binomial test against 0.5 on
       pairs, Wilson 95 % CI; rater agreement reported. Input is the DECODED file
       o2_blind_preference_decoded.csv (preferred = guided|unguided|tie) written by
       decode_blind.py; raw A/B answers are refused.
    c) certified sets guided vs unguided: exact McNemar test.
    CLAIM "measurably improves" ONLY IF a) on FQS p < 0.05 AND b) p < 0.05.
O3  Framework selection agrees with people: Jaccard overlap of the framework's set
    with (a) the participant's own picks made BEFORE seeing the result and (b) the
    experts' blind picks; Cohen's kappa over images. Descriptive; pre-registered
    failure: mean overlap with participants below 0.50.
O4  Usability: SUS (Brooke, 1996) mean, SD, 95 % CI, one-sample t-test against the
    benchmark 68 (Sauro & Lewis, 2016), adjective band (Bangor et al., 2009);
    ISO 9241-11 effectiveness (task completion, Wilson CI) and efficiency (time).
    Pre-registered failure: SUS mean below 50.

Inputs: CSV files named as in templates/. Usage:
  python research/evaluation/analysis_participants.py --dir <folder with the CSVs> --out <dir>
  python research/evaluation/analysis_participants.py --demo --out <dir>   (SYNTHETIC data,
        only to check the pipeline; never report it)
"""
from __future__ import annotations

import argparse
import math
import random
import statistics as st
from collections import defaultdict
from pathlib import Path

from scipy import stats

from evalcommon import read_csv, write_csv, save_json, wilson


def flag(v):
    """1 / 0 from 1, 0, true, false, yes, no; None for blank (missing)."""
    v = str(v or "").strip().lower()
    if v in ("1", "true", "yes", "y"):
        return 1
    if v in ("0", "false", "no", "n"):
        return 0
    if v == "":
        return None
    raise SystemExit(f"Unexpected flag value {v!r}; use 0 or 1.")


def hodges_lehmann(d):
    w = sorted((d[i] + d[j]) / 2 for i in range(len(d)) for j in range(i, len(d)))
    return st.median(w)


def boot_ci(d, f, n=5000, seed=1):
    rng = random.Random(seed)
    vals = sorted(f([rng.choice(d) for _ in d]) for _ in range(n))
    return vals[int(0.025 * n)], vals[int(0.975 * n) - 1]


def o2(pairs, prefs):
    res = {}
    for metric in ("fqs", "tqs"):
        per = defaultdict(list)
        for r in pairs:
            if r.get(f"guided_{metric}") and r.get(f"unguided_{metric}"):
                per[r["participant"]].append(float(r[f"guided_{metric}"]) - float(r[f"unguided_{metric}"]))
        d = [st.mean(v) for v in per.values()]
        if len(d) < 2:
            continue
        w = stats.wilcoxon(d, alternative="greater")
        z = stats.norm.isf(w.pvalue) if 0 < w.pvalue < 1 else 0.0
        res[metric] = {"n_participants": len(d), "median_difference": round(st.median(d), 3),
                       "hodges_lehmann": round(hodges_lehmann(d), 3),
                       "hl_95ci": [round(x, 3) for x in boot_ci(d, hodges_lehmann)],
                       "wilcoxon_W": float(w.statistic), "p_one_sided": round(float(w.pvalue), 4),
                       "effect_size_r": round(z / math.sqrt(len(d)), 3),
                       "guided_better": sum(x > 0 for x in d)}
    cp = [(flag(r.get("guided_certified")), flag(r.get("unguided_certified"))) for r in pairs]
    cp = [x for x in cp if None not in x]
    if cp:
        b = sum(1 for g, u in cp if g == 1 and u == 0)
        c = sum(1 for g, u in cp if g == 0 and u == 1)
        p = stats.binomtest(b, b + c, 0.5).pvalue if b + c else 1.0
        res["certified"] = {"pairs": len(cp), "guided_only": b, "unguided_only": c,
                            "mcnemar_exact_p": round(float(p), 4),
                            "guided_rate": round(st.mean(g for g, _ in cp), 3),
                            "unguided_rate": round(st.mean(u for _, u in cp), 3)}
    if prefs:
        bad = {r["preferred"] for r in prefs} - {"guided", "unguided", "tie"}
        if bad:
            raise SystemExit(f"Blind preferences must be DECODED first (found {sorted(bad)}); "
                             "run decode_blind.py.")
        by_item = defaultdict(dict)
        for r in prefs:
            by_item[r["pair_id"]][r["rater"]] = r["preferred"]
        verdict = {}
        for pid, v in by_item.items():
            g_, u_ = sum(x == "guided" for x in v.values()), sum(x == "unguided" for x in v.values())
            verdict[pid] = "guided" if g_ > u_ else "unguided" if u_ > g_ else "none"
        g = sum(x == "guided" for x in verdict.values())
        u = sum(x == "unguided" for x in verdict.values())
        p = stats.binomtest(g, g + u, 0.5, alternative="greater").pvalue if g + u else 1.0
        multi = [v for v in by_item.values() if len(v) > 1]
        agree = sum(len(set(v.values())) == 1 for v in multi)
        res["blind_preference"] = {"pairs": len(verdict), "judgements": len(prefs),
                                   "pairs_guided": g, "pairs_unguided": u,
                                   "pairs_no_majority": len(verdict) - g - u,
                                   "share_guided": round(g / (g + u), 3) if g + u else None,
                                   "wilson_95ci": [round(x, 3) for x in wilson(g, g + u)],
                                   "binomial_p_one_sided": round(float(p), 4),
                                   "rater_full_agreement": f"{agree}/{len(multi)}" if multi else None}
    ok = (res.get("fqs", {}).get("p_one_sided", 1) < 0.05
          and res.get("blind_preference", {}).get("binomial_p_one_sided", 1) < 0.05)
    res["claim_measurably_improves"] = ok
    return res


def jaccard(a, b):
    return len(a & b) / len(a | b) if a | b else float("nan")


def kappa(x, y):
    n = len(x)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in zip(x, y)) / n
    p1, p2 = sum(x) / n, sum(y) / n
    pe = p1 * p2 + (1 - p1) * (1 - p2)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def o3(rows):
    res = {}
    for who in ("participant", "expert"):
        col = f"{who}_picked"
        if not rows or col not in rows[0]:
            continue
        use = [r for r in rows if flag(r.get(col)) is not None]
        if not use:
            continue
        gr = defaultdict(list)
        for r in use:
            gr[(r["participant"], r["product"])].append(r)
        j = [jaccard({r["image_id"] for r in g if flag(r["framework_selected"]) == 1},
                     {r["image_id"] for r in g if flag(r[col]) == 1}) for g in gr.values()]
        k = kappa([flag(r["framework_selected"]) for r in use], [flag(r[col]) for r in use])
        res[who] = {"sets": len(j), "mean_jaccard": round(st.mean(j), 3),
                    "median_jaccard": round(st.median(j), 3), "min": round(min(j), 3),
                    "cohen_kappa_images": round(k, 3)}
    res["preregistered_failure"] = res.get("participant", {}).get("mean_jaccard", 1) < 0.50
    return res


def sus_score(r):
    q = [int(r[f"q{i}"]) for i in range(1, 11)]
    return 2.5 * (sum(q[i] - 1 for i in range(0, 10, 2)) + sum(5 - q[i] for i in range(1, 10, 2)))


def adjective(m):
    """Adjective whose MEAN SUS is nearest (Bangor, Kortum & Miller, 2009, Table 3)."""
    means = {"Worst imaginable": 12.5, "Awful": 20.3, "Poor": 35.7, "OK": 50.9,
             "Good": 71.4, "Excellent": 85.5, "Best imaginable": 90.9}
    return min(means, key=lambda k: abs(means[k] - m))


def o4(sus, tasks):
    res = {}
    if sus:
        s = [sus_score(r) for r in sus]
        m, sd, n = st.mean(s), (st.stdev(s) if len(s) > 1 else 0.0), len(s)
        h = stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n) if n > 1 else float("nan")
        t = stats.ttest_1samp(s, 68) if n > 1 else None
        res["sus"] = {"n": n, "mean": round(m, 1), "sd": round(sd, 1),
                      "ci95": [round(m - h, 1), round(m + h, 1)], "min": min(s), "max": max(s),
                      "vs_68_t": round(float(t.statistic), 2) if t else None,
                      "vs_68_p": round(float(t.pvalue), 4) if t else None,
                      "adjective": adjective(m), "preregistered_failure": m < 50,
                      "scores": s}
    if tasks:
        by = defaultdict(list)
        for r in tasks:
            by[r["task"]].append(r)
        res["tasks"] = {}
        for k, rs in by.items():
            done = sum(flag(r["completed"]) == 1 for r in rs)
            times = [float(r["time_s"]) for r in rs if flag(r["completed"]) == 1 and r.get("time_s")]
            res["tasks"][k] = {"n": len(rs), "completed": done,
                               "completion_ci95": [round(x, 3) for x in wilson(done, len(rs))],
                               "median_time_s": round(st.median(times), 1) if times else None,
                               "assisted": sum(flag(r.get("assisted")) == 1 for r in rs)}
    return res


def demo(folder: Path):
    """SYNTHETIC data with the right shape, to test the analysis. Never report it."""
    rng = random.Random(7)
    pairs, prefs, sel, sus, tasks = [], [], [], [], []
    for p in range(1, 9):
        for prod in ("A", "B", "C"):
            u = rng.uniform(0.45, 0.65)
            g = min(0.95, u + rng.uniform(-0.03, 0.2))
            pairs.append({"participant": f"P{p}", "product": prod, "order": "GU" if p % 2 else "UG",
                          "unguided_tqs": round(u, 3), "guided_tqs": round(g, 3),
                          "unguided_fqs": round(u + 0.05, 3), "guided_fqs": round(g + 0.05, 3),
                          "unguided_certified": str(int(u > 0.6)), "guided_certified": str(int(g > 0.6)),
                          "time_unguided_s": rng.randint(90, 240), "time_guided_s": rng.randint(120, 300)})
            for rater in ("E1", "E2"):
                prefs.append({"rater": rater, "pair_id": f"P{p}-{prod}",
                              "preferred": rng.choice(["guided"] * 3 + ["unguided", "tie"])})
            for i in range(8):
                fs = int(i < 5)
                sel.append({"participant": f"P{p}", "product": prod, "image_id": f"{prod}{i}",
                            "framework_selected": str(fs),
                            "participant_picked": str(int(rng.random() < (0.7 if fs else 0.25)))
                            , "expert_picked": str(int(rng.random() < (0.75 if fs else 0.2)))})
        sus.append({"participant": f"P{p}", **{f"q{i}": str(rng.choice([4, 5] if i % 2 else [1, 2]))
                                               for i in range(1, 11)}})
        for t in ("guided_capture", "missing_shots", "video_saved"):
            tasks.append({"participant": f"P{p}", "task": t, "completed": str(int(rng.random() < 0.9)),
                          "time_s": rng.randint(60, 300), "errors": rng.randint(0, 2),
                          "assisted": str(int(rng.random() < 0.15))})
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in (("o2_capture_pairs", pairs), ("o2_blind_preference_decoded", prefs),
                       ("o3_selection", sel), ("o4_sus", sus), ("o4_tasks", tasks)):
        write_csv(folder / f"{name}.csv", rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    d = a.dir
    if a.demo:
        d = a.out / "DEMO_SYNTHETIC_INPUT"
        demo(d)
    load = lambda n: read_csv(d / f"{n}.csv") if (d / f"{n}.csv").exists() else []
    res = {"SYNTHETIC_DEMO_DO_NOT_REPORT": bool(a.demo),
           "O2": o2(load("o2_capture_pairs"), load("o2_blind_preference_decoded")),
           "O3": o3(load("o3_selection")),
           "O4": o4(load("o4_sus"), load("o4_tasks"))}
    save_json(a.out / "participants_summary.json", res)
    import json
    print(json.dumps(res, indent=1, default=float)[:3000])
