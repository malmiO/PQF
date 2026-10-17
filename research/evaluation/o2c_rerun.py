"""
o2c_rerun.py - re-run O2(c) ONLY, with the pre-registered definition of "first attempt":
photos taken BEFORE the first "Take the missing shots" (re-capture) prompt. help_card_shown is NOT
that prompt. The app does not log the prompt as an event: the results screen shows the
"Take the missing shots" button exactly when the batch is NOT certified, so the prompt time of a
session = the timestamp of its first batch_result whose gate.certified is False. If no such batch
exists in the session, ALL first-attempt photos are used. Photos replaced by a later retake are
dropped, as in analysis_study.prefix_hashes.

The earlier (help-card / setup-card / restart) version is recomputed with the unchanged
analysis_study.o2c and shown side by side. Nothing else in analysis_study is touched.

  python research/evaluation/o2c_rerun.py --dir <study_dir> --rescored <folder with rescored_decisions.json> --out <md>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import analysis_study as AS      # noqa: E402
from scipy import stats          # noqa: E402


def missing_shots_prefix(s: dict) -> tuple:
    """(hashes, cut timestamp or None, reason)."""
    first = next((e for e in s["events"] if e["event"] == "batch_result"), None)
    shown = bool(first) and not (first.get("gate") or {}).get("certified", False)
    cut = first["timestamp"] if shown else None
    caps = [c for c in s["captures"] if cut is None or c["timestamp"] < cut]
    replaced = {c["retake_of"] for c in caps if c.get("retake_of")}
    return [c["hash"] for c in caps if c["hash"] not in replaced], cut


def run(S: dict, dec: dict, prefix_fn) -> dict:
    """Same logic as analysis_study.o2c with a different cut."""
    from backend.pqf.pipeline import process_batch
    orig = AS.prefix_hashes
    AS.prefix_hashes = prefix_fn
    try:
        res, rows = AS.o2c(S, dec)
    finally:
        AS.prefix_hashes = orig
    return res, rows


def mcnemar(rows: list, keep: set) -> dict:
    pairs = [(r["guided_certified"], r["unguided_certified"]) for r in rows
             if r["participant"] in keep and "guided_certified" in r and "unguided_certified" in r]
    b = sum(1 for g, u in pairs if g and not u)
    c = sum(1 for g, u in pairs if u and not g)
    out = {"n": len(pairs), "both_certified": sum(1 for g, u in pairs if g and u),
           "neither": sum(1 for g, u in pairs if not g and not u),
           "guided_only": b, "unguided_only": c, "discordant_pairs": b + c,
           "guided_rate": round(sum(g for g, _ in pairs) / len(pairs), 3) if pairs else None,
           "unguided_rate": round(sum(u for _, u in pairs) / len(pairs), 3) if pairs else None}
    out["mcnemar_exact_p_two_sided"] = round(stats.binomtest(b, b + c, 0.5).pvalue, 4) if b + c else 1.0
    out["mcnemar_exact_p_one_sided_guided_better"] = (
        round(stats.binomtest(b, b + c, 0.5, alternative="greater").pvalue, 4) if b + c else 1.0)
    return out


def table(rows_old: list, rows_new: list, keep_primary: set) -> str:
    old = {r["participant"]: r for r in rows_old}
    out = ["| participant | set | GUIDED old (help card cut) | GUIDED new (missing-shots cut) | "
           "UNGUIDED old | UNGUIDED new | photos G/U old | photos G/U new |", "|---|---|---|---|---|---|---|---|"]
    yn = lambda v: "yes" if v else "no"
    for r in rows_new:
        o = old[r["participant"]]
        out.append(f"| {r['participant']} | {'primary' if r['participant'] in keep_primary else 'secondary only'} | "
                   f"{yn(o['guided_certified'])} | {yn(r['guided_certified'])} | "
                   f"{yn(o['unguided_certified'])} | {yn(r['unguided_certified'])} | "
                   f"{o['guided_photos_before_first_prompt']}/{o['unguided_photos_before_first_prompt']} | "
                   f"{r['guided_photos_before_first_prompt']}/{r['unguided_photos_before_first_prompt']} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--rescored", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    import csv
    log = AS.load_log(a.dir / "study_log.jsonl")
    S = AS.sessions(log)
    dec = json.loads((a.rescored / "rescored_decisions.json").read_text(encoding="utf-8"))
    man = list(csv.DictReader(open(a.manifest, newline="", encoding="utf-8")))
    primary = {r["code"] for r in man if r["primary"] == "True"}
    secondary = {r["code"] for r in man if r["secondary"] == "True"}
    # which photos does each definition need, and are they all already scored?
    need = {}
    for (p, c), s in sorted(S.items()):
        hs_old, cut_old = AS.prefix_hashes(s)
        hs_new, cut_new = missing_shots_prefix(s)
        need[(p, c)] = {"old": hs_old, "new": hs_new, "cut_old": cut_old, "cut_new": cut_new,
                        "unscored_new": [h for h in hs_new if h not in dec],
                        "unscored_old": [h for h in hs_old if h not in dec]}
    unscored = {k: v["unscored_new"] for k, v in need.items() if v["unscored_new"]}
    if unscored:
        print("PHOTOS NOT YET SCORED (rescore with rescore_study.py, 3 runs, cache off):", unscored)
        return 2
    res_old, rows_old = run(S, dec, AS.prefix_hashes)
    res_new, rows_new = run(S, dec, missing_shots_prefix)
    sess = []
    for (p, c), v in sorted(need.items()):
        first = next((e for e in S[(p, c)]["events"] if e["event"] == "batch_result"), None)
        sess.append({"participant": p, "condition": c,
                     "first_batch_certified": (first.get("gate") or {}).get("certified") if first else None,
                     "missing_shots_prompt_shown": v["cut_new"] is not None,
                     "photos_old_cut": len(v["old"]), "photos_new_cut": len(v["new"])})
    summary = {"definition": __doc__.strip().splitlines()[1:6],
               "primary": {"old": mcnemar(rows_old, primary), "new": mcnemar(rows_new, primary)},
               "secondary": {"old": mcnemar(rows_old, secondary), "new": mcnemar(rows_new, secondary)},
               "photos_needing_rescoring": 0}
    md = ["# O2(c) re-run - first attempt = photos before the first \"Take the missing shots\" prompt\n",
          "Only O2(c) was recomputed. Every other result is unchanged. `help_card_shown` is not the prompt.\n",
          "**How the prompt was found.** The study log has no event for the prompt itself (events: "
          "photo_captured, help_card_shown, setup_check_shown, capture_end, batch_result, own_picks, "
          "session_start, video_ready). The results screen shows the \"Take the missing shots\" button "
          "exactly when the batch is not certified (`results_screen.dart`), so the prompt time of a "
          "session is its first `batch_result` with `gate.certified = false`. Photos taken before that "
          "moment are the first attempt; where no such batch exists, all first-attempt photos are used. "
          "Photos replaced by a later retake are dropped (as before).\n",
          "**Rescoring.** Every photo needed by either definition already has a stored score (3 runs, "
          "median, cache off; rescored_decisions.json), so no photo was rescored.\n",
          "## Per participant, both versions side by side\n",
          table(rows_old, rows_new, primary), "\n",
          "## Sessions (new definition)\n",
          AS.md_table(sess),
          "\n## Exact McNemar, guided vs unguided, set certified\n",
          "```json\n" + json.dumps(summary, indent=1) + "\n```\n",
          "Old = cut at the first help card / setup card / restart (the earlier analysis_study version). "
          "New = cut at the first missing-shots prompt (pre-registered). Primary = 8 participants; "
          "secondary = all 10.\n"]
    a.out.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print(table(rows_old, rows_new, primary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
