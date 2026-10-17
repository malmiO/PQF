"""Dry-run chain (2026-10-15): analysis_study, sus_score, weight sensitivity.

All data here is SYNTHETIC and lives in tmp_path; it exercises the code paths that a
single-participant dry run cannot (tests, kappa, McNemar, group split)."""
import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "research" / "evaluation"))
sys.path.insert(0, str(ROOT))

import analysis_study as an          # noqa: E402
import sus_score as sus              # noqa: E402
import weight_sensitivity as ws      # noqa: E402


def H(i):
    return f"{i:064x}"


def test_hodges_lehmann_exact_ci_matches_known_values():
    d = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    est, ci, covered = an.hl_estimate_and_ci(d)
    assert covered and est == pytest.approx(0.55)
    # n = 10: the two-sided 5 % critical value of the signed-rank statistic is 8, so the CI
    # runs from the 9th smallest to the 9th largest Walsh average
    w = sorted((d[i] + d[j]) / 2 for i in range(10) for j in range(i, 10))
    assert ci == (w[8], w[-9])
    _, ci5, covered5 = an.hl_estimate_and_ci([0.1, 0.2, 0.3, 0.4, 0.5])
    assert not covered5 and ci5 == (0.1, 0.5)        # n < 6: no 95 % interval exists


def test_cohen_kappa_three_classes():
    x = ["guided", "guided", "tie", "unguided"]
    assert an.cohen_kappa(x, x) == pytest.approx(1.0)
    assert an.cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)


def test_sus_scoring_and_summary(tmp_path):
    assert sus.respondent_score([5, 1] * 5) == 100.0
    assert sus.respondent_score([3] * 10) == 50.0
    assert sus.respondent_score([1, 5] * 5) == 0.0
    p = tmp_path / "form.csv"
    hdr = ["Timestamp"] + [f"{i}. item" for i in range(1, 11)] + ["Age", "Comment"]
    rows = [["t1"] + [5, 1] * 5 + ["25", "great"],
            ["t2"] + [3] * 10 + ["31", ""],
            ["t3"] + [4, 2] * 5 + ["", "ok"]]        # 4,2 -> (3 + 3) * 5 = 30 * 2.5 = 75
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(hdr)
        w.writerows(rows)
    r = sus.score_csv(p)
    assert [s["sus"] for s in r["scores"]] == [100.0, 50.0, 75.0]
    s = sus.summarise(r["scores"])
    assert s["n"] == 3 and s["mean"] == 75.0 and s["sd"] == 25.0
    assert s["ci95"][0] < 75 < s["ci95"][1] and s["adjective"] == "Good"
    # no numbered headers: falls back to the first ten columns of 1-5 answers
    p2 = tmp_path / "plain.csv"
    with open(p2, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["When", "How easy was it"] + [f"Another question {i}" for i in range(2, 11)]
                   + ["Age"])
        w.writerow(["t", 5, 1, 5, 1, 5, 1, 5, 1, 5, 1, "30"])
    assert sus.score_csv(p2)["scores"][0]["sus"] == 100.0


