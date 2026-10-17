"""Human cross-check (2026-10-16): pair construction/ordering rule and the 7A / 7B analysis.
Synthetic ratings only; the real pair_key.csv is used when it exists (it is derived from
research/results/o1_holdout/per_image.csv, which is read, never re-scored)."""
import csv
import json
import subprocess
import sys
from itertools import combinations
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "evaluation"))
sys.path.insert(0, str(ROOT))

import crosscheck_pairs as cp     # noqa: E402
import human_crosscheck as hc     # noqa: E402

REAL_KEY = ROOT / "research" / "results" / "crosscheck" / "pair_key.csv"
HOLDOUT = ROOT / "research" / "results" / "o1_holdout" / "per_image.csv"


# ------------------------------------------------------------------ the ordering rule
def test_framework_ordering_rule():
    f = cp.framework_pick
    assert f(0.40, 0.60, 0.4, 0.5) == "clean"          # higher FQS wins
    assert f(0.70, 0.60, 0.4, 0.5) == "fault"
    assert f(0.60, 0.60, 0.4, 0.5) == "tie"
    assert f(None, 0.30, 0.9, 0.1) == "clean"          # no FQS is lower, whatever the TQS
    assert f(0.30, None, 0.1, 0.9) == "fault"
    assert f(None, None, 0.30, 0.50) == "clean"        # neither has FQS: higher TQS wins
    assert f(None, None, 0.60, 0.50) == "fault"
    assert f(None, None, None, 0.2) == "clean"         # no TQS counts as lowest
    assert f(None, None, 0.5, 0.5) == "tie"


@pytest.mark.skipif(not HOLDOUT.exists(), reason="holdout per_image.csv not present")
def test_pairs_are_24_four_per_fault_and_reproducible(tmp_path):
    a = cp.build(HOLDOUT, seed=7)
    b = cp.build(HOLDOUT, seed=7)
    assert a == b and len(a) == 24
    from collections import Counter
    assert Counter(r["fault_type"] for r in a) == {k: 4 for k in
                                                   ("ANGLE", "BLUR", "BRIGHT", "CLUTTER", "DARK", "OFFCENTRE")}
    assert len({r["product"] for r in a}) == 4 and len({r["pair_id"] for r in a}) == 24
    assert {r["source"] for r in a} == {"holdout_real"} and {r["left_is"] for r in a} == {"fault", "clean"}
    # another seed changes sides but never the pairing or the framework's ordering
    c = cp.build(HOLDOUT, seed=8)
    assert [r["left_is"] for r in a] != [r["left_is"] for r in c]
    assert {(r["product"], r["fault_type"], r["framework_pick"]) for r in a} == \
        {(r["product"], r["fault_type"], r["framework_pick"]) for r in c}


# ------------------------------------------------------------------ 7A
def _key(n=12):
    faults = ["ANGLE", "BLUR", "BRIGHT", "CLUTTER", "DARK", "OFFCENTRE"]
    return [{"pair_id": f"k{i:04d}", "left_is": ["fault", "clean"][i % 2], "fault_type": faults[i % 6],
             "fqs_fault": 0.4, "fqs_clean": 0.6, "framework_pick": "clean", "product": f"p{i % 4}"}
            for i in range(n)]


def _sheet(key, wanted: dict):
    """wanted: pair_id -> {rater: clean|fault|tie}; written as the letters a rater would type."""
    rows = []
    for k in key:
        for rater, lab in wanted.get(k["pair_id"], {}).items():
            if lab == "tie":
                pref = "tie"
            else:
                pref = "A" if k["left_is"] == lab else "B"
            rows.append({"rater": rater, "pair_id": k["pair_id"], "preferred": pref, "strength": "" if lab == "tie" else "4"})
    return rows


