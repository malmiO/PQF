"""Tests for ai_judges.py / panel.py / the --panel modes. MOCK judge only: no API, no network.
Run from the repo root:  python -m pytest research/evaluation/tests -q"""
import csv
import io
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image

EVAL = Path(__file__).resolve().parents[1]
REPO = EVAL.parents[1]
sys.path.insert(0, str(EVAL))
import ai_judges as A      # noqa: E402
import panel as P          # noqa: E402

RES = REPO / "research/results"
DRY = RES / "dryrun"


def rd(p):
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def cli(*args):
    r = subprocess.run([sys.executable, str(EVAL / "ai_judges.py"), *map(str, args)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout


def blind_item():
    p = DRY / "blind/blind_pairs"
    return A.Item("blind_pairs", "74f60c", "pair",
                  [next(p.glob("pair_74f60c_A.*")), next(p.glob("pair_74f60c_B.*"))], {})


# ------------------------------------------------------------ pure statistics
def test_panel_label_needs_two_valid_judges():
    assert P.panel_label(["A", "A", "B"]) == "A"
    assert P.panel_label(["A", "B", "tie"]) == "tie"
    assert P.panel_label(["A"]) == "tie"
    assert P.panel_label(["tie", "tie", "A"]) == "tie"


def test_fleiss_and_cohen_known_values():
    assert P.fleiss_kappa([["a", "a", "a"], ["b", "b", "b"]]) == pytest.approx(1.0)
    assert P.cohen_kappa(list("aabb"), list("aabb")) == pytest.approx(1.0)
    assert P.cohen_kappa(list("aabb"), list("abab")) == pytest.approx(0.0)
    t = [[0, 0, 0, 0, 14], [0, 2, 6, 4, 2], [0, 0, 3, 5, 6], [0, 3, 9, 2, 0], [2, 2, 8, 1, 1],
         [7, 7, 0, 0, 0], [3, 2, 6, 3, 0], [2, 5, 3, 2, 2], [6, 5, 2, 1, 0], [0, 2, 2, 3, 7]]
    rows = [[c for c, n in enumerate(r) for _ in range(n)] for r in t]
    assert P.fleiss_kappa(rows) == pytest.approx(0.210, abs=0.001)      # textbook value


def test_gate_threshold_ties_count_wrong():
    key = [{"pair_id": str(i)} for i in range(24)]
    votes = {str(i): {"J1": "clean" if i < 18 else "tie", "J2": "clean" if i < 17 else "fault"}
             for i in range(24)}
    g = P.known_answer_gate(key, votes, ["J1", "J2"])
    assert g["J1"]["correct"] == 18 and g["J1"]["included_in_panel"] is True
    assert g["J2"]["correct"] == 17 and g["J2"]["included_in_panel"] is False
    assert P.included_judges(g) == ["J1"]


# ------------------------------------------------------------ prompts, parsing, safety
def test_free_variants_and_framework_evaluator_rejected():
    with pytest.raises(SystemExit):
        A.check_slug("google/gemma-3-27b-it:free")
    with pytest.raises(SystemExit):
        A.check_slug("google/gemini-3.5-flash-lite")
    assert A.check_slug("qwen/qwen3.8-max-0902")
    assert not any(":free" in m for m in A.JUDGES.values())


def test_exact_prompt_text():
    assert A.PAIR_PROMPT == ("You are an experienced e-commerce product photographer. Which photo is "
                             "better for an online product listing? Answer A, B or NO_DIFFERENCE, give "
                             "strength 1-5 and one short reason.")


def test_parsers():
    assert A.parse_pair('x {"choice":"b","strength":4,"reason":"sharp"} y')["choice"] == "B"
    assert A.parse_pair('{"choice":"NO_DIFFERENCE","strength":1,"reason":""}')["choice"] == "NO_DIFFERENCE"
    assert A.parse_pair('{"choice":"C","strength":3}') is None
    assert A.parse_pair('{"choice":"A","strength":9}') is None
    assert A.parse_pair("A") is None
    assert A.parse_set('{"main":1,"angle1":2,"angle2":3,"detail":4}', 5)["detail"] == 4
    assert A.parse_set('{"main":1,"angle1":1,"angle2":3,"detail":4}', 5) is None
    assert A.parse_set('{"main":1,"angle1":2,"angle2":3,"detail":9}', 5) is None


def test_image_prep_exif_resize_jpeg(tmp_path):
    im = Image.new("RGB", (3000, 1000), (200, 10, 10))
    ex = im.getexif()
    ex[0x0112] = 6
    p = tmp_path / "x.jpg"
    im.save(p, exif=ex)
    out = Image.open(io.BytesIO(A.prep_image(p)))
    assert out.format == "JPEG" and max(out.size) == 1536
    assert out.size[1] > out.size[0]                       # orientation applied
    small = tmp_path / "s.png"
    Image.new("RGB", (400, 300)).save(small)
    assert Image.open(io.BytesIO(A.prep_image(small))).size == (400, 300)


def test_requests_carry_no_private_names_and_swap_orders(tmp_path):
    a, b = tmp_path / "secret_fault_BLUR.jpg", tmp_path / "secret_CLEAN_source.jpg"
    Image.new("RGB", (64, 64), (1, 2, 3)).save(a)
    Image.new("RGB", (64, 64), (9, 8, 7)).save(b)
    it = A.Item("bank_pairs", "p1", "pair", [a, b], {})
    c = {}
    p1, m1 = A.build_request(it, 1, c)
    p2, m2 = A.build_request(it, 2, c)
    texts = " ".join(v for k, v in p1 + p2 if k == "text")
    for bad in ("secret", "fault", "CLEAN", "BLUR", "source", "jpg"):
        assert bad not in texts
    assert m1 == {"A": "A", "B": "B"} and m2 == {"A": "B", "B": "A"}
    assert [v for k, v in p1 if k == "image"][0] == [v for k, v in p2 if k == "image"][1]


# ------------------------------------------------------------ mock end-to-end
@pytest.fixture(scope="module")
def mock_out(tmp_path_factory):
    o = tmp_path_factory.mktemp("mock")
    cli("run", "--mock", "--source", "bank_pairs", "--pair-key", RES / "crosscheck/pair_key.csv", "--out", o)
    cli("run", "--mock", "--source", "bank_sets", "--set-key",
        DRY / "crosscheck_dryrun/set_photo_key.csv", "--out", o)
    cli("run", "--mock", "--source", "blind_pairs", "--dir", DRY / "blind", "--out", o)
    cli("run", "--mock", "--source", "packs_sets", "--dir", DRY / "blind", "--photos",
        DRY / "study_dir/photos", "--out", o)
    return o


def test_sheets_have_the_human_layouts(mock_out):
    heads = {"rater_sheet.csv": ["rater", "pair_id", "preferred", "strength"],
             "crosscheck_pairs_sheet.csv": ["rater", "pair_id", "preferred", "strength"],
             "photographer_picks_sheet.csv": ["rater", "product", "role", "photo_no"],
             "crosscheck_picks_sheet.csv": ["rater", "set_id", "role", "photo_no"]}
    for f, h in heads.items():
        rows = rd(mock_out / f)
        assert list(rows[0]) == h and {r["rater"] for r in rows} == {"J1", "J2", "J3"}


def test_log_fields_both_orders_and_retry(mock_out):
    log = [json.loads(l) for l in (mock_out / "ai_judge_log.jsonl").read_text().splitlines()]
    need = {"item_id", "order", "judge", "returned_model", "requested_model", "provider",
            "prompt_hash", "response", "timestamp", "tokens_in", "tokens_out"}
    assert need <= set(log[0])
    pairs = [r for r in log if r["source"] == "bank_pairs" and r["status"] == "ok"]
    assert {r["order"] for r in pairs} == {1, 2}
    assert len(pairs) == 24 * 2 * 3
    assert any(r["status"] == "retry" for r in log)
    assert not any(r["status"] == "missing" for r in log)


def test_inconsistent_order_becomes_tie(mock_out):
    cons = rd(mock_out / "ai_judge_consistency_bank_pairs.csv")
    sheet = {(r["rater"], r["pair_id"]): r for r in rd(mock_out / "crosscheck_pairs_sheet.csv")}
    bad = [c for c in cons if c["consistent"] == "False"]
    assert bad
    for c in bad:
        assert sheet[(c["judge"], c["item_id"])]["preferred"].lower() == "tie"


def test_json_failures_logged_missing_never_guessed(tmp_path):
    class Bad:
        def chat(self, model, parts):
            return {"text": "no json here", "model": "bad/m", "provider": "x", "id": "1",
                    "tokens_in": 1, "tokens_out": 1, "cost": 0, "finish": "stop"}
    it = blind_item()
    lp = tmp_path / "log.jsonl"
    A.run_calls([it], ["J1"], {"J1": "bad/m"}, Bad(), lp, {}, "blind_pairs")
    log = A.load_log(lp)
    assert [r["status"] for r in log if r["order"] == 1] == ["retry", "retry", "missing"]
    out = A.judge_outcomes(log, [it], ["J1"])
    assert out[("J1", "74f60c")]["valid"] is False
    A.write_sheet(tmp_path, [it], out, ["J1"])
    assert rd(tmp_path / "rater_sheet.csv")[0]["preferred"] == ""


def test_api_error_stops_run(tmp_path):
    class Boom:
        def chat(self, model, parts):
            raise A.ApiStop("HTTP 402")
    with pytest.raises(A.ApiStop):
        A.run_calls([blind_item()], ["J1"], {"J1": "x/y"}, Boom(), tmp_path / "l.jsonl", {}, "blind_pairs")


def test_resume_skips_done_calls(mock_out, tmp_path):
    shutil.copy(mock_out / "ai_judge_log.jsonl", tmp_path / "ai_judge_log.jsonl")
    n0 = len((tmp_path / "ai_judge_log.jsonl").read_text().splitlines())
    cli("run", "--mock", "--source", "bank_pairs", "--pair-key", RES / "crosscheck/pair_key.csv",
        "--out", tmp_path)
    assert len((tmp_path / "ai_judge_log.jsonl").read_text().splitlines()) == n0


def test_estimate_printed_first(tmp_path):
    assert "ESTIMATED COST" in cli("run", "--mock", "--source", "bank_pairs", "--limit", "1",
                                   "--pair-key", RES / "crosscheck/pair_key.csv", "--out", tmp_path)


# ------------------------------------------------------------ --panel modes
def _synthetic_judge_dir(d):
    d.mkdir(parents=True)
    key = rd(RES / "crosscheck/pair_key.csv")
    rows = []
    for i, k in enumerate(key):
        cp = "A" if k["left_is"] == "clean" else "B"
        fp = "B" if cp == "A" else "A"
        rows.append({"rater": "J1", "pair_id": k["pair_id"], "preferred": cp if i < 22 else "tie", "strength": "4"})
        rows.append({"rater": "J2", "pair_id": k["pair_id"], "preferred": cp if i < 20 else fp, "strength": "3"})
        rows.append({"rater": "J3", "pair_id": k["pair_id"], "preferred": fp if i % 2 else "tie", "strength": "2"})
    with open(d / "crosscheck_pairs_sheet.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["rater", "pair_id", "preferred", "strength"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return d


def test_human_crosscheck_panel_excludes_failed_gate_judge(tmp_path):
    jd = _synthetic_judge_dir(tmp_path / "j")
    d = tmp_path / "d"
    d.mkdir()
    shutil.copy(RES / "crosscheck/pair_key.csv", d / "pair_key.csv")
    r = subprocess.run([sys.executable, str(EVAL / "human_crosscheck.py"), "--dir", d, "--out",
                        tmp_path / "o", "--panel", "--judge-dir", jd], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = json.loads((tmp_path / "o/panel_crosscheck_summary.json").read_text())
    assert s["judges_in_panel"] == ["J1", "J2"] and s["judges_excluded"] == ["J3"]
    assert s["gate"]["J1"]["correct"] == 22 and s["gate"]["J2"]["correct"] == 20
    assert s["7A_panel"]["raters"] == ["PANEL"]
    assert "fleiss_kappa" in s["agreement_7A"] and "J1-J2" in s["agreement_7A"]["pairwise_cohen"]


def test_old_two_rater_mode_unchanged(tmp_path):
    r = subprocess.run([sys.executable, str(EVAL / "human_crosscheck.py"), "--dir",
                        DRY / "crosscheck_dryrun", "--out", tmp_path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    s = json.loads(r.stdout)
    assert s["7A"]["raters"] == ["PH1", "PH2"] and "inter_rater" in s["7A"]


def test_analysis_study_panel_runs_on_dryrun(mock_out, tmp_path):
    jd = tmp_path / "j"
    shutil.copytree(mock_out, jd)
    gate = json.loads((jd / "gate.json").read_text())
    for g in gate.values():
        g["included_in_panel"] = True        # force the panel path; the gate itself is tested above
    (jd / "gate.json").write_text(json.dumps(gate))
    work = tmp_path / "w"
    work.mkdir()
    shutil.copy(DRY / "blind/blind_key.csv", work / "blind_key.csv")
    shutil.copy(DRY / "blind/packs/product_photo_key.csv", work / "product_photo_key.csv")
    shutil.copy(DRY / "study_dir/study_log.jsonl", work / "study_log.jsonl")
    r = subprocess.run([sys.executable, str(EVAL / "analysis_study.py"), "--dir", work, "--out",
                        tmp_path / "o", "--label", "DRYRUN", "--panel", "--judge-dir", jd],
                       capture_output=True, text=True, cwd=REPO)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    s = json.loads((tmp_path / "o/DRYRUN_panel_study_summary.json").read_text())
    assert s["judges_in_panel"] == ["J1", "J2", "J3"]
    assert s["O2b_panel"]["pairs"] == 1