def _synthetic_study(tmp_path, n=10):
    """n participants, both conditions, 4 photos each; guided sets certify, unguided do not."""
    log, photos, dec = [], [], {}
    k = 0
    for i in range(1, n + 1):
        p = f"P{i:02d}"
        for cond in ("GUIDED", "UNGUIDED"):
            t0 = (f"2026-10-20T10:{i:02d}:00.000Z" if cond == "GUIDED"
                  else f"2026-10-20T11:{i:02d}:00.000Z")
            common = {"participant": p, "condition": cond, "product": f"K{i}",
                      "times": {"session_start": t0}}
            log.append({**common, "event": "session_start", "timestamp": t0,
                        "group": "seller" if i <= 5 else "non_expert", "session": 1})
            hashes = []
            strong = cond == "GUIDED"
            for slot in ("main", "angle1", "angle2", "detail"):
                k += 1
                h = H(k)
                hashes.append(h)
                log.append({**common, "event": "photo_captured", "hash": h,
                            "shot_requested": slot, "retake_of": None, "source": "in_app",
                            "timestamp": f"2026-10-20T10:{i:02d}:{10 + len(hashes):02d}.000Z"})
                role = {"main": "hero_shot", "angle1": "angle_shot", "angle2": "angle_shot",
                        "detail": "detail_shot"}[slot]
                sem = {"subject_centering": 0.9 if strong else 0.5,
                       "feature_visibility": 0.8 if strong else 0.4,
                       "marketing_suitability": 0.9 if strong else 0.5,
                       "angle_value": 0.75 if strong else 0.5,
                       "lighting_style_quality": 0.8}
                tech = {"sharpness": 0.9 if strong else 0.5, "exposure": 0.9,
                        "background": 0.9 if strong else 0.6,
                        "brisque": 0.2, "piqe": 0.6, "colorcast": 0.9}
                tqs = (0.27 * tech["sharpness"] + 0.22 * tech["exposure"]
                       + 0.22 * tech["background"] + 0.17 * tech["piqe"] + 0.12 * tech["colorcast"])
                sqs = (0.25 * (sem["subject_centering"] + sem["feature_visibility"]
                               + sem["marketing_suitability"]) + 0.15 * sem["angle_value"]
                       + 0.10 * sem["lighting_style_quality"])
                fqs = 0.4 * tqs + 0.6 * sqs
                dec[h] = {"tqs": tqs, "sqs": sqs, "fqs": fqs, "role": role if strong else "reject",
                          "passed": strong, "hard_rejected": False, "semantic_scores": sem,
                          "technical_scores": tech, "view_sig": None}
                photos.append({"hash": h, **{f"t_{a}": b for a, b in tech.items()},
                               **{f"s_{a}": b for a, b in sem.items()}})
            log.append({**common, "event": "capture_end", "timestamp": t0, "photo_hashes": hashes})
            log.append({**common, "event": "own_picks", "timestamp": t0,
                        "own_picks": dict(zip(("main", "angle1", "angle2", "detail"), hashes))})
            log.append({**common, "event": "batch_result", "timestamp": t0,
                        "photos": [{"hash": h, "tqs": round(dec[h]["tqs"], 3),
                                    "sqs": round(dec[h]["sqs"], 3), "fqs": round(dec[h]["fqs"], 3),
                                    "role": dec[h]["role"], "passed": dec[h]["passed"],
                                    "selected": dec[h]["passed"]} for h in hashes],
                        "framework_selection": [{"hash": h, "role": dec[h]["role"]}
                                                for h in hashes if dec[h]["passed"]],
                        "gate": {"certified": strong, "missing": []}})
    d = tmp_path / "study"
    d.mkdir()
    (d / "study_log.jsonl").write_text("".join(json.dumps(e) + "\n" for e in log), encoding="utf-8")
    keys = list(dict.fromkeys(a for r in photos for a in r))
    with open(d / "rescored_photos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(photos)
    (d / "rescored_decisions.json").write_text(json.dumps(dec), encoding="utf-8")
    return d, log


def test_analysis_chain_on_synthetic_ten_participants(tmp_path):
    d, log = _synthetic_study(tmp_path)
    key = [{"pair_id": f"p{i:02d}", "A_is": "guided" if i % 2 else "unguided",
            "participant": f"P{i:02d}", "slot": "main"} for i in range(1, 11)]
    with open(d / "blind_key.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(key[0]))
        w.writeheader()
        w.writerows(key)

    def letter(i, want):
        a_is = "guided" if i % 2 else "unguided"
        return "tie" if want == "tie" else ("A" if a_is == want else "B")

    # guided wins 7, unguided 1, two ties; rater 2 identical to rater 1
    want = ["guided"] * 7 + ["unguided", "tie", "tie"]
    ans = []
    for i, w_ in enumerate(want, 1):
        ans.append({"rater": "PH1", "pair_id": f"p{i:02d}", "preferred": letter(i, w_), "strength": "4"})
        ans.append({"rater": "PH2", "pair_id": f"p{i:02d}", "preferred": letter(i, w_), "strength": "3"})
    with open(d / "rater_sheet.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["rater", "pair_id", "preferred", "strength"])
        w.writeheader()
        w.writerows(ans)

    S = an.sessions(an.load_log(d / "study_log.jsonl"))
    photo_rows = {r["hash"]: r for r in an.read_csv(d / "rescored_photos.csv")}
    M = an.per_participant_means(S, photo_rows)
    a, tables = an.o2a(M)
    assert a["fqs"]["n_participants"] == 10 and a["fqs"]["guided_better"] == 10
    assert a["fqs"]["wilcoxon_p_one_sided"] < 0.01 and a["fqs"]["hl_ci_has_95_coverage"]
    crit = {r["criterion"]: r for r in tables["o2a_criterion_delta"]}
    assert len(crit) == 11 and crit["T1 Sharpness"]["group"] == "targeted"
    assert crit["S1 Centring"]["group"] == "targeted"
    assert crit["T4 BRISQUE"]["group"] == "non-targeted"
    assert crit["T1 Sharpness"]["delta_guided_minus_unguided"] == pytest.approx(0.4)

    b, rows = an.o2b(d)
    assert (b["both_guided"], b["both_unguided"], b["tie"]) == (7, 1, 2)
    assert b["binomial_p_one_sided_non_ties"] == pytest.approx(0.0352, abs=1e-3)      # 7 of 8
    assert b["sensitivity_ties_against_guided_p"] == pytest.approx(0.1719, abs=1e-3)  # 7 of 10
    assert b["cohen_kappa_between_raters"] == 1.0
    assert b["mean_strength_votes_for_guided"] == pytest.approx(3.5)

    dec = json.loads((d / "rescored_decisions.json").read_text())
    c, sets = an.o2c(S, dec)
    assert c["pairs"] == 10 and c["guided_only"] == 10 and c["unguided_only"] == 0
    assert c["mcnemar_exact_p_two_sided"] == pytest.approx(2 * 0.5 ** 10, abs=1e-3)

    o3, _ = an.o3(S, d)
    assert o3["participants_guided"]["mean_jaccard"] == 1.0
    assert o3["participants_unguided"]["mean_jaccard"] == 0.0
    assert o3["preregistered_failure_mean_jaccard_below_0.50"] is False
    ret, groups = an.descriptive(S, M)
    assert {g["group"] for g in groups} == {"seller", "non_expert"}


def test_first_prompt_cuts_the_prefix(tmp_path):
    d, log = _synthetic_study(tmp_path, n=2)
    ev = [e for e in log if e["participant"] == "P01" and e["condition"] == "GUIDED"]
    cut = {**ev[0], "event": "help_card_shown", "role": "hero_shot", "seconds": 20,
           "timestamp": "2026-10-20T10:01:12.500Z"}        # after the 2nd capture (10:01:12.000)
    S = an.sessions(ev + [cut])
    hs, when = an.prefix_hashes(S[("P01", "GUIDED")])
    assert when == cut["timestamp"] and len(hs) == 2


def test_weight_scenarios_sum_to_one_and_config_untouched():
    from backend.pqf import config
    before = (dict(config.TQS_WEIGHTS), dict(config.SQS_WEIGHTS), config.FQS_ALPHA)
    sc = ws.scenarios()
    assert len(sc) == 1 + 2 * 6 + 2 * 5 + 4
    for label, kind, p in sc:
        assert sum(p["tw"].values()) == pytest.approx(1.0)
        assert sum(p["sw"].values()) == pytest.approx(1.0)
        assert p["alpha"] + p["beta"] == pytest.approx(1.0)
    assert (dict(config.TQS_WEIGHTS), dict(config.SQS_WEIGHTS), config.FQS_ALPHA) == before
    t4 = [p for label, k, p in sc if label.startswith("TQS brisque")]
    assert all(p["tw"]["brisque"] == 0.0 and p["_noop"] for p in t4)


def test_weight_baseline_matches_the_framework_decision():
    from backend.pqf.combination import decide_image
    tech = {"sharpness": 0.9, "exposure": 0.9, "background": 0.9, "brisque": 0.0, "piqe": 0.6,
            "colorcast": 0.9}
    sem = {"subject_centering": 0.9, "feature_visibility": 0.8, "marketing_suitability": 0.9,
           "angle_value": 0.8, "lighting_style_quality": 0.9}
    tqs = sum(ws.BASE["tw"][k] * tech[k] for k in tech)
    sqs = sum(ws.BASE["sw"][k] * sem[k] for k in sem)
    d = decide_image(tqs, sqs, sem)
    r = ws.decide(tech, sem, ws.BASE)
    assert (r["role"], r["passed"]) == (d.role, d.passed)
    assert r["fqs"] == pytest.approx(d.fqs)
