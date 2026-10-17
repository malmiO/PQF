"""study_analysis_run.py - the NON-panel analyses of the real study (plan fixed in advance;
no test, threshold or inclusion rule is changed here). Re-uses the tests of analysis_study.py
and weight_sensitivity.py; all inputs come from build_study_inputs.py (no API calls).

    .venv/Scripts/python.exe research/evaluation/study_analysis_run.py
Outputs -> research/results/study/analysis/ (analysis.md, summary.json, *.csv)
"""
from __future__ import annotations

import csv
import json
import math
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]

import numpy as np                                   # noqa: E402
from scipy import stats                              # noqa: E402

import analysis_study as A                           # noqa: E402
import weight_sensitivity as W                       # noqa: E402
from backend.pqf import config                       # noqa: E402
from backend.pqf.pipeline import process_batch       # noqa: E402
from backend.pqf.pipeline.pipeline import _meets     # noqa: E402
from evalcommon import write_csv                     # noqa: E402

ROOT = HERE.parents[1] / "research" / "results" / "study"
OUT = ROOT / "analysis"
SD = OUT / "study_dir"
rnd = A.rnd


# ------------------------------------------------------------------ inputs
def manifest():
    rows = list(csv.DictReader(open(ROOT / "participant_manifest.csv", encoding="utf-8")))
    prim = {r["code"] for r in rows if r["primary"] == "True"}
    sec = {r["code"] for r in rows if r["secondary"] == "True"}
    arm = {r["code"]: r["arm"] for r in rows}
    return prim, sec, arm


def sub(S, codes):
    return {k: v for k, v in S.items() if k[0] in codes}


def means(S, rows, fq="rescored"):
    """participant -> condition -> means over the photos of the first batch_result of the
    attempt. fq='rescored' uses the rescored TQS/SQS/FQS; 'logged' the live values."""
    out = defaultdict(dict)
    for (p, c), s in S.items():
        if not s["first"] or not s["first"].get("photos"):
            continue
        ph = s["first"]["photos"]
        if fq == "rescored":
            f = [float(rows[x["hash"]]["rescored_fqs"]) for x in ph]
            t = [float(rows[x["hash"]]["rescored_tqs"]) for x in ph]
            q = [float(rows[x["hash"]]["rescored_sqs"]) for x in ph]
        else:
            f, t, q = ([x[k] for x in ph] for k in ("fqs", "tqs", "sqs"))
        d = {"fqs": st.mean(f), "tqs": st.mean(t), "sqs": st.mean(q), "n_photos": len(ph)}
        for col, _ in A.CRITERIA:
            v = [float(rows[x["hash"]][col]) for x in ph
                 if rows.get(x["hash"], {}).get(col) not in (None, "")]
            d[col] = st.mean(v) if v else None
        out[p][c] = d
    return out


def o2a_exact(M):
    """A.o2a plus the unrounded one-sided Wilcoxon p."""
    res, tab = A.o2a(M)
    parts = sorted(p for p in M if "GUIDED" in M[p] and "UNGUIDED" in M[p])
    d = [M[p]["GUIDED"]["fqs"] - M[p]["UNGUIDED"]["fqs"] for p in parts]
    if len(d) >= 2 and any(x != 0 for x in d):
        w = stats.wilcoxon(d, alternative="greater")
        res["fqs"]["p_unrounded"] = float(w.pvalue)
        res["fqs"]["T_plus"] = float(w.statistic)
        res["fqs"]["ties_or_zeros"] = (len(set(map(abs, d))) < len(d)) or any(x == 0 for x in d)
        # exact two-sided companion, descriptive only
        res["fqs"]["wilcoxon_p_two_sided"] = float(stats.wilcoxon(d).pvalue)
    return res, tab, parts, d


def ci_text(e):
    return f"{e.get('hodges_lehmann')} [{e['hl_95ci'][0]}, {e['hl_95ci'][1]}]" if e.get("hl_95ci") else ""


# ------------------------------------------------------------------ O3 (rescored set)
def fw_set(s, dec):
    hs = [x["hash"] for x in s["first"]["photos"] if x["hash"] in dec]
    r = process_batch([A._rebuild(h, dec) for h in hs])
    return {d.path: d.role for d in r.selected}, r.certified


