"""build_study_inputs.py - turns the manifest + the Step-2 runs into the input folder that
analysis_study / weight_sensitivity / make_blind_packs read. NO Gemini calls: the semantic
result of a photo is the per-criterion median of its stored valid runs (runs.jsonl); a photo
with fewer than 3 valid stored runs is reported and left unscored. Read-only on the zips.

Writes research/results/study/analysis/study_dir/:
  study_log.jsonl        events of the FIRST complete attempt of every analysed session
  study_log_last.jsonl   events of the LAST complete attempt (sensitivity only)
  photos/<sha>.jpg       every photo those attempts mention
  rescored_photos.csv, rescored_decisions.json   (frozen v1.4.0 pipeline, median-of-3 semantic)
Product codes are lower-cased in the copies (case-insensitive rule); nothing else changes.
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

os.environ["PQF_SCORE_CACHE"] = "off"
os.environ.pop("PQF_SEMANTIC_MOCK", None)
sys.argv = sys.argv[:1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np                                    # noqa: E402
import rescore_study as rs                            # noqa: E402
import study_manifest as sm                           # noqa: E402
import backend.pqf.semantic as semmod                 # noqa: E402
from backend.pqf.semantic import evaluator            # noqa: E402
from backend.pqf.pipeline import score_image          # noqa: E402

ROOT = Path(rs._REPO_ROOT) / "research" / "results" / "study"
OUT = ROOT / "analysis" / "study_dir"
CRITS = [k for k, _ in evaluator.SEMANTIC_CRITERIA]
STORED = defaultdict(list)
CUR = {"h": None}


def stored_eval(image_bytes, mime="image/jpeg"):
    valid = [r for r in STORED[CUR["h"]] if r["ok"]][:3]
    if len(valid) < 3:
        return evaluator.SemanticResult(ok=False, error="fewer than 3 stored valid runs")
    med = {c: statistics.median(v["scores"][c] for v in valid) for c in CRITS}
    roles = [v["role"] for v in valid]
    role = max(set(roles), key=roles.count)
    if roles.count(role) == 1:
        role = sorted(valid, key=lambda v: v["sqs"])[1]["role"]
    return evaluator.SemanticResult(scores=med, sqs=evaluator._aggregate_sqs(med), role=role,
                                    ok=True, model_version=valid[-1]["model"])


semmod.evaluate_semantic = stored_eval


def main(extra_hashes=()):
    with contextlib.redirect_stdout(io.StringIO()):
        attempts, rows, verdict = sm.main()
    (OUT / "photos").mkdir(parents=True, exist_ok=True)
    keep = {(r["code"], r["session"]) for r in rows if r["secondary"]}
    arm = {r["code"]: r["arm"] for r in rows}
    first_ev, last_ev, hashes, att_info = [], [], set(), []
    for (code, sess) in sorted(keep):
        comp = [a for a in attempts[(code, sess)] if a["complete"]]
        for tag, a, bucket in (("first", comp[0], first_ev), ("last", comp[-1], last_ev)):
            ev = list(a["events"])
            if a["session_start"] is not None and not any(e is a["session_start"] for e in ev):
                ev.insert(0, a["session_start"])
            rid = ((a["session_start"] or ev[0]).get("times") or {}).get("session_start", "")
            for e in ev:
                e = json.loads(json.dumps(e))
                e["product"] = str(e.get("product", "")).lower()
                # one attempt = one run id (an app restart mid-attempt starts a new
                # session_start; analysis_study groups by it)
                if isinstance(e.get("times"), dict):
                    e["times"]["session_start"] = rid
                bucket.append(e)
            hashes |= sm.hashes_of(ev)
            att_info.append({"code": code, "arm": arm[code], "session": sess, "which": tag,
                             "start": a["start"], "end": a["end"]})
    for name, evs in (("study_log.jsonl", first_ev), ("study_log_last.jsonl", last_ev)):
        (OUT / name).write_text("".join(json.dumps(e) + "\n" for e in evs), encoding="utf-8")
    (OUT / "attempt_windows.json").write_text(json.dumps(att_info, indent=1))
    # photos
    zips = {z.name: zipfile.ZipFile(z) for z in (ROOT / "raw").glob("*.zip")}
    where = {}
    for zn, zf in zips.items():
        for n in zf.namelist():
            m = sm.ENTRY.match(n)
            if m:
                where.setdefault(m.group(1), (zn, n))
    hashes |= set(extra_hashes)
    miss = []
    for h in sorted(hashes):
        if h in where:
            (OUT / "photos" / f"{h}.jpg").write_bytes(zips[where[h][0]].read(where[h][1]))
        else:
            miss.append(h[:10])
    # stored runs
    for l in (ROOT / "runs.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(l)
        STORED[r["hash"]].append(r)
    # rescore (offline) every hash that has 3 stored valid runs
    sl = {r["hash"] for r in csv.DictReader(open(ROOT / "scoring_list.csv", encoding="utf-8"))}
    if (ROOT / "extra_scoring_list.csv").exists():
        sl |= {r["hash"] for r in csv.DictReader(
            open(ROOT / "extra_scoring_list.csv", encoding="utf-8"))}
    todo = sorted(h for h in (sl | set(extra_hashes)) if h in where)
    logged = {}
    for e in first_ev + last_ev:
        if e["event"] == "batch_result":
            for p in e["photos"]:
                logged.setdefault(p["hash"], p)
    dec, out_rows, mism, short = {}, [], [], []
    for h in todo:
        CUR["h"] = h
        data = rs._platform_format((OUT / "photos" / f"{h}.jpg").read_bytes())
        d = score_image(data, path=None)
        if d.reason.startswith("semantic_failed"):
            short.append(h[:10])
            continue
        tq = round(rs._tqs_only(data), 4)
        lt = (logged.get(h) or {}).get("tqs")
        if lt is not None and abs(tq - round(float(lt), 4)) > 0.001:
            mism.append((h[:10], lt, tq))
        ts, ss = (getattr(d, "technical_scores", None) or {}), d.semantic_scores or {}
        sig = getattr(d, "view_sig", None)
        dec[h] = {"tqs": d.tqs, "sqs": d.sqs, "fqs": d.fqs, "role": d.role, "passed": d.passed,
                  "hard_rejected": d.hard_rejected, "reason": d.reason, "semantic_scores": ss,
                  "technical_scores": ts,
                  "view_sig": None if not sig else {
                      "hash": np.asarray(sig["hash"]).astype(int).tolist(),
                      "sil": np.asarray(sig["sil"]).astype(int).tolist()}}
        out_rows.append({"hash": h, "logged_tqs": lt, "rescored_tqs": tq,
                         "logged_sqs": (logged.get(h) or {}).get("sqs"),
                         "logged_fqs": (logged.get(h) or {}).get("fqs"),
                         "rescored_sqs": round(d.sqs, 4), "rescored_fqs": round(d.fqs, 4),
                         "rescored_role": d.role, "reason": d.reason,
                         **{f"t_{k}": round(v, 4) for k, v in ts.items()},
                         **{f"s_{k}": round(v, 4) for k, v in ss.items()}})
    keys = list(dict.fromkeys(k for r in out_rows for k in r))
    with open(OUT / "rescored_photos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out_rows)
    (OUT / "rescored_decisions.json").write_text(json.dumps(dec), encoding="utf-8")
    rep = {"photos_in_folder": len(list((OUT / "photos").glob("*.jpg"))), "rescored": len(dec),
           "missing_from_zips": miss, "fewer_than_3_stored_runs": short,
           "tqs_mismatches": mism}
    (OUT / "build_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