def test_7a_primary_agreement_and_kappa():
    key = _key(12)
    key[0]["framework_pick"] = "fault"                 # framework disagrees with raters here
    key[1]["framework_pick"] = "tie"
    w = {}
    for i, k in enumerate(key):
        lab = "clean"
        w[k["pair_id"]] = {"PH1": lab, "PH2": lab}
    w[key[2]["pair_id"]] = {"PH1": "tie", "PH2": "tie"}                    # tied: excluded
    w[key[3]["pair_id"]] = {"PH1": "clean", "PH2": "fault"}                # split -> tie
    w[key[4]["pair_id"]] = {"PH1": "fault", "PH2": "fault"}                # raters: fault wins
    res, rows, by = hc.analyse_pairs(key, _sheet(key, w))
    maj = {r["pair_id"]: r["raters_majority"] for r in rows}
    assert maj[key[2]["pair_id"]] == "tie" and maj[key[3]["pair_id"]] == "tie"
    assert maj[key[4]["pair_id"]] == "fault" and maj[key[5]["pair_id"]] == "clean"
    p = res["PRIMARY_framework_vs_raters_majority"]
    # non-tied: 12 - 2 (tie, split) = 10; framework agrees except pair 0 (fault vs clean),
    # pair 1 (tie), pair 4 (clean vs fault) -> 7 of 10
    assert (p["n_non_tied_pairs"], p["agreements"]) == (10, 7)
    assert p["framework_ties_counted_as_disagreement"] == 1
    from scipy import stats
    assert p["exact_binomial_p_one_sided_vs_0.5"] == pytest.approx(
        stats.binomtest(7, 10, 0.5, alternative="greater").pvalue, abs=1e-4)
    assert p["wilson_95ci"][0] < 0.7 < p["wilson_95ci"][1]
    ir = res["inter_rater"]
    assert ir["pairs"] == 12 and ir["percent_agreement"] == pytest.approx(100 * 11 / 12, abs=0.1)
    assert -1 <= ir["cohen_kappa_3_class"] <= 1
    assert res["per_rater_vs_construction"]["PH1"]["ties"] == 1
    assert {r["fault_type"] for r in by} == {"ANGLE", "BLUR", "BRIGHT", "CLUTTER", "DARK", "OFFCENTRE"}


def test_7a_missing_rater_answers_are_incomplete_not_ties():
    key = _key(4)
    w = {k["pair_id"]: {"PH1": "clean", "PH2": "clean"} for k in key}
    del w[key[0]["pair_id"]]["PH2"]
    res, rows, _ = hc.analyse_pairs(key, _sheet(key, w))
    assert rows[0]["raters_majority"] == "incomplete"
    assert res["PRIMARY_framework_vs_raters_majority"]["n_non_tied_pairs"] == 3


def test_decode_rejects_unknown_pairs_and_answers():
    key = {k["pair_id"]: k for k in _key(2)}
    with pytest.raises(ValueError):
        hc.decode_votes([{"rater": "PH1", "pair_id": "nope", "preferred": "A"}], key)
    with pytest.raises(ValueError):
        hc.decode_votes([{"rater": "PH1", "pair_id": "k0000", "preferred": "C"}], key)


# ------------------------------------------------------------------ 7B
def _sets():
    pool = [f"img{i}.jpg" for i in range(8)]
    sel = {"S1": {"pool": pool, "certified": True, "fail_reasons": [],
                  "selected": [{"path": pool[0], "role": "hero_shot"}, {"path": pool[1], "role": "angle_shot"},
                               {"path": pool[2], "role": "angle_shot"}, {"path": pool[3], "role": "detail_shot"}]}}
    key = [{"set_id": "S1", "number": i + 1, "path": p, "sha256": "0" * 64} for i, p in enumerate(pool)]
    return pool, sel, key


def _picks(rater, nums):
    return [{"rater": rater, "set_id": "S1", "role": r, "photo_no": n}
            for r, n in zip(("main", "angle1", "angle2", "detail"), nums)]


def test_7b_jaccard_chance_and_roles():
    pool, sel, key = _sets()
    sheet = _picks("PH1", [1, 2, 3, 4]) + _picks("PH2", [1, 2, 5, 6])
    res, rows, cover, ex = hc.analyse_sets(sel, key, sheet)
    r = rows[0]
    assert r["jaccard_framework_PH1"] == 1.0
    assert r["perm_p_framework_PH1"] == pytest.approx(1 / 70, abs=1e-4)      # only 1 of C(8,4)
    # PH2 shares {img0, img1} with the framework: |inter| 2, |union| 6
    assert r["jaccard_framework_PH2"] == pytest.approx(2 / 6, abs=1e-3)
    js = [hc.jaccard({pool[0], pool[1], pool[2], pool[3]}, set(c)) for c in combinations(pool, 4)]
    assert r["chance_expected_framework_PH2"] == pytest.approx(sum(js) / 70, abs=1e-3)
    assert r["perm_p_framework_PH2"] == pytest.approx(sum(j >= 2 / 6 - 1e-12 for j in js) / 70, abs=1e-4)
    assert r["jaccard_expert_expert"] == pytest.approx(hc.jaccard(
        {pool[0], pool[1], pool[2], pool[3]}, {pool[0], pool[1], pool[4], pool[5]}), abs=1e-3)
    assert r["role_kappa_framework_PH1"] == 1.0           # same photos in the same roles
    assert res["sets_with_complete_framework_set"] == 1 and cover[0]["complete_framework_set"]
    assert ex[0]["jaccard_expert_expert"] == r["jaccard_expert_expert"]
    assert res["mean_jaccard_framework_vs_expert"] == pytest.approx((1.0 + 2 / 6) / 2, abs=1e-3)


def test_7b_duplicate_or_incomplete_picks_are_ignored():
    pool, sel, key = _sets()
    sheet = _picks("PH1", [1, 1, 3, 4]) + _picks("PH2", [1, 2, 3, ""])
    res, rows, cover, ex = hc.analyse_sets(sel, key, sheet)
    assert "jaccard_framework_PH1" not in rows[0] and "jaccard_framework_PH2" not in rows[0]
    assert ex == []


