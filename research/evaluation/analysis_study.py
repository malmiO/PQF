"""
analysis_study.py  -  O2, O3 and descriptive analyses of the REAL study data (plan of 2026-10-15,
replacing the 2026-10-07 version; the pre-registered rules of decisions.md 2026-10-03 stand).

Reads what the app and server actually record, nothing re-typed:
  study_log.jsonl                 the merged phone/server log (one participant = two sessions,
                                  GUIDED and UNGUIDED, ABBA order)
  rescored_photos.csv             from rescore_study.py --zip: all 11 criteria per photo
  rescored_decisions.json         same run: what is needed to rebuild a set offline
  rater_sheet.csv + blind_key.csv       the two photographers' blind A/B answers
                                        (rater, pair_id, preferred A|B|tie, strength 1-5)
  photographer_picks_sheet.csv + product_photo_key.csv    photographers' best photo per role
Any input that is missing is skipped and reported as "not collected".

O2a  per participant, mean FQS per condition (all photos of the FIRST /batch of the session);
     guided minus unguided; one-sided Wilcoxon signed-rank (H1 guided > unguided), r = Z/sqrt(N),
     Hodges-Lehmann estimate with an exact distribution-free 95 % CI (Walsh averages, signed-rank
     distribution). A per-criterion table (guided - unguided, 11 criteria) is labelled
     TARGETED (T1, T2, T3, S1: what live guidance steers) or NON-TARGETED.
O2b  pair outcome from two raters: both guided / both unguided / tie. Exact one-sided binomial on
     the non-ties; sensitivity with ties counted against guided; Cohen's kappa between raters on
     the three-way label; mean 1-5 strength.
O2c  set certified using only the photos taken BEFORE the first re-capture prompt (help card,
     setup card or restart); exact McNemar guided vs unguided.
O3   Jaccard of the framework's set with the participant's own four picks, per participant per
     condition; role kappa over photos; the same against the photographers' picks if collected.
     Retake counts per condition and sellers vs non-experts are DESCRIPTIVE only.
Inclusion: both sessions, same product, schema valid; partial participants are listed.

Usage:
  python research/evaluation/analysis_study.py --dir <folder with the files> --out <dir> [--label DRYRUN]
"""
from __future__ import annotations

import argparse
import json
import math
import statistics as st
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np
from scipy import stats

from evalcommon import read_csv, save_json, wilson, write_csv

TARGETED = {"t_sharpness": "T1", "t_exposure": "T2", "t_background": "T3",
            "s_subject_centering": "S1"}
CRITERIA = [("t_sharpness", "T1 Sharpness"), ("t_exposure", "T2 Exposure"),
            ("t_background", "T3 Background"), ("t_brisque", "T4 BRISQUE"),
            ("t_piqe", "T5 PIQE"), ("t_colorcast", "T6 Colour cast"),
            ("s_subject_centering", "S1 Centring"), ("s_feature_visibility", "S2 Feature visibility"),
            ("s_marketing_suitability", "S3 Marketing suitability"),
            ("s_angle_value", "S4 Angle value"), ("s_lighting_style_quality", "S5 Lighting and style")]
PROMPTS = ("help_card_shown", "setup_check_shown", "restart")
OWN_ROLE = {"main": "hero_shot", "angle1": "angle_shot", "angle2": "angle_shot",
            "detail": "detail_shot"}
# Documented app<->server contract gaps (found by the 2026-10-15 dry run). They are reported,
# not counted as a participant's data being invalid.
KNOWN_CONTRACT = ("device_model must be", "role must be a pipeline role",
                  "shot_requested must be one of")


# ----------------------------------------------------------------------------- statistics
def hl_estimate_and_ci(d: list) -> tuple:
    """Hodges-Lehmann estimate (median of Walsh averages) and the exact distribution-free
    ~95 % CI from the signed-rank distribution. For n < 6 no 95 % interval exists; the full
    range is returned with covered=False."""
    n = len(d)
    w = sorted((d[i] + d[j]) / 2 for i in range(n) for j in range(i, n))
    est = st.median(w)
    # P(T+ <= k) under H0: count subsets of {1..n} with sum <= k
    top = n * (n + 1) // 2
    counts = [0] * (top + 1)
    counts[0] = 1
    for r in range(1, n + 1):
        for s in range(top, r - 1, -1):
            counts[s] += counts[s - r]
    total = 2 ** n
    k, cum = -1, 0
    for s in range(top + 1):
        cum += counts[s]
        if 2 * cum / total <= 0.05:
            k = s
        else:
            break
    if k < 0:
        return est, (w[0], w[-1]), False
    return est, (w[k], w[len(w) - 1 - k]), True


