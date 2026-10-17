"""rescore_study_runs.py - STEP 2 of the study rescore (frozen v1.4.0, cache OFF).

For every photo in research/results/study/scoring_list.csv: server pipeline exactly
(_platform_format + score_image), but the semantic call is replaced by N VALID Gemini runs
(a failed run is re-run) whose per-criterion MEDIAN gives the SQS. Nothing in backend/ is
edited; only backend.pqf.semantic.evaluate_semantic is wrapped in-process.
Order: REMOTE first-attempt photos, STATION first-attempt, then last-attempt-only photos.
Resumable: raw runs are appended to runs.jsonl as they happen.
Stops (exit 3) if the quota blocks a photo; it never falls back to fewer runs.

    .venv/Scripts/python.exe research/evaluation/rescore_study_runs.py
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import sys
import time
import zipfile
from pathlib import Path

os.environ["PQF_SCORE_CACHE"] = "off"
os.environ.pop("PQF_SEMANTIC_MOCK", None)
sys.argv = sys.argv[:1]                      # rescore_study parses argv at import
sys.path.insert(0, str(Path(__file__).resolve().parent))

import rescore_study as rs                   # noqa: E402  (loads .env, repo path)
import backend.pqf.semantic as semmod        # noqa: E402
from backend.pqf.semantic import evaluator   # noqa: E402
from backend.pqf import config               # noqa: E402
from backend.pqf.pipeline import score_image  # noqa: E402

ROOT = Path(rs._REPO_ROOT) / "research" / "results" / "study"
RUNS = ROOT / "runs.jsonl"
N, MAX_TRIES = 3, 8
CRITS = [k for k, _ in evaluator.SEMANTIC_CRITERIA]
STATS = {"calls": 0, "failed": 0, "quota_stop": False}
RUNLOG = {}                                   # hash -> [valid runs] (current photo)
CUR = {"hash": None}


class QuotaBlocked(Exception):
    pass


def _load_done():
    done = {}
    if RUNS.exists():
        for l in RUNS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            done.setdefault(r["hash"], []).append(r)
    return done


def multi_eval(image_bytes, mime="image/jpeg"):
    h = CUR["hash"]
    prior = [r for r in DONE.get(h, []) if r["ok"]]
    valid = list(prior)
    tries = 0                                  # failed tries of an earlier invocation do not count
    consec_quota = 0
    while len(valid) < N:
        if tries >= MAX_TRIES:
            return evaluator.SemanticResult(ok=False, error=f"{MAX_TRIES} tries, <{N} valid")
        r = evaluator.evaluate_semantic(image_bytes, mime)   # cache is off
        tries += 1
        STATS["calls"] += 1
        bad = (not r.ok) or r.sqs <= 0.0
        rec = {"hash": h, "try": tries, "ok": not bad, "sqs": r.sqs, "role": r.role,
               "scores": r.scores, "error": r.error, "model": r.model_version,
               "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(RUNS, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        DONE.setdefault(h, []).append(rec)
        if bad:
            STATS["failed"] += 1
            if "RESOURCE_EXHAUSTED" in r.error or "429" in r.error:
                consec_quota += 1
                if consec_quota >= 3:
                    raise QuotaBlocked(r.error[:200])
            continue
        consec_quota = 0
        valid.append(rec)
    med = {c: statistics.median(v["scores"][c] for v in valid) for c in CRITS}
    sqs = evaluator._aggregate_sqs(med)
    roles = [v["role"] for v in valid]
    role = max(set(roles), key=roles.count)
    if roles.count(role) == 1:                # no majority: role of the median-SQS run
        role = sorted(valid, key=lambda v: v["sqs"])[len(valid) // 2]["role"]
    return evaluator.SemanticResult(scores=med, sqs=sqs, role=role, ok=True,
                                    justification="median of %d" % len(valid),
                                    model_version=valid[-1]["model"])


semmod.evaluate_semantic = multi_eval         # pipeline imports it at call time


def main():
    sl = list(csv.DictReader(open(ROOT / "scoring_list.csv", encoding="utf-8")))
    order, seen = [], set()
    for tier in (lambda r: r["which"] == "first" and r["key"].endswith("REMOTE"),
                 lambda r: r["which"] == "first" and r["key"].endswith("STATION"),
                 lambda r: True):
        for r in sl:
            if r["hash"] not in seen and tier(r):
                seen.add(r["hash"])
                order.append(r)
    ex = ROOT / "extra_scoring_list.csv"        # O2c pre-prompt photos not in the Step-1 list
    if ex.exists():
        for r in csv.DictReader(open(ex, encoding="utf-8")):
            if r["hash"] not in seen:
                seen.add(r["hash"])
                order.append(r)
    zips = {}
    logged = {}
    for z in sorted((ROOT / "raw").glob("*.zip")):
        zf = zipfile.ZipFile(z)
        zips[z.name] = zf
        for l in zf.read("study_log.jsonl").decode().splitlines():
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("event") == "batch_result":
                for p in e["photos"]:
                    logged.setdefault(p["hash"], p)
    global DONE
    DONE = _load_done()
    out = ROOT / "rescored_photos.csv"
    rows, mism = [], []
    n_total = len(order)
    for i, r in enumerate(order, 1):
        h = r["hash"]
        name = next(n for n in r["zips"].split(";") if n in zips)
        entry = next(n for n in zips[name].namelist() if n.endswith(h + ".jpg"))
        data = rs._platform_format(zips[name].read(entry))
        CUR["hash"] = h
        try:
            d = score_image(data, path=None)
        except QuotaBlocked as ex:
            print(f"QUOTA BLOCKED at photo {i}/{n_total} {h[:10]}: {ex}")
            STATS["quota_stop"] = True
            break
        tq = round(rs._tqs_only(data), 4)
        lt = (logged.get(h) or {}).get("tqs")
        match = lt is not None and abs(tq - round(float(lt), 4)) <= 0.001
        if not match:
            mism.append((r["key"], h[:10], lt, tq))
        valid = [x for x in DONE.get(h, []) if x["ok"]]
        ss = d.semantic_scores or {}
        rows.append({"key": r["key"], "session": r["session"], "which": r["which"], "hash": h,
                     "logged_tqs": lt, "rescored_tqs": tq, "tqs_match": match,
                     "logged_sqs": (logged.get(h) or {}).get("sqs"),
                     "rescored_sqs": round(d.sqs, 4), "rescored_fqs": round(d.fqs, 4),
                     "role": d.role, "reason": d.reason, "valid_runs": len(valid),
                     "total_tries": len(DONE.get(h, [])),
                     "run_sqs": ";".join(f"{x['sqs']:.3f}" for x in valid),
                     **{f"s_{k}": round(v, 4) for k, v in ss.items()}})
        print(f"[{i}/{n_total}] {r['key']} s{r['session']} {h[:10]} tqs {tq} sqs {d.sqs:.3f} "
              f"runs={len(valid)} tries={len(DONE.get(h, []))} {d.reason}", flush=True)
    if rows:
        keys = list(dict.fromkeys(k for x in rows for k in x))
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    rep = {"photos_done": len(rows), "photos_planned": n_total, "gemini_calls_this_invocation":
           STATS["calls"], "failed_runs_this_invocation": STATS["failed"],
           "quota_stop": STATS["quota_stop"], "tqs_checked": len(rows),
           "tqs_mismatches": [list(m) for m in mism],
           "photos_below_3_valid": [x["hash"][:10] for x in rows
                                    if x["valid_runs"] < N and not x["reason"].startswith(
                                        ("hard_reject", "t0_platform"))],
           "model": config.GEMINI_MODEL, "prompt": config.PROMPT_VERSION}
    (ROOT / "rescore_report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep, indent=1))
    return 3 if STATS["quota_stop"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