# ------------------------------------------------------------------ the script end to end
@pytest.mark.skipif(not REAL_KEY.exists(), reason="real pair_key.csv not built")
def test_script_on_the_real_banks_with_synthetic_raters(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    (d / "pair_key.csv").write_bytes(REAL_KEY.read_bytes())
    key = list(csv.DictReader(open(REAL_KEY, encoding="utf-8")))
    rows = []
    for rater in ("PH1", "PH2"):
        for k in key:
            lab = "clean" if k["fault_type"] != "ANGLE" else "tie"
            pref = "tie" if lab == "tie" else ("A" if k["left_is"] == lab else "B")
            rows.append({"rater": rater, "pair_id": k["pair_id"], "preferred": pref,
                         "strength": "" if pref == "tie" else "3"})
    with open(d / "crosscheck_pairs_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rater", "pair_id", "preferred", "strength"])
        w.writeheader()
        w.writerows(rows)
    out = tmp_path / "out"
    r = subprocess.run([sys.executable, str(ROOT / "research" / "evaluation" / "human_crosscheck.py"),
                        "--dir", str(d), "--out", str(out), "--label", "TEST"],
                       capture_output=True, text=True, cwd=ROOT, timeout=300)
    assert r.returncode == 0, r.stderr[-1500:]
    s = json.loads((out / "TEST_crosscheck_summary.json").read_text())
    p = s["7A"]["PRIMARY_framework_vs_raters_majority"]
    # 4 ANGLE pairs are ties for both raters -> 20 non-tied; the raters say "clean" on every
    # one, so the framework agrees exactly where its own pick is clean
    fw_clean = sum(1 for k in key if k["fault_type"] != "ANGLE" and k["framework_pick"] == "clean")
    assert p["n_non_tied_pairs"] == 20 and p["agreements"] == fw_clean
    assert (out / "TEST_crosscheck_analysis.md").exists() and (out / "TEST_7a_by_fault.csv").exists()
    assert s["7A"]["inter_rater"]["percent_agreement"] == 100.0


def test_7b_incomplete_framework_sets_are_not_scored_as_zero():
    pool = [f"img{i}.jpg" for i in range(8)]
    sel = {
        "FULL": {"pool": pool, "certified": False, "fail_reasons": ["no_detail_shot"],
                 "selected": [{"path": p, "role": r} for p, r in zip(
                     pool[:4], ("hero_shot", "angle_shot", "angle_shot", "angle_shot"))]},
        "TWO": {"pool": pool, "certified": False,
                "fail_reasons": ["no_hero_shot", "insufficient_coverage"],
                "selected": [{"path": pool[0], "role": "angle_shot"},
                             {"path": pool[1], "role": "angle_shot"}]},
        "NONE": {"pool": pool, "certified": False, "fail_reasons": ["no_hero_shot"],
                 "selected": []}}
    key = [{"set_id": s, "number": i + 1, "path": p, "sha256": "0" * 64}
           for s in sel for i, p in enumerate(pool)]
    sheet = []
    for s in sel:
        sheet += [{"rater": "PH1", "set_id": s, "role": r, "photo_no": n}
                  for r, n in zip(("main", "angle1", "angle2", "detail"), (1, 2, 3, 4))]
        sheet += [{"rater": "PH2", "set_id": s, "role": r, "photo_no": n}
                  for r, n in zip(("main", "angle1", "angle2", "detail"), (1, 2, 5, 6))]
    res, rows, cover, ex = hc.analyse_sets(sel, key, sheet)
    assert [r["set_id"] for r in rows] == ["FULL"], "incomplete sets must not enter the primary table"
    assert {c["set_id"]: c["framework_selected"] for c in cover} == {"FULL": 4, "TWO": 2, "NONE": 0}
    assert {c["set_id"]: c["complete_framework_set"] for c in cover} == {
        "FULL": True, "TWO": False, "NONE": False}
    assert "no_hero_shot" in next(c for c in cover if c["set_id"] == "TWO")["reason"]
    assert res["sets_with_complete_framework_set"] == 1
    assert sorted(res["sets_without_complete_framework_set"]) == ["NONE", "TWO"]
    assert res["mean_jaccard_framework_vs_expert"] == pytest.approx((1.0 + 2 / 6) / 2, abs=1e-3)
    # photographers are compared on ALL three sets
    assert {e["set_id"] for e in ex} == {"FULL", "TWO", "NONE"}
    assert res["all_sets_with_two_expert_sets"] == 3
    # pooled role kappa uses the complete set only
    assert set(res["role_kappa_framework_vs_expert_pooled_complete_sets"]) == {"PH1", "PH2"}