def cohen_kappa(x: list, y: list) -> float:
    n = len(x)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = Counter(x), Counter(y)
    pe = sum(cx[c] * cy[c] for c in set(cx) | set(cy)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else float("nan")


def rnd(v, k=3):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), k)


# ----------------------------------------------------------------------------- loading
def load_log(p: Path) -> list:
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            if not str(e.get("product", "")).upper().startswith("SMOKE"):
                out.append(e)
    return out


def sessions(log: list) -> dict:
    """(participant, condition) -> first batch, own picks, captures, prompts, retakes.

    A participant may have repeated runs of a condition (restart, second product); the FIRST
    run of that condition that produced a batch is the session analysed, the rest are listed
    in `other_runs`."""
    by = defaultdict(list)
    for e in log:
        by[(e["participant"], e["condition"])].append(e)
    out = {}
    for k, ev in by.items():
        ev.sort(key=lambda e: e.get("timestamp", ""))
        runs = defaultdict(list)
        for e in ev:
            runs[(e.get("times") or {}).get("session_start", "")].append(e)
        ordered = sorted(runs)
        chosen = next((r for r in ordered if any(e["event"] == "batch_result" for e in runs[r])),
                      ordered[0])
        evs = runs[chosen]
        batches = [e for e in evs if e["event"] == "batch_result"]
        picks = next((e.get("own_picks", {}) for e in evs if e["event"] == "own_picks"), {})
        start = next((e for e in evs if e["event"] == "session_start"), {})
        caps = [e for e in evs if e["event"] == "photo_captured"]
        out[k] = {"events": evs, "first": batches[0] if batches else None,
                  "n_batches": len(batches), "picks": picks, "captures": caps,
                  "product": evs[0].get("product"), "group": start.get("group"),
                  "other_runs": len(ordered) - 1,
                  "retakes": sum(1 for c in caps if c.get("retake_of")),
                  "help_cards": sum(1 for e in evs if e["event"] == "help_card_shown"),
                  "setup_cards": sum(1 for e in evs if e["event"] == "setup_check_shown"),
                  "restarts": sum(1 for e in evs if e["event"] == "restart"),
                  "guidance_calls": len(next((e.get("guidance_ms") or []
                                              for e in evs if e["event"] == "capture_end"), []))}
    return out


def schema_status(events_by_participant: dict) -> dict:
    from backend.api import study_api
    res = {}
    for p, evs in events_by_participant.items():
        bad, known = [], []
        for e in evs:
            try:
                study_api.validate(e)
            except ValueError as ex:
                (known if any(m in str(ex) for m in KNOWN_CONTRACT) else bad).append(
                    f"{e.get('event')}: {ex}")
        res[p] = {"valid": not bad, "errors": bad, "contract_gaps": known}
    return res


# ----------------------------------------------------------------------------- O2a
def per_participant_means(S: dict, photo_rows: dict) -> dict:
    """participant -> condition -> {fqs, tqs, criterion...} means over the first batch's photos."""
    out = defaultdict(dict)
    for (p, c), s in S.items():
        if not s["first"] or not s["first"].get("photos"):
            continue
        ph = s["first"]["photos"]
        d = {"fqs": st.mean(x["fqs"] for x in ph), "tqs": st.mean(x["tqs"] for x in ph),
             "sqs": st.mean(x["sqs"] for x in ph), "n_photos": len(ph)}
        for col, _ in CRITERIA:
            v = [float(photo_rows[x["hash"]][col]) for x in ph
                 if x["hash"] in photo_rows and photo_rows[x["hash"]].get(col) not in (None, "")]
            d[col] = st.mean(v) if v else None
        out[p][c] = d
    return out