def o3_rescored(S, dec):
    res, rows = {}, []
    for cond in ("GUIDED", "UNGUIDED"):
        js, X, Y = [], [], []
        for (p, c), s in sorted(S.items()):
            if c != cond or not s["first"] or not s["picks"]:
                continue
            fw, cert = fw_set(s, dec)
            own = set(s["picks"].values())
            j = A.jaccard(set(fw), own)
            js.append(j)
            own_role = {h: A.OWN_ROLE[slot] for slot, h in s["picks"].items() if slot in A.OWN_ROLE}
            for ph in s["first"]["photos"]:
                X.append(fw.get(ph["hash"], "none"))
                Y.append(own_role.get(ph["hash"], "none"))
            rows.append({"participant": p, "condition": cond, "framework_set": len(fw),
                         "own_picks": len(own), "overlap": len(set(fw) & own),
                         "jaccard": rnd(j), "framework_certified": cert})
        if js:
            res[cond] = {"sessions": len(js), "mean_jaccard": rnd(st.mean(js)),
                         "median_jaccard": rnd(st.median(js)), "min": rnd(min(js)),
                         "role_kappa_photos": rnd(A.cohen_kappa(X, Y)), "photos": len(X)}
    return res, rows


# ------------------------------------------------------------------ role outcomes
def role_outcomes(S, dec, arm):
    rows = []
    for (p, c), s in sorted(S.items()):
        shot = {}
        for cap in s["captures"]:
            shot[cap["hash"]] = cap.get("shot_requested")
        for ph in s["first"]["photos"]:
            h = ph["hash"]
            if h not in dec:
                continue
            req = shot.get(h)
            if req not in ("main", "detail"):
                continue
            d = A._rebuild(h, dec)
            role = "hero_shot" if req == "main" else "detail_shot"
            rule = config.ROLE_RULES[role]
            hard = d.hard_rejected
            fails = []
            if hard:
                fails = ["hard_reject"]
            else:
                if d.fqs < rule["fqs_min"]:
                    fails.append("FQS")
                for k, v in rule["criteria_min"].items():
                    if d.semantic_scores.get(k, 0.0) < v:
                        fails.append({"subject_centering": "S1", "feature_visibility": "S2",
                                      "marketing_suitability": "S3"}.get(k, k))
            rows.append({"participant": p, "arm": arm[p], "condition": c, "requested": req,
                         "rule": role, "fqs": rnd(d.fqs), "tqs": rnd(d.tqs),
                         "met": _meets(role, d) and not hard, "failing": "+".join(fails)})
    return rows


def role_summary(rows):
    out = []
    for req in ("detail", "main"):
        for c in ("GUIDED", "UNGUIDED"):
            r = [x for x in rows if x["requested"] == req and x["condition"] == c]
            if not r:
                continue
            f = Counter(x["failing"] or "met" for x in r)
            out.append({"requested": req, "rule": r[0]["rule"], "condition": c, "n": len(r),
                        "met": sum(x["met"] for x in r),
                        "failing_gates": ", ".join(f"{k}:{v}" for k, v in sorted(f.items())
                                                   if k != "met") or "-"})
    return out


# ------------------------------------------------------------------ descriptive
def per_session(S, arm):
    rows = []
    for (p, c), s in sorted(S.items()):
        rows.append({"participant": p, "arm": arm[p], "condition": c,
                     "photos_captured": len(s["captures"]),
                     "photos_in_first_batch": len(s["first"]["photos"]) if s["first"] else 0,
                     "retakes": s["retakes"], "help_cards": s["help_cards"],
                     "setup_cards": s["setup_cards"], "restarts": s["restarts"],
                     "guidance_calls": s["guidance_calls"]})
    return rows


def cond_summary(rows):
    out = []
    for c in ("GUIDED", "UNGUIDED"):
        r = [x for x in rows if x["condition"] == c]
        if r:
            out.append({"condition": c, "sessions": len(r),
                        "retakes_total": sum(x["retakes"] for x in r),
                        "retakes_mean": rnd(st.mean(x["retakes"] for x in r)),
                        "photos_captured_mean": rnd(st.mean(x["photos_captured"] for x in r)),
                        "help_cards_total": sum(x["help_cards"] for x in r),
                        "setup_cards_total": sum(x["setup_cards"] for x in r)})
    return out


