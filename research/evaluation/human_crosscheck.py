"""
human_crosscheck.py  -  PART D: do the framework's orderings and sets agree with two human
photographers, on banks of KNOWN construction (2026-10-16). Pre-registered as Analysis Plan 7.

Inputs (--dir; the rating app's admin page writes the sheets, the builders write the keys)
  pair_key.csv                  pair_id, left_is (fault|clean), fault_type, fqs_fault, fqs_clean,
                                framework_pick (fault|clean|tie), source=holdout_real, ...
  crosscheck_pairs_sheet.csv    rater, pair_id, preferred (A|B|tie), strength     (A = left)
  set_selection.json            per kept set: pool and the framework's selected photos + roles
  set_photo_key.csv             set_id, number, path, sha256
  crosscheck_picks_sheet.csv    rater, set_id, role (main|angle1|angle2|detail), photo_no

7A  pairs of known construction (the fault photo SHOULD lose)
    * each rater's pick vs the construction; the raters' majority vs the construction;
    * the framework's ordering vs the construction;
    * PRIMARY: agreement of the framework ordering with the raters' majority on the pairs the
      raters did not tie: n, agreements, exact one-sided binomial against 0.5, Wilson 95 % CI.
      A framework tie counts as a disagreement (the conservative reading);
    * inter-rater % agreement and Cohen's kappa (three classes: clean / fault / tie);
    * by fault type (descriptive).
7B  sets: Jaccard of the framework's set with each photographer's four, role kappa and a
    chance baseline from ALL 4-photo subsets of the pool (exact enumeration; the permutation p is
    P(random Jaccard >= observed)) - COMPLETE framework sets only (>= 4 photos selected). Sets
    where the framework did not produce a full 4-photo set go in a separate coverage table and
    are never scored as Jaccard 0. Photographer-vs-photographer agreement is reported for ALL
    sets in its own table.

  python research/evaluation/human_crosscheck.py --dir <folder> --out <dir> [--label DRYRUN]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics as st
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from scipy import stats

ROLE_OF = {"main": "main", "angle1": "angle", "angle2": "angle", "detail": "detail"}
FW_ROLE = {"hero_shot": "main", "angle_shot": "angle", "detail_shot": "detail"}


def rnd(v, k=3):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), k)


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


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


def read_csv(p: Path) -> list:
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(p: Path, rows: list) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ----------------------------------------------------------------------------------- 7A
def decode_votes(sheet: list, key: dict) -> dict:
    """pair_id -> rater -> 'clean' | 'fault' | 'tie'."""
    out = defaultdict(dict)
    for r in sheet:
        pref = r["preferred"].strip().upper()
        if not pref or not r.get("rater", "").strip():
            continue
        k = key.get(r["pair_id"])
        if k is None:
            raise ValueError(f"pair {r['pair_id']} is not in pair_key.csv")
        if pref in ("TIE", "NO DIFFERENCE"):
            lab = "tie"
        elif pref in ("A", "B"):
            left = k["left_is"]
            right = "clean" if left == "fault" else "fault"
            lab = left if pref == "A" else right
        else:
            raise ValueError(f"answer {r['preferred']!r}: use A, B or tie")
        out[r["pair_id"]][r["rater"].strip()] = lab
    return out


def majority(votes: dict, n_raters: int) -> str:
    c = Counter(votes.values())
    if len(votes) < n_raters:
        return "incomplete"
    for lab in ("clean", "fault"):
        if c[lab] > n_raters / 2:
            return lab
    return "tie"


def analyse_pairs(key_rows: list, sheet: list) -> tuple:
    key = {r["pair_id"]: r for r in key_rows}
    votes = decode_votes(sheet, key)
    raters = sorted({r for v in votes.values() for r in v})
    rows, res = [], {"pairs": len(key_rows), "raters": raters}
    for pid, k in key.items():
        v = votes.get(pid, {})
        row = {"pair_id": pid, "fault_type": k["fault_type"], "product": k.get("product", ""),
               "left_is": k["left_is"], "fqs_fault": k["fqs_fault"], "fqs_clean": k["fqs_clean"],
               "framework_pick": k["framework_pick"],
               **{f"{r}_picks": v.get(r, "") for r in raters},
               "raters_majority": majority(v, len(raters)) if raters else ""}
        rows.append(row)
    res["framework_vs_construction"] = {
        "framework_clean": sum(r["framework_pick"] == "clean" for r in rows),
        "framework_fault": sum(r["framework_pick"] == "fault" for r in rows),
        "framework_tie": sum(r["framework_pick"] == "tie" for r in rows)}
    per = {}
    for r in raters:
        picks = [votes[p][r] for p in votes if r in votes[p]]
        non = [x for x in picks if x != "tie"]
        per[r] = {"answered": len(picks), "ties": len(picks) - len(non),
                  "picked_clean": sum(x == "clean" for x in non), "picked_fault": sum(x == "fault" for x in non),
                  "share_clean_of_non_ties": rnd(sum(x == "clean" for x in non) / len(non)) if non else None}
    res["per_rater_vs_construction"] = per
    comp = [r for r in rows if r["raters_majority"] not in ("", "incomplete")]
    res["majority_vs_construction"] = {
        "complete_pairs": len(comp),
        "majority_clean": sum(r["raters_majority"] == "clean" for r in comp),
        "majority_fault": sum(r["raters_majority"] == "fault" for r in comp),
        "majority_tie": sum(r["raters_majority"] == "tie" for r in comp)}
    nontied = [r for r in comp if r["raters_majority"] in ("clean", "fault")]
    agree = sum(r["framework_pick"] == r["raters_majority"] for r in nontied)
    n = len(nontied)
    prim = {"n_non_tied_pairs": n, "agreements": agree,
            "framework_ties_counted_as_disagreement": sum(r["framework_pick"] == "tie" for r in nontied)}
    if n:
        lo, hi = wilson(agree, n)
        prim.update({"agreement_rate": rnd(agree / n),
                     "exact_binomial_p_one_sided_vs_0.5": rnd(
                         stats.binomtest(agree, n, 0.5, alternative="greater").pvalue, 4),
                     "wilson_95ci": [rnd(lo), rnd(hi)]})
    res["PRIMARY_framework_vs_raters_majority"] = prim
    if len(raters) >= 2:
        r1, r2 = raters[:2]
        both = [(v[r1], v[r2]) for v in votes.values() if r1 in v and r2 in v]
        x, y = [a for a, _ in both], [b for _, b in both]
        nn = [(a, b) for a, b in both if a != "tie" and b != "tie"]
        res["inter_rater"] = {"raters": [r1, r2], "pairs": len(both),
                              "percent_agreement": rnd(100 * sum(a == b for a, b in both) / len(both), 1)
                              if both else None,
                              "cohen_kappa_3_class": rnd(cohen_kappa(x, y)),
                              "cohen_kappa_non_ties": rnd(cohen_kappa([a for a, _ in nn],
                                                                      [b for _, b in nn]))}
    by = defaultdict(list)
    for r in rows:
        by[r["fault_type"]].append(r)
    fault_rows = []
    for ft, rs in sorted(by.items()):
        nt = [r for r in rs if r["raters_majority"] in ("clean", "fault")]
        fault_rows.append({
            "fault_type": ft, "pairs": len(rs),
            "framework_picks_clean": sum(r["framework_pick"] == "clean" for r in rs),
            "raters_majority_clean": sum(r["raters_majority"] == "clean" for r in rs),
            "raters_majority_fault": sum(r["raters_majority"] == "fault" for r in rs),
            "raters_majority_tie_or_split": sum(r["raters_majority"] == "tie" for r in rs),
            "framework_agrees_with_majority": sum(r["framework_pick"] == r["raters_majority"] for r in nt),
            "non_tied_pairs": len(nt)})
    return res, rows, fault_rows


# ----------------------------------------------------------------------------------- 7B
def chance(pool_n: int, size: int, ref: set, pool: list, observed: float) -> tuple:
    """(expected Jaccard, P(J >= observed)) over every `size`-photo subset of the pool."""
    js = [jaccard(set(c), ref) for c in combinations(pool, size)]
    exp = st.mean(js)
    p = sum(j >= observed - 1e-12 for j in js) / len(js)
    return exp, p


def analyse_sets(selection: dict, key_rows: list, sheet: list) -> tuple:
    """Returns (summary, framework_rows, coverage_rows, expert_rows).

    * coverage_rows: one row per set - photos, how many the framework selected, why not complete.
      A set is COMPLETE when the framework produced a full 4-photo set (>= 4 selected). Sets that
      are not complete are NOT scored as Jaccard 0; they only appear here.
    * framework_rows: Jaccard of the framework's set with each photographer, role kappa and the
      permutation p - COMPLETE sets only. This is the primary 7B result.
    * expert_rows: photographer vs photographer for ALL sets (it does not depend on the framework).
    """
    num_to_path = {(r["set_id"], int(r["number"])): r["path"] for r in key_rows}
    picks = defaultdict(lambda: defaultdict(dict))        # set -> rater -> role -> path
    for r in sheet:
        n = str(r.get("photo_no", "")).strip()
        if n.isdigit() and r.get("rater", "").strip() and (r["set_id"], int(n)) in num_to_path:
            picks[r["set_id"]][r["rater"].strip()][r["role"]] = num_to_path[(r["set_id"], int(n))]
    raters = sorted({rt for s in picks.values() for rt in s})
    cover, fw_rows, ex_rows = [], [], []
    pooled_x, pooled_y = defaultdict(list), defaultdict(list)
    for sid, sel in selection.items():
        pool = sel["pool"]
        n_sel = len(sel["selected"])
        complete = n_sel >= 4
        reasons = sel.get("fail_reasons") or []
        cover.append({"set_id": sid, "photos": len(pool), "framework_selected": n_sel,
                      "complete_framework_set": complete,
                      "framework_certified": sel.get("certified"),
                      "reason": "complete 4-photo set" if complete else
                      ("framework selected " + str(n_sel) + " of the 4 photos needed: "
                       + (", ".join(reasons) or "not enough passing photos"))})
        fw = {s["path"] for s in sel["selected"]}
        fw_role = {s["path"]: FW_ROLE.get(s["role"], "none") for s in sel["selected"]}
        sets_ = {}
        for rt, roles in picks.get(sid, {}).items():
            if len(roles) == 4 and len(set(roles.values())) == 4:
                sets_[rt] = {p: ROLE_OF[ro] for ro, p in roles.items()}
        have = [r for r in raters if r in sets_]
        # photographer vs photographer: every set
        if len(have) >= 2:
            r1, r2 = have[:2]
            a, b = set(sets_[r1]), set(sets_[r2])
            j = jaccard(a, b)
            exp, p = chance(len(pool), len(b), a, pool, j)
            ex_rows.append({"set_id": sid, "pool_photos": len(pool),
                            "complete_framework_set": complete,
                            "jaccard_expert_expert": rnd(j), "chance_expected": rnd(exp),
                            "perm_p": rnd(p, 4),
                            "role_kappa_expert_expert": rnd(cohen_kappa(
                                [sets_[r1].get(q, "none") for q in pool],
                                [sets_[r2].get(q, "none") for q in pool]))})
        if not complete:
            continue
        row = {"set_id": sid, "pool_photos": len(pool), "framework_set_size": len(fw),
               "framework_certified": sel.get("certified")}
        js_fw = {}
        for rt in have:
            ph = set(sets_[rt])
            j = jaccard(fw, ph)
            exp, p = chance(len(pool), len(ph), fw, pool, j)
            row.update({f"jaccard_framework_{rt}": rnd(j), f"chance_expected_framework_{rt}": rnd(exp),
                        f"perm_p_framework_{rt}": rnd(p, 4),
                        f"role_kappa_framework_{rt}": rnd(cohen_kappa(
                            [fw_role.get(q, "none") for q in pool],
                            [sets_[rt].get(q, "none") for q in pool]))})
            js_fw[rt] = j
            for q in pool:
                pooled_x[rt].append(fw_role.get(q, "none"))
                pooled_y[rt].append(sets_[rt].get(q, "none"))
        if js_fw:
            row["mean_jaccard_framework_vs_experts"] = rnd(st.mean(js_fw.values()))
        ee = next((e for e in ex_rows if e["set_id"] == sid), None)
        if ee:
            row["jaccard_expert_expert"] = ee["jaccard_expert_expert"]
        fw_rows.append(row)
    complete_n = sum(1 for c in cover if c["complete_framework_set"])
    res = {"sets_total": len(selection), "sets_with_complete_framework_set": complete_n,
           "sets_without_complete_framework_set": [c["set_id"] for c in cover
                                                    if not c["complete_framework_set"]],
           "framework_comparison_uses": "complete sets only"}
    fe = [r["mean_jaccard_framework_vs_experts"] for r in fw_rows
          if "mean_jaccard_framework_vs_experts" in r]
    both = [(r["mean_jaccard_framework_vs_experts"], r["jaccard_expert_expert"]) for r in fw_rows
            if "mean_jaccard_framework_vs_experts" in r and r.get("jaccard_expert_expert") is not None]
    if fe:
        res["complete_sets_with_expert_picks"] = len(fe)
        res["mean_jaccard_framework_vs_expert"] = rnd(st.mean(fe))
    if both:
        res["same_sets_mean_jaccard_expert_vs_expert"] = rnd(st.mean(e for _, e in both))
        res["sets_where_framework_is_as_close_to_experts_as_they_are_to_each_other"] = \
            sum(1 for f, e in both if f >= e)
        res["of_sets"] = len(both)
    if ex_rows:
        res["all_sets_with_two_expert_sets"] = len(ex_rows)
        res["all_sets_mean_jaccard_expert_vs_expert"] = rnd(
            st.mean(e["jaccard_expert_expert"] for e in ex_rows))
        res["all_sets_mean_chance_jaccard"] = rnd(st.mean(e["chance_expected"] for e in ex_rows))
    exp_f = [r[k] for r in fw_rows for k in r if k.startswith("chance_expected_framework_")]
    if exp_f:
        res["mean_chance_jaccard_framework"] = rnd(st.mean(exp_f))
    res["role_kappa_framework_vs_expert_pooled_complete_sets"] = {
        rt: rnd(cohen_kappa(pooled_x[rt], pooled_y[rt])) for rt in raters if pooled_x[rt]}
    return res, fw_rows, cover, ex_rows


def md_table(rows: list) -> str:
    if not rows:
        return "_none_\n"
    keys = list(dict.fromkeys(k for r in rows for k in r))
    out = ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
    for r in rows:
        out.append("| " + " | ".join("" if r.get(k) is None else str(r.get(k)) for k in keys) + " |")
    return "\n".join(out) + "\n"


def main_panel(a) -> int:
    """--panel: the AI-judge panel (J1-J3, from ai_judges.py) stands in for the two raters.
    Panel decision = choice of >= 2 valid judges, else tie; judges below the known-answer gate
    (< 0.75 on the 24 holdout pairs) are excluded. The old two-rater analysis is untouched."""
    import panel as P
    pre = f"{a.label}_" if a.label else ""
    a.out.mkdir(parents=True, exist_ok=True)
    jd = a.judge_dir
    key = read_csv(a.dir / "pair_key.csv")
    pair_sheet = read_csv(jd / "crosscheck_pairs_sheet.csv")
    all_j = sorted({r["rater"] for r in pair_sheet})
    gate = P.known_answer_gate(key, decode_votes(pair_sheet, {r["pair_id"]: r for r in key}), all_j)
    ok = P.included_judges(gate)
    summary = {"gate": gate, "judges_in_panel": ok,
               "judges_excluded": sorted(set(all_j) - set(ok))}
    md = [f"> **{a.label}: test data only.**\n" if a.label else "",
          "# Human cross-check - AI-judge panel mode\n",
          "## Known-answer gate (24 holdout pairs, clean should win; ties = wrong)\n",
          "```json\n" + json.dumps(gate, indent=1) + "\n```\n"]
    if len(ok) < 2:
        md.append("**Fewer than 2 judges pass the gate: no panel majority can be formed.**\n")
    else:
        votes = decode_votes([r for r in pair_sheet if r["rater"] in ok], {r["pair_id"]: r for r in key})
        summary["agreement_7A"] = P.agreement_stats(votes, ok)
        summary["position_consistency_7A"] = P.position_consistency(
            P.read_consistency(jd, "bank_pairs"), ok)
        prow = P.panel_pair_rows(pair_sheet, ok)
        r7, rows, by = analyse_pairs(key, prow)
        r7["per_judge_vs_construction"] = analyse_pairs(
            key, [r for r in pair_sheet if r["rater"] in ok])[0]["per_rater_vs_construction"]
        summary["7A_panel"] = r7
        write_csv(a.out / f"{pre}panel_7a_pairs.csv", rows)
        write_csv(a.out / f"{pre}panel_7a_by_fault.csv", by)
        md += ["## 7A - framework vs PANEL majority\n", "```json\n" + json.dumps(summary, indent=1) + "\n```\n",
               "### By fault type\n", md_table(by), "### Pairs\n", md_table(rows)]
        need = [a.dir / n for n in ("set_selection.json", "set_photo_key.csv")]
        if all(p.exists() for p in need) and (jd / "crosscheck_picks_sheet.csv").exists():
            sel = json.loads(need[0].read_text(encoding="utf-8"))
            kr = read_csv(need[1])
            ps = read_csv(jd / "crosscheck_picks_sheet.csv")
            r7b, rows_b, cover, _ = analyse_sets(sel, kr, P.panel_set_rows(
                [r for r in ps if r["rater"] in ok], ok, "set_id"))
            per = {}
            for j in ok:
                rj = analyse_sets(sel, kr, [r for r in ps if r["rater"] == j])[0]
                per[j] = rj.get("mean_jaccard_framework_vs_expert")
            r7b["mean_jaccard_framework_vs_each_judge"] = per
            r7b["judge_vs_judge_jaccard"] = P.pairwise_set_jaccard(ps, ok, "set_id")
            r7b["position_consistency_7B"] = P.position_consistency(
                P.read_consistency(jd, "bank_sets"), ok)
            summary["7B_panel"] = r7b
            write_csv(a.out / f"{pre}panel_7b_sets.csv", rows_b)
            write_csv(a.out / f"{pre}panel_7b_framework_coverage.csv", cover)
            md += ["## 7B - framework vs PANEL sets (complete framework sets only)\n",
                   "```json\n" + json.dumps(r7b, indent=1) + "\n```\n", md_table(rows_b)]
    (a.out / f"{pre}panel_crosscheck_analysis.md").write_text("\n".join(md), encoding="utf-8")
    (a.out / f"{pre}panel_crosscheck_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--label", default="")
    ap.add_argument("--panel", action="store_true",
                    help="use the AI-judge panel sheets in --judge-dir instead of the two raters")
    ap.add_argument("--judge-dir", type=Path, help="ai_judges.py output folder (with --panel)")
    a = ap.parse_args()
    if a.panel:
        if not a.judge_dir:
            raise SystemExit("--panel needs --judge-dir")
        return main_panel(a)
    pre = f"{a.label}_" if a.label else ""
    a.out.mkdir(parents=True, exist_ok=True)
    md = []
    if a.label:
        md.append(f"> **{a.label}: test data only.** Nothing here may be reported.\n")
    md.append("# Human cross-check (Analysis Plan 7)\n")
    summary = {}
    if (a.dir / "pair_key.csv").exists() and (a.dir / "crosscheck_pairs_sheet.csv").exists():
        r7, rows, by = analyse_pairs(read_csv(a.dir / "pair_key.csv"),
                                     read_csv(a.dir / "crosscheck_pairs_sheet.csv"))
        summary["7A"] = r7
        write_csv(a.out / f"{pre}7a_pairs.csv", rows)
        write_csv(a.out / f"{pre}7a_by_fault.csv", by)
        md += ["## 7A - pairs of known construction (the fault photo should lose)\n",
               "```json\n" + json.dumps(r7, indent=1) + "\n```\n", "### By fault type\n",
               md_table(by), "### Pairs\n", md_table(rows)]
    else:
        md.append("## 7A\n_not collected (pair_key.csv or crosscheck_pairs_sheet.csv missing)_\n")
    if all((a.dir / n).exists() for n in ("set_selection.json", "set_photo_key.csv",
                                          "crosscheck_picks_sheet.csv")):
        r7b, rows_b, cover, ex_rows = analyse_sets(
            json.loads((a.dir / "set_selection.json").read_text(encoding="utf-8")),
            read_csv(a.dir / "set_photo_key.csv"), read_csv(a.dir / "crosscheck_picks_sheet.csv"))
        summary["7B"] = r7b
        write_csv(a.out / f"{pre}7b_framework_coverage.csv", cover)
        write_csv(a.out / f"{pre}7b_sets.csv", rows_b)
        write_csv(a.out / f"{pre}7b_expert_agreement_all_sets.csv", ex_rows)
        md += ["## 7B - sets\n",
               "### Framework coverage (which sets the framework could build a full 4-photo set for)\n",
               "Sets without a complete framework set are NOT scored as Jaccard 0; they appear only here.\n",
               md_table(cover),
               "### Framework vs photographers - complete framework sets only (primary)\n",
               "```json\n" + json.dumps(r7b, indent=1) + "\n```\n", md_table(rows_b),
               "### Photographer vs photographer - ALL sets\n", md_table(ex_rows)]
    else:
        md.append("## 7B\n_not collected_\n")
    (a.out / f"{pre}crosscheck_analysis.md").write_text("\n".join(md), encoding="utf-8")
    (a.out / f"{pre}crosscheck_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