def o2a(M: dict) -> tuple:
    res, tables = {}, {}
    parts = sorted(p for p in M if "GUIDED" in M[p] and "UNGUIDED" in M[p])
    rows = []
    for metric in ("fqs", "tqs"):
        d = [M[p]["GUIDED"][metric] - M[p]["UNGUIDED"][metric] for p in parts]
        if metric == "fqs":
            rows = [{"participant": p, "guided_fqs": rnd(M[p]["GUIDED"]["fqs"]),
                     "unguided_fqs": rnd(M[p]["UNGUIDED"]["fqs"]),
                     "difference": rnd(M[p]["GUIDED"]["fqs"] - M[p]["UNGUIDED"]["fqs"]),
                     "photos_guided": M[p]["GUIDED"]["n_photos"],
                     "photos_unguided": M[p]["UNGUIDED"]["n_photos"]} for p in parts]
        if not d:
            res[metric] = {"n_participants": 0, "note": "no participant has both sessions"}
            continue
        entry = {"n_participants": len(d), "mean_difference": rnd(st.mean(d)),
                 "median_difference": rnd(st.median(d)), "guided_better": sum(x > 0 for x in d)}
        if len(d) >= 2 and any(x != 0 for x in d):
            w = stats.wilcoxon(d, alternative="greater")
            z = float(stats.norm.isf(min(max(w.pvalue, 1e-12), 1 - 1e-12)))
            est, ci, covered = hl_estimate_and_ci(d)
            entry.update({"wilcoxon_p_one_sided": rnd(w.pvalue, 4),
                          "effect_size_r": rnd(z / math.sqrt(len(d))),
                          "hodges_lehmann": rnd(est), "hl_95ci": [rnd(ci[0]), rnd(ci[1])],
                          "hl_ci_has_95_coverage": covered})
            if len(d) < 6:
                entry["note"] = "n < 6: the exact one-sided p cannot go below 0.03; descriptive"
        else:
            entry["note"] = "n < 2 (or all differences zero): no test is possible"
        res[metric] = entry
    # 11-criterion table, guided minus unguided
    crit = []
    for col, label in CRITERIA:
        g, u, dd = [], [], []
        for p in parts:
            a, b = M[p]["GUIDED"].get(col), M[p]["UNGUIDED"].get(col)
            if a is not None and b is not None:
                g.append(a)
                u.append(b)
                dd.append(a - b)
        crit.append({"criterion": label, "group": "targeted" if col in TARGETED else "non-targeted",
                     "n_participants": len(dd), "guided_mean": rnd(st.mean(g)) if g else None,
                     "unguided_mean": rnd(st.mean(u)) if u else None,
                     "delta_guided_minus_unguided": rnd(st.mean(dd)) if dd else None,
                     "guided_better": sum(x > 0 for x in dd) if dd else None})
    tables["o2a_participants"] = rows
    tables["o2a_criterion_delta"] = crit
    return res, tables


# ----------------------------------------------------------------------------- O2b
def o2b(folder: Path) -> tuple:
    rs, ks = folder / "rater_sheet.csv", folder / "blind_key.csv"
    if not rs.exists() or not ks.exists():
        return None, []
    key = {r["pair_id"]: r for r in read_csv(ks)}
    ans = [r for r in read_csv(rs) if r.get("preferred", "").strip() and r.get("rater", "").strip()]
    if not ans:
        return None, []
    votes = defaultdict(dict)       # pair -> rater -> (label, strength)
    for r in ans:
        pid = r["pair_id"]
        if pid not in key:
            raise SystemExit(f"pair {pid} is not in blind_key.csv")
        pref = r["preferred"].strip().upper()
        a_is = key[pid]["A_is"].strip().lower()
        if pref in ("TIE", "NO DIFFERENCE", "="):
            lab = "tie"
        elif pref in ("A", "B"):
            lab = a_is if pref == "A" else ("unguided" if a_is == "guided" else "guided")
        else:
            raise SystemExit(f"answer {r['preferred']!r}: use A, B or tie")
        s = str(r.get("strength", "")).strip()
        votes[pid][r["rater"].strip()] = (lab, int(s) if s.isdigit() and 1 <= int(s) <= 5 else None)
    raters = sorted({rt for v in votes.values() for rt in v})
    rows, outcome = [], {}
    for pid, v in sorted(votes.items()):
        labs = [x[0] for x in v.values()]
        if len(v) >= 2 and all(l == "guided" for l in labs):
            o = "both guided"
        elif len(v) >= 2 and all(l == "unguided" for l in labs):
            o = "both unguided"
        else:
            o = "tie"
        outcome[pid] = o
        rows.append({"pair_id": pid, "participant": key[pid].get("participant", ""),
                     "slot": key[pid].get("slot", ""), "outcome": o,
                     **{f"{rt}_vote": v.get(rt, ("", None))[0] for rt in raters},
                     **{f"{rt}_strength": v.get(rt, ("", None))[1] for rt in raters}})
    g = sum(o == "both guided" for o in outcome.values())
    u = sum(o == "both unguided" for o in outcome.values())
    t = sum(o == "tie" for o in outcome.values())
    res = {"pairs": len(outcome), "raters": raters, "both_guided": g, "both_unguided": u,
           "tie": t}
    if g + u:
        res["binomial_p_one_sided_non_ties"] = rnd(
            stats.binomtest(g, g + u, 0.5, alternative="greater").pvalue, 4)
        res["wilson_95ci_share_guided_of_non_ties"] = [rnd(x) for x in wilson(g, g + u)]
    res["sensitivity_ties_against_guided_p"] = rnd(
        stats.binomtest(g, len(outcome), 0.5, alternative="greater").pvalue, 4) if outcome else None
    if len(raters) >= 2:
        r1, r2 = raters[:2]
        both = [(v[r1][0], v[r2][0]) for v in votes.values() if r1 in v and r2 in v]
        res["cohen_kappa_between_raters"] = rnd(cohen_kappa([a for a, _ in both],
                                                            [b for _, b in both]))
        res["raters_agree_pairs"] = f"{sum(a == b for a, b in both)}/{len(both)}"
        if len(raters) > 2:
            res["note"] = f"{len(raters)} raters: kappa uses {r1} and {r2}; outcome needs all raters equal"
    sg = [s for v in votes.values() for l, s in v.values() if l == "guided" and s]
    su = [s for v in votes.values() for l, s in v.values() if l == "unguided" and s]
    res["mean_strength_votes_for_guided"] = rnd(st.mean(sg)) if sg else None
    res["mean_strength_votes_for_unguided"] = rnd(st.mean(su)) if su else None
    allv = sg + su
    res["mean_strength_all_preferences"] = rnd(st.mean(allv)) if allv else None
    if len({r.get("participant") for r in rows}) < len(rows):
        res["note_unit"] = "several pairs per participant: they are not independent"
    return res, rows