def md(rows):
    return A.md_table(rows)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    prim, sec, arm = manifest()
    rows = {r["hash"]: r for r in A.read_csv(SD / "rescored_photos.csv")}
    dec = json.loads((SD / "rescored_decisions.json").read_text(encoding="utf-8"))
    S1 = A.sessions(A.load_log(SD / "study_log.jsonl"))
    SL = A.sessions(A.load_log(SD / "study_log_last.jsonl"))
    for D in (S1, SL):
        for k in list(D):
            if k[0] not in sec:
                raise SystemExit(f"{k} is not an analysed key")
    summary, parts_md = {"primary": sorted(prim), "secondary": sorted(sec)}, []

    # ---- O2a, primary + secondary, rescored first attempt
    o2a_out, crit_tabs = {}, {}
    for label, codes in (("PRIMARY", prim), ("SECONDARY", sec)):
        M = means(sub(S1, codes), rows)
        res, tab, parts, d = o2a_exact(M)
        o2a_out[label] = {"fqs": res["fqs"], "tqs": res["tqs"]}
        part_rows = [dict(r, arm=arm[r["participant"]]) for r in tab["o2a_participants"]]
        write_csv(OUT / f"o2a_participants_{label.lower()}.csv", part_rows)
        write_csv(OUT / f"o2a_criteria_{label.lower()}.csv", tab["o2a_criterion_delta"])
        crit_tabs[label] = (part_rows, tab["o2a_criterion_delta"])
    summary["O2a"] = o2a_out

    # ---- sensitivity: last attempt and logged live FQS
    sens = []
    for src, S, fq in (("rescored, FIRST attempt (primary analysis)", S1, "rescored"),
                       ("rescored, LAST attempt", SL, "rescored"),
                       ("logged live FQS, first attempt", S1, "logged"),
                       ("logged live FQS, last attempt", SL, "logged")):
        for label, codes in (("PRIMARY", prim), ("SECONDARY", sec)):
            res, _, _, d = o2a_exact(means(sub(S, codes), rows, fq))
            e = res["fqs"]
            sens.append({"source": src, "set": label, "n": e.get("n_participants"),
                         "mean_diff": e.get("mean_difference"), "guided_better": e.get("guided_better"),
                         "p_one_sided": e.get("wilcoxon_p_one_sided"), "r": e.get("effect_size_r"),
                         "HL_95CI": ci_text(e)})
    write_csv(OUT / "sensitivity_last_and_logged.csv", sens)

    # ---- O2c
    o2c_out, o2c_rows = {}, []
    for label, codes in (("PRIMARY", prim), ("SECONDARY", sec)):
        r, rr = A.o2c(sub(S1, codes), dec)
        o2c_out[label] = r
        if label == "SECONDARY":
            o2c_rows = [dict(x, arm=arm[x["participant"]]) for x in rr]
    write_csv(OUT / "o2c_sets.csv", o2c_rows)
    summary["O2c"] = o2c_out

    # ---- O3
    o3_out, o3_rows = {}, []
    for label, codes in (("PRIMARY", prim), ("SECONDARY", sec)):
        r, rr = o3_rescored(sub(S1, codes), dec)
        o3_out[label] = r
        if label == "SECONDARY":
            o3_rows = [dict(x, arm=arm[x["participant"]]) for x in rr]
    o3_logged = {lab: A.o3(sub(S1, codes), SD)[0] for lab, codes in (("PRIMARY", prim), ("SECONDARY", sec))}
    write_csv(OUT / "o3_overlap.csv", o3_rows)
    summary["O3_rescored_framework_set"] = o3_out
    summary["O3_logged_framework_selection_sensitivity"] = o3_logged

    # ---- role outcomes
    ro = role_outcomes(S1, dec, arm)
    write_csv(OUT / "role_outcomes_photos.csv", ro)
    ro_sum = {lab: role_summary([x for x in ro if x["participant"] in codes])
              for lab, codes in (("PRIMARY", prim), ("SECONDARY", sec))}
    write_csv(OUT / "role_outcomes_summary.csv",
              [dict(set=k, **r) for k, v in ro_sum.items() for r in v])

    # ---- retakes
    ps = per_session(S1, arm)
    write_csv(OUT / "sessions_descriptive.csv", ps)
    cs = {lab: cond_summary([x for x in ps if x["participant"] in codes])
          for lab, codes in (("PRIMARY", prim), ("SECONDARY", sec))}

    # ---- weight sensitivity (cached/stored scores, no API calls)
    ws = []
    ws += W.evaluate("calibration", W.load_o1(HERE.parents[1] / "research/results/o1_calibration/per_image.csv"), W.set_o1)
    ws += W.evaluate("holdout", W.load_o1(HERE.parents[1] / "research/results/o1_holdout/per_image.csv"), W.set_o1)
    srows, _ = W.load_study(SD, SD / "study_log.jsonl")
    ws += W.evaluate(f"study photos (first attempts, {len({r['group'] for r in srows})} sessions)",
                     srows, W.set_study)
    write_csv(OUT / "weight_sensitivity.csv", ws)

    # ---- participant flow
    flow = [
        {"stage": "Recruited codes", "n": 14, "detail": "P01-P14"},
        {"stage": "No data exported", "n": 2, "detail": "P07, P08"},
        {"stage": "Exported", "n": 12, "detail": ""},
        {"stage": "Excluded (listed, never scored)", "n": 2,
         "detail": "P10 (P10_EXCLUDED: 1 own zip + 30 rows inside the P04-P10 zip), "
                   "P12 (P12_EXCLUDED: 3 zips)"},
        {"stage": "Analysed SECONDARY", "n": len(sec), "detail": ", ".join(sorted(sec))},
        {"stage": "Analysed PRIMARY (REMOTE)", "n": len(prim), "detail": ", ".join(sorted(prim))},
        {"stage": "STATION arm (secondary only)", "n": len(sec - prim),
         "detail": ", ".join(sorted(sec - prim))},
        {"stage": "Not applicable here", "n": 0,
         "detail": "no P00 rows and no 15 Oct P01 export in the supplied zips; P05 20261015_200152 "
                   "zip superseded by 20261016_151524"}]
    write_csv(OUT / "participant_flow.csv", flow)

    summary.update({"role_outcomes": ro_sum, "retakes": cs,
                    "claim_rule": "O2(a) assessable now; O2(b) waits for the judge panel; "
                                  "the claim cannot be assessed yet"})
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")

    # ---- report
    L = ["# Study analysis - non-panel parts (frozen plan; nothing changed after seeing results)\n",
         "Rescored with frozen v1.4.0, cache off, per-criterion median of 3 valid Gemini runs. "
         "First complete attempt per session. PRIMARY = REMOTE keys; SECONDARY = PRIMARY + STATION "
         "(P04, P06). Last-attempt photos and logged live FQS appear only in the sensitivity table.\n",
         "## Participant flow\n", md(flow)]
    for label in ("PRIMARY", "SECONDARY"):
        e = o2a_out[label]["fqs"]
        L += [f"\n## O2(a) {label} (n = {e.get('n_participants')})\n",
              "```json\n" + json.dumps(o2a_out[label], indent=1) + "\n```\n",
              md(crit_tabs[label][0]), f"\n### 11-criterion delta, guided minus unguided ({label})\n",
              md([dict(r, label="TARGETED" if r["group"] == "targeted" else "NON-TARGETED")
                  for r in crit_tabs[label][1]])]
    L += ["\n## Sensitivity (last attempt; logged live FQS)\n", md(sens),
          "\n## O2(c) certified at first attempt (photos before the first prompt)\n",
          "```json\n" + json.dumps(o2c_out, indent=1) + "\n```\n", md(o2c_rows),
          "\n## O3 vs own picks (framework set rebuilt from rescored scores)\n",
          "```json\n" + json.dumps(o3_out, indent=1) + "\n```\n", md(o3_rows),
          "\nSensitivity, logged live framework selection:\n```json\n"
          + json.dumps(o3_logged, indent=1) + "\n```\n",
          "\n## Role outcomes (requested photo vs the role rule: detail FQS>=0.60 & S2>=0.70; "
          "hero FQS>=0.75 & S1>=0.70 & S3>=0.70)\n"]
    for lab in ("PRIMARY", "SECONDARY"):
        L += [f"\n{lab}\n", md(ro_sum[lab])]
    L += ["\n## Retakes and photos (descriptive)\n", md(cs["SECONDARY"]), "\nPer session:\n", md(ps)]
    L += ["\n## Weight sensitivity (stored scores, no API calls)\n"]
    for ds in dict.fromkeys(r["dataset"] for r in ws):
        s_ = [r for r in ws if r["dataset"] == ds]
        nb = [r for r in s_ if r["scenario"] != "baseline"]
        worst = min(nb, key=lambda r: r["pass_unchanged_pct"])
        mj = min((r for r in nb if r["set_jaccard_vs_baseline"] is not None),
                 key=lambda r: r["set_jaccard_vs_baseline"], default=None)
        L += [f"\n### {ds}: n = {s_[0]['images']} images ({s_[0]['no_semantic_scores']} without semantic scores)\n",
              md([{k: r[k] for k in ("scenario", "pass_unchanged_pct", "role_unchanged_pct",
                                     "set_jaccard_vs_baseline", "passes_baseline",
                                     "passes_scenario")} for r in s_ if r["scenario"] != "baseline"
                  and (r["kind"] == "alpha_beta" or r is worst or r is mj)]),
              f"\nLeast stable verdicts: {worst['scenario']} ({worst['pass_unchanged_pct']} % unchanged). "
              f"Full table in weight_sensitivity.csv."]
    L += ["\n## Pre-registered claim\n", summary["claim_rule"] + "\n"]
    (OUT / "analysis.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
