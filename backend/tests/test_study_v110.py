"""Step 7 (v1.1.0): study log (codes only), ABBA order, and the CSV export."""
import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api.study_api import abba_order

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]
H = [f"{i:064x}" for i in range(1, 7)]


def _export():
    spec = importlib.util.spec_from_file_location("export_study", ROOT / "scripts" / "export_study.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _base(event, cond="GUIDED", ts="2026-10-07T10:00:00Z", **kw):
    return {"event": event, "timestamp": ts, "participant": "P03", "condition": cond,
            "product": "K1", **kw}


@pytest.fixture
def log(tmp_path, monkeypatch):
    p = tmp_path / "study_log.jsonl"
    monkeypatch.setenv("PQF_STUDY_LOG", str(p))
    return p


def test_log_line_round_trip(log):
    entry = _base("own_picks", own_picks={"main": H[0], "angle1": H[1],
                                          "angle2": H[2], "detail": H[3]})
    r = client.post("/study/log", content=json.dumps(entry))
    assert r.status_code == 200, r.text
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    back = json.loads(lines[0])
    assert {k: back[k] for k in entry} == entry
    assert "received_at" in back


@pytest.mark.parametrize("bad", [
    {"name": "Nimal"},                              # a name field
    {"participant": "Nimal Perera"},                # a name as the code
    {"product": "call 0771234567 please"},          # contact detail in a code
    {"photo_hashes": ["not-a-hash"]},
    {"photos": [{"hash": "0" * 64, "image": "base64..."}]},   # image data
    {"condition": "SOMETIMES"},
])
def test_only_codes_are_accepted(log, bad):
    entry = {**_base("capture_end"), **bad}
    assert client.post("/study/log", content=json.dumps(entry)).status_code == 400
    assert not log.exists()


def test_abba_order_counterbalances_over_participants():
    orders = [abba_order(f"P{n:02d}") for n in range(1, 9)]
    a, b = ["UNGUIDED", "GUIDED"], ["GUIDED", "UNGUIDED"]
    assert orders == [a, b, b, a, a, b, b, a]


def test_export_produces_the_expected_columns_and_values(tmp_path):
    def photos(tqs):
        return [{"hash": h, "tqs": t, "sqs": 0.8, "fqs": 0.75, "role": r, "passed": True,
                 "selected": s} for h, t, r, s in zip(H[:5], tqs,
               ["hero_shot", "angle_shot", "angle_shot", "detail_shot", "angle_shot"],
               [True, True, True, True, False])]
    sel = [{"hash": H[i], "role": r} for i, r in
           enumerate(["hero_shot", "angle_shot", "angle_shot", "detail_shot"])]
    lines = [
        _base("session_start", times={"session_start": "2026-10-07T10:00:00Z"}),
        _base("capture_end", ts="2026-10-07T10:04:00Z", photo_hashes=H[:5],
              times={"capture_end": "2026-10-07T10:04:00Z"}),
        _base("own_picks", ts="2026-10-07T10:05:00Z",
              own_picks={"main": H[0], "angle1": H[1], "angle2": H[4], "detail": H[3]}),
        _base("batch_result", ts="2026-10-07T10:06:00Z", photos=photos([0.8, 0.7, 0.6, 0.9, 0.5]),
              framework_selection=sel, gate={"certified": True, "missing": []}),
        _base("video_ready", ts="2026-10-07T10:08:00Z",
              times={"video_ready": "2026-10-07T10:08:00Z"}),
    ]
    src = tmp_path / "log.jsonl"
    src.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    dst = tmp_path / "out.csv"
    m = _export()
    assert m.main(src, dst) == 0
    rows = list(csv.DictReader(open(dst, encoding="utf-8")))
    assert list(rows[0].keys()) == m.COLUMNS
    r = rows[0]
    assert r["participant"] == "P03" and r["condition"] == "GUIDED" and r["order"] == "1"
    assert float(r["mean_tqs"]) == pytest.approx(0.7)
    assert r["overlap_n"] == "3" and float(r["overlap_ratio"]) == 0.75
    assert float(r["role_agreement"]) == 1.0
    assert r["capture_seconds"] == "240.0" and r["video_seconds"] == "480.0"


def test_a_rejected_photo_is_logged(log):
    entry = _base("batch_result", photos=[{"hash": H[0], "tqs": 0.3, "sqs": 0.0, "fqs": 0.2,
                                           "role": "reject", "passed": False,
                                           "selected": False}],
                  framework_selection=[], gate={"certified": False,
                                                "missing": ["hero_shot"]})
    assert client.post("/study/log", content=json.dumps(entry)).status_code == 200


def test_export_skips_smoke_test_entries(tmp_path):
    src = tmp_path / "log.jsonl"
    src.write_text(json.dumps({**_base("session_start"), "participant": "P99",
                               "product": "SMOKE"}), encoding="utf-8")
    m = _export()
    assert m.rows_from([json.loads(src.read_text())]) == []


def test_log_download_needs_a_configured_token(log, monkeypatch):
    entry = _base("session_start")
    client.post("/study/log", content=json.dumps(entry))
    monkeypatch.delenv("PQF_API_TOKEN", raising=False)
    assert client.get("/study/log/download").status_code == 403
    monkeypatch.setenv("PQF_API_TOKEN", "t0k")
    assert client.get("/study/log/download").status_code == 401        # no header
    r = client.get("/study/log/download", headers={"X-PQF-Token": "t0k"})
    assert r.status_code == 200 and json.loads(r.text.splitlines()[0])["participant"] == "P03"


# --- v1.4.0-rc: the model that answered, and the API tier, on batch_result entries ----
def test_batch_result_accepts_model_version_and_tier(log):
    entry = _base("batch_result", model_version="gemini-3.5-flash-lite", tier="free",
                  gate={"certified": True, "missing": []})
    assert client.post("/study/log", content=json.dumps(entry)).status_code == 200
    back = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert back["model_version"] == "gemini-3.5-flash-lite" and back["tier"] == "free"


@pytest.mark.parametrize("bad", [
    {"model_version": "x" * 65},                   # longer than 64
    {"model_version": "gemini 3.5"},               # a space
    {"model_version": "gemini/3.5"},               # a slash
    {"model_version": 3.5},                        # not a string
    {"tier": "free tier!"},
])
def test_model_version_and_tier_are_validated(log, bad):
    entry = {**_base("batch_result"), **bad}
    assert client.post("/study/log", content=json.dumps(entry)).status_code == 400
    assert not log.exists()


def test_model_version_only_on_batch_result(log):
    entry = _base("capture_end", model_version="gemini-3.5-flash-lite")
    assert client.post("/study/log", content=json.dumps(entry)).status_code == 400