# ----------------------------------------------------------------------------- O2c
def _rebuild(h: str, dec: dict):
    from backend.pqf.combination import ImageDecision
    d = dec[h]
    obj = ImageDecision(tqs=d["tqs"], sqs=d["sqs"], fqs=d["fqs"], role=d["role"],
                        passed=d["passed"], hard_rejected=d["hard_rejected"],
                        semantic_scores=d["semantic_scores"], reason=d.get("reason", ""))
    sig = d.get("view_sig")
    setattr(obj, "view_sig", None if not sig else {
        "hash": np.asarray(sig["hash"]).astype(bool), "sil": np.asarray(sig["sil"]).astype(bool)})
    setattr(obj, "technical_scores", d.get("technical_scores", {}))
    setattr(obj, "path", h)
    return obj


def prefix_hashes(s: dict) -> tuple:
    """Photos captured before the first re-capture prompt, minus any a later capture in that
    prefix replaced. Returns (hashes, first_prompt_timestamp or None)."""
    prompts = [e["timestamp"] for e in s["events"] if e["event"] in PROMPTS]
    cut = min(prompts) if prompts else None
    caps = [c for c in s["captures"] if cut is None or c["timestamp"] < cut]
    replaced = {c["retake_of"] for c in caps if c.get("retake_of")}
    return [c["hash"] for c in caps if c["hash"] not in replaced], cut


def o2c(S: dict, dec: dict | None) -> tuple:
    if not dec:
        return {"note": "rescored_decisions.json not found: not computed"}, []
    from backend.pqf.pipeline import process_batch
    parts = sorted({p for p, _ in S})
    rows, pairs = [], []
    for p in parts:
        row = {"participant": p}
        ok = True
        for c in ("GUIDED", "UNGUIDED"):
            s = S.get((p, c))
            if not s:
                ok = False
                continue
            hs, cut = prefix_hashes(s)
            usable = [h for h in hs if h in dec]
            r = process_batch([_rebuild(h, dec) for h in usable]) if usable else None
            row[f"{c.lower()}_photos_before_first_prompt"] = len(usable)
            row[f"{c.lower()}_first_prompt"] = cut or "none"
            row[f"{c.lower()}_certified"] = bool(r and r.certified)
            row[f"{c.lower()}_fail_reasons"] = ",".join(r.recapture["fail_reasons"]) \
                if r and r.recapture else ""
        rows.append(row)
        if ok:
            pairs.append((row["guided_certified"], row["unguided_certified"]))
    if not pairs:
        return {"pairs": 0, "note": "no participant has both sessions"}, rows
    b = sum(1 for g, u in pairs if g and not u)
    c_ = sum(1 for g, u in pairs if u and not g)
    res = {"pairs": len(pairs), "both_certified": sum(1 for g, u in pairs if g and u),
           "neither": sum(1 for g, u in pairs if not g and not u),
           "guided_only": b, "unguided_only": c_,
           "guided_rate": rnd(st.mean(int(g) for g, _ in pairs)),
           "unguided_rate": rnd(st.mean(int(u) for _, u in pairs))}
    if b + c_:
        res["mcnemar_exact_p_two_sided"] = rnd(stats.binomtest(b, b + c_, 0.5).pvalue, 4)
        res["mcnemar_exact_p_one_sided_guided_better"] = rnd(
            stats.binomtest(b, b + c_, 0.5, alternative="greater").pvalue, 4)
    else:
        res["mcnemar_exact_p_two_sided"] = 1.0
        res["note"] = "no discordant pairs"
    return res, rows


# ----------------------------------------------------------------------------- O3
def o3(S: dict, folder: Path) -> tuple:
    res, rows = {}, []
    for cond in ("GUIDED", "UNGUIDED"):
        js, x_all, y_all = [], [], []
        for (p, c), s in sorted(S.items()):
            if c != cond or not s["first"] or not s["picks"]:
                continue
            fw_sel = s["first"].get("framework_selection", [])
            fw = {x["hash"] for x in fw_sel}
            own = set(s["picks"].values())
            j = jaccard(fw, own)
            js.append(j)
            fw_role = {x["hash"]: x["role"] for x in fw_sel}
            own_role = {h: OWN_ROLE[slot] for slot, h in s["picks"].items() if slot in OWN_ROLE}
            for ph in s["first"]["photos"]:
                x_all.append(fw_role.get(ph["hash"], "none"))
                y_all.append(own_role.get(ph["hash"], "none"))
            rows.append({"participant": p, "condition": cond, "framework_set": len(fw),
                         "own_picks": len(own), "overlap": len(fw & own),
                         "jaccard_framework_vs_own": rnd(j)})
        if js:
            res[f"participants_{cond.lower()}"] = {
                "sessions": len(js), "mean_jaccard": rnd(st.mean(js)),
                "median_jaccard": rnd(st.median(js)), "min": rnd(min(js)),
                "role_kappa_photos": rnd(cohen_kappa(x_all, y_all))}
    pg = res.get("participants_guided")
    res["preregistered_failure_mean_jaccard_below_0.50"] = (
        pg["mean_jaccard"] < 0.50) if pg else None
    # photographers' picks (best photo per role, per product)
    ps, pk = folder / "photographer_picks_sheet.csv", folder / "product_photo_key.csv"
    if ps.exists() and pk.exists():
        by_no = {(r["product"], int(r["number"])): r["sha256"] for r in read_csv(pk)}
        picks = defaultdict(set)
        for r in read_csv(ps):
            n = str(r.get("photo_no", "")).strip()
            if n.isdigit() and (r["product"], int(n)) in by_no:
                picks[(r["rater"], r["product"])].add(by_no[(r["product"], int(n))])
        ph = []
        for (rater, product), hs in sorted(picks.items()):
            for (p, c), s in sorted(S.items()):
                if s["product"] != product or not s["first"]:
                    continue
                fw = {x["hash"] for x in s["first"].get("framework_selection", [])}
                own = set(s["picks"].values())
                ph.append({"rater": rater, "product": product, "participant": p, "condition": c,
                           "jaccard_framework_vs_photographer": rnd(jaccard(fw, hs)),
                           "jaccard_own_vs_photographer": rnd(jaccard(own, hs))})
        if ph:
            res["photographers"] = {
                "rows": len(ph),
                "mean_jaccard_framework": rnd(st.mean(r["jaccard_framework_vs_photographer"]
                                                      for r in ph)),
                "mean_jaccard_own_picks": rnd(st.mean(r["jaccard_own_vs_photographer"]
                                                      for r in ph))}
            rows += [dict(r, source="photographer") for r in ph]
    return res, rows


# ----------------------------------------------------------------------------- descriptive
def descriptive(S: dict, M: dict) -> tuple:
    ret = []
    for cond in ("GUIDED", "UNGUIDED"):
        ss = [s for (p, c), s in S.items() if c == cond]
        if not ss:
            continue
        ret.append({"condition": cond, "sessions": len(ss),
                    "retakes_mean": rnd(st.mean(s["retakes"] for s in ss)),
                    "retakes_total": sum(s["retakes"] for s in ss),
                    "help_cards_total": sum(s["help_cards"] for s in ss),
                    "setup_cards_total": sum(s["setup_cards"] for s in ss),
                    "restarts_total": sum(s["restarts"] for s in ss),
                    "guidance_calls_total": sum(s["guidance_calls"] for s in ss)})
    grp = defaultdict(list)
    for p in M:
        if "GUIDED" in M[p] and "UNGUIDED" in M[p]:
            g = next((S[(p, c)]["group"] for c in ("GUIDED", "UNGUIDED")
                      if (p, c) in S and S[(p, c)]["group"]), None)
            if not g:       # the pre-registered mapping, when the app did not record a group
                try:
                    g = "seller" if int(p[1:]) <= 5 else "non_expert"
                except ValueError:
                    g = "unknown"
            grp[g].append(M[p]["GUIDED"]["fqs"] - M[p]["UNGUIDED"]["fqs"])
    groups = [{"group": g, "participants": len(d), "mean_fqs_difference": rnd(st.mean(d)),
               "median_fqs_difference": rnd(st.median(d))} for g, d in sorted(grp.items())]
    return ret, groups


def inclusion(S: dict, schema: dict) -> list:
    rows = []
    for p in sorted({p for p, _ in S}):
        g, u = S.get((p, "GUIDED")), S.get((p, "UNGUIDED"))
        both = bool(g and u and g["first"] and u["first"])
        same = bool(g and u and g["product"] == u["product"])
        sc = schema.get(p, {})
        ok = both and same and sc.get("valid", False)
        why = [] if ok else [x for x, c in (("a session is missing or has no batch", both),
                                              ("different product in the two sessions", same or not (g and u)),
                                              ("schema invalid", sc.get("valid", False))) if not c]
        rows.append({"participant": p, "guided_session": bool(g and g["first"]),
                     "unguided_session": bool(u and u["first"]), "same_product": same,
                     "schema_valid": sc.get("valid", False),
                     "app_server_contract_gaps": len(sc.get("contract_gaps", [])),
                     "included": ok, "reason_excluded": "; ".join(why)})
    return rows


# ----------------------------------------------------------------------------- report
def md_table(rows: list) -> str:
    if not rows:
        return "_none_\n"
    keys = list(dict.fromkeys(k for r in rows for k in r))
    out = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(k) is None else str(r.get(k)) for k in keys) + " |")
    return "\n".join(out) + "\n"


# ----------------------------------------------------------------------------- panel mode
def panel_mode(a, S: dict, included: set, pre: str) -> dict:
    """--panel: the AI-judge panel (J1-J3, ai_judges.py output in --judge-dir) is analysed in
    the same way as the two photographers. Panel decision = choice of >= 2 valid judges, else tie.
    Judges below the known-answer gate (gate.json from the 24 holdout pairs) are excluded."""
    import panel as P
    jd = a.judge_dir
    if not (jd / "gate.json").exists():
        raise SystemExit("--panel needs judge-dir/gate.json (run ai_judges.py --source bank_pairs first)")
    gate = P.load_gate(jd / "gate.json")
    ok = P.included_judges(gate)
    res = {"gate": gate, "judges_in_panel": ok, "judges_excluded": sorted(set(gate) - set(ok))}
    if len(ok) < 2:
        res["note"] = "fewer than 2 judges pass the gate: no panel majority"
        return res
    # O2b: participant pairs
    if (jd / "rater_sheet.csv").exists() and (a.dir / "blind_key.csv").exists():
        key = {r["pair_id"]: r for r in read_csv(a.dir / "blind_key.csv")}
        sheet = read_csv(jd / "rater_sheet.csv")
        prow = P.panel_pair_rows(sheet, ok)
        lab_of = {}
        votes = defaultdict(dict)
        for r in sheet:
            pref = r["preferred"].strip().upper()
            if r["rater"] in ok and pref and r["pair_id"] in key:
                a_is = key[r["pair_id"]]["A_is"].strip().lower()
                b_is = "unguided" if a_is == "guided" else "guided"
                votes[r["pair_id"]][r["rater"]] = "tie" if pref in ("TIE", "NO DIFFERENCE") else (
                    a_is if pref == "A" else b_is)
        rows = []
        for r in prow:
            k = key[r["pair_id"]]
            a_is = k["A_is"].strip().lower()
            lab = "tie" if r["preferred"] == "tie" else (
                a_is if r["preferred"] == "A" else ("unguided" if a_is == "guided" else "guided"))
            lab_of[r["pair_id"]] = lab
            rows.append({"pair_id": r["pair_id"], "participant": k.get("participant", ""),
                         "slot": k.get("slot", ""), "panel_outcome": lab,
                         **{f"{j}_vote": votes[r["pair_id"]].get(j, "missing") for j in ok}})
        g = sum(v == "guided" for v in lab_of.values())
        u = sum(v == "unguided" for v in lab_of.values())
        t = sum(v == "tie" for v in lab_of.values())
        o = {"pairs": len(lab_of), "panel_guided": g, "panel_unguided": u, "panel_tie": t}
        if g + u:
            o["binomial_p_one_sided_non_ties"] = rnd(stats.binomtest(g, g + u, 0.5, alternative="greater").pvalue, 4)
            o["wilson_95ci_share_guided_of_non_ties"] = [rnd(x) for x in wilson(g, g + u)]
        if lab_of:
            o["sensitivity_ties_against_guided_p"] = rnd(
                stats.binomtest(g, len(lab_of), 0.5, alternative="greater").pvalue, 4)
        o["agreement"] = P.agreement_stats(votes, ok)
        o["position_consistency"] = P.position_consistency(P.read_consistency(jd, "blind_pairs"), ok)
        res["O2b_panel"] = o
        write_csv(a.out / f"{pre}panel_o2b_pairs.csv", rows) if rows else None
    else:
        res["O2b_panel"] = "not collected"
    # O3: panel's four picks per product vs the framework
    ps, pk = jd / "photographer_picks_sheet.csv", a.dir / "product_photo_key.csv"
    if not pk.exists():
        pk = a.dir / "packs" / "product_photo_key.csv"
    if ps.exists() and pk.exists():
        by_no = {(r["product"], int(r["number"])): r["sha256"] for r in read_csv(pk)}
        sheet = read_csv(ps)
        out = []
        for who, srows in (("PANEL", P.panel_set_rows(sheet, ok, "product")),
                           *[(j, [r for r in sheet if r["rater"] == j]) for j in ok]):
            picks = defaultdict(set)
            for r in srows:
                n = str(r.get("photo_no", "")).strip()
                if n.isdigit() and (r["product"], int(n)) in by_no:
                    picks[r["product"]].add(by_no[(r["product"], int(n))])
            for product, hs in sorted(picks.items()):
                for (p, c), s_ in sorted(S.items()):
                    if p not in included or s_["product"] != product or not s_["first"]:
                        continue
                    fw = {x["hash"] for x in s_["first"].get("framework_selection", [])}
                    own = set(s_["picks"].values())
                    out.append({"rater": who, "product": product, "participant": p, "condition": c,
                                "picked": len(hs),
                                "jaccard_framework_vs_judge": rnd(jaccard(fw, hs)),
                                "jaccard_own_vs_judge": rnd(jaccard(own, hs))})
        o3p = {}
        for who in ["PANEL"] + ok:
            rr = [r for r in out if r["rater"] == who]
            if rr:
                o3p[who] = {"rows": len(rr),
                            "mean_jaccard_framework": rnd(st.mean(r["jaccard_framework_vs_judge"] for r in rr)),
                            "mean_jaccard_own_picks": rnd(st.mean(r["jaccard_own_vs_judge"] for r in rr))}
        o3p["judge_vs_judge_jaccard"] = P.pairwise_set_jaccard(sheet, ok, "product")
        o3p["position_consistency"] = P.position_consistency(P.read_consistency(jd, "packs_sets"), ok)
        res["O3_panel"] = o3p
        write_csv(a.out / f"{pre}panel_o3_overlap.csv", out) if out else None
    else:
        res["O3_panel"] = "not collected"
    res["claim_measurably_improves_by_panel"] = bool(
        isinstance(res["O2b_panel"], dict) and res["O2b_panel"].get("binomial_p_one_sided_non_ties", 1) < 0.05)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="", help="e.g. DRYRUN: banner and file-name prefix")
    ap.add_argument("--rescored", type=Path, help="folder with rescored_photos.csv/decisions.json")
    ap.add_argument("--panel", action="store_true",
                    help="also analyse the AI-judge panel sheets in --judge-dir (old output unchanged)")
    ap.add_argument("--judge-dir", type=Path, help="ai_judges.py output folder (with --panel)")
    a = ap.parse_args()
    if a.panel and not a.judge_dir:
        raise SystemExit("--panel needs --judge-dir")
    pre = f"{a.label}_" if a.label else ""
    log_path = a.dir / "study_log.jsonl"
    log = load_log(log_path)
    S = sessions(log)
    rdir = a.rescored or a.dir
    photo_rows = {r["hash"]: r for r in read_csv(rdir / "rescored_photos.csv")} \
        if (rdir / "rescored_photos.csv").exists() else {}
    dec = json.loads((rdir / "rescored_decisions.json").read_text(encoding="utf-8")) \
        if (rdir / "rescored_decisions.json").exists() else None
    ev_by_p = defaultdict(list)
    for e in log:
        ev_by_p[e["participant"]].append(e)
    schema = schema_status(ev_by_p)
    inc = inclusion(S, schema)
    included = {r["participant"] for r in inc if r["included"]}
    M = per_participant_means({k: v for k, v in S.items() if k[0] in included}, photo_rows)

    O2a, tables = o2a(M)
    O2b, pair_rows = o2b(a.dir)
    O2c, set_rows = o2c({k: v for k, v in S.items() if k[0] in included}, dec)
    O3, o3_rows = o3({k: v for k, v in S.items() if k[0] in included}, a.dir)
    retakes, groups = descriptive({k: v for k, v in S.items() if k[0] in included}, M)
    claim = bool(O2a.get("fqs", {}).get("wilcoxon_p_one_sided", 1) < 0.05 and O2b
                 and O2b.get("binomial_p_one_sided_non_ties", 1) < 0.05)

    a.out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("o2a_participants", tables["o2a_participants"]),
                       ("o2a_criterion_delta", tables["o2a_criterion_delta"]),
                       ("o2b_pairs", pair_rows), ("o2c_sets", set_rows), ("o3_overlap", o3_rows),
                       ("retakes_by_condition", retakes), ("groups", groups),
                       ("inclusion", inc)):
        write_csv(a.out / f"{pre}{name}.csv", rows) if rows else None
    summary = {"label": a.label, "participants_in_log": len({p for p, _ in S}),
               "included": sorted(included), "O2a": O2a, "O2b": O2b or "not collected",
               "O2c": O2c, "O3": O3, "claim_measurably_improves": claim,
               "schema": {p: {"valid": v["valid"], "errors": v["errors"],
                              "contract_gaps": sorted(set(v["contract_gaps"]))}
                          for p, v in schema.items()}}
    save_json(a.out / f"{pre}study_summary.json", summary)

    md = []
    if a.label:
        md += [f"> **{a.label}: test data only.** Conditions were relabelled to exercise the "
               "pipeline. Nothing here may be reported.\n"]
    md += ["# Study analysis (O2, O3, descriptive)\n",
           f"Log: `{log_path}`. Participants in log: {len({p for p, _ in S})}; included: "
           f"{len(included)}.\n", "## Inclusion\n", md_table(inc)]
    gaps = sorted({g for v in schema.values() for g in v["contract_gaps"]})
    if gaps:
        md += ["\nApp/server contract gaps seen (reported, not counted as invalid data):\n"]
        md += [f"- {g}" for g in gaps]
        md += [""]
    md += ["\n## O2a - framework score, guided vs unguided (within participant)\n",
           "```json\n" + json.dumps(O2a, indent=1) + "\n```\n",
           "Participant means (all photos of the first /batch):\n",
           md_table(tables["o2a_participants"]),
           "\n### 11-criterion delta (guided minus unguided)\n",
           "TARGETED = T1, T2, T3, S1 (what live guidance steers); the rest are NON-TARGETED.\n",
           md_table(tables["o2a_criterion_delta"]),
           "\n## O2b - blind preference (2 photographers)\n",
           ("```json\n" + json.dumps(O2b, indent=1) + "\n```\n" if O2b else "_not collected_\n"),
           md_table(pair_rows),
           "\n## O2c - set certified using only photos before the first re-capture prompt\n",
           "```json\n" + json.dumps(O2c, indent=1) + "\n```\n", md_table(set_rows),
           "\n## O3 - framework set vs people\n",
           "```json\n" + json.dumps(O3, indent=1) + "\n```\n", md_table(o3_rows),
           "\n## Retakes and prompts per condition (descriptive)\n", md_table(retakes),
           "\n## Sellers vs non-experts (descriptive)\n", md_table(groups),
           f"\n## Pre-registered claim\n\n\"Guided capture measurably improves\" requires O2a "
           f"p < 0.05 AND O2b p < 0.05: **{'MET' if claim else 'not met'}**.\n"]
    (a.out / f"{pre}analysis.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("included", "O2a", "O2b", "O2c", "O3")},
                     indent=1, default=str))
    print(f"-> {a.out / (pre + 'analysis.md')}")
    if a.panel:
        pres = panel_mode(a, {k: v for k, v in S.items() if k[0] in included}, included, pre)
        save_json(a.out / f"{pre}panel_study_summary.json", pres)
        (a.out / f"{pre}analysis_panel.md").write_text(
            ("> **" + a.label + ": test data only.**\n\n" if a.label else "")
            + "# Study analysis - AI-judge panel mode\n\n```json\n"
            + json.dumps(pres, indent=1, default=str) + "\n```\n", encoding="utf-8")
        print(json.dumps(pres, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
