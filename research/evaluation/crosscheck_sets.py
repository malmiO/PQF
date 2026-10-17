"""
crosscheck_sets.py  -  PART B of the human cross-check: candidate product sets from the
researcher's own light-box captures, and the framework's 4-photo set for each kept set
(2026-10-16). NOT holdout images (checked by SHA-256 against the dataset manifest).

  --list    candidates: product, photos, distinct views (view signature), paths. NO scoring, no
            API. Writes research/results/crosscheck/candidate_sets.csv.
  --score   for each KEPT set (>= 6 photos AND >= 2 distinct views): score every photo with the
            frozen v1.4.0 pipeline, technical once (deterministic) and the semantic stage 3 times
            with the cache OFF (4 s pacing), median per criterion, then the app's own selection
            (pipeline.process_batch: main, two distinct angles, detail) and gate.

Sets are NOT chosen by score. Product membership is the capture order (gaps >= 60 s between
photos) confirmed by looking at the photos; correct LIGHTBOX / WHATSAPP below if a grouping is
wrong.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import statistics as st
import sys
import time
from pathlib import Path

os.environ["PQF_SCORE_CACHE"] = "off"
os.environ.pop("PQF_SEMANTIC_MOCK", None)

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")

OUT = REPO / "research" / "results" / "crosscheck"
LB = REPO / "data" / "lightning_studio_box_captures"
WA = REPO / "test-img"
MIN_PHOTOS, MIN_VIEWS = 6, 2
REPEATS, PACE_S = 3, 4.0

# (set id, first index, last index) into the sorted file list
LIGHTBOX = [("LB_LIPBALM", 0, 6), ("LB_EARRINGS_PINK", 7, 11), ("LB_EARRINGS_SILVER", 12, 16),
            ("LB_EARRINGS_BLUE", 17, 20), ("LB_EARRINGS_GOLD", 21, 27), ("LB_STICKERS", 28, 34),
            ("LB_APPLE_KEYCHAIN", 35, 43), ("LB_DESK_KEYCHAIN", 44, 47),
            ("LB_ABC_KEYCHAIN", 48, 53), ("LB_MUG_KEYCHAINS", 54, 55),
            ("LB_BOOKS_KEYCHAIN", 56, 59)]
WHATSAPP = [("WA_LIPBALM", 0, 6), ("WA_APPLE_KEYCHAIN", 7, 12), ("WA_BOOKS_KEYCHAIN", 13, 15),
            ("WA_THANKYOU_KEYCHAIN", 16, 19)]


def _wa_key(p: Path):
    m = re.search(r"at (\d+)\.(\d+)\.(\d+) (AM|PM)", p.name)
    h = int(m[1]) % 12 + (12 if m[4] == "PM" else 0)
    return (h * 3600 + int(m[2]) * 60 + int(m[3]), p.name)


def candidate_products() -> list:
    rows = []
    lb = sorted(LB.glob("*.jpg"))
    wa = sorted(WA.glob("WhatsApp*"), key=_wa_key)
    for files, spec, group in ((lb, LIGHTBOX, "lightbox_2026-10-08/09"),
                               (wa, WHATSAPP, "whatsapp_2026-10-05")):
        for sid, a, b in spec:
            for i in range(a, b + 1):
                p = files[i]
                rows.append({"set_id": sid, "group": group, "path": p.relative_to(REPO).as_posix(),
                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return rows


def dataset_overlap(shas: set) -> int:
    """Candidate files that are also dataset files of the frozen split (must be 0)."""
    n = 0
    with open(REPO / "data" / "master_manifest.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("sha256") in shas:
                n += 1
    return n


def view_counts(rows: list) -> dict:
    """set_id -> number of distinct views (greedy, view signature, NEAR_DUPLICATE)."""
    import cv2
    import numpy as np
    from backend.api.main import _platform_format
    from backend.pqf.pipeline.views import NEAR_DUPLICATE, view_distance, view_signature
    from backend.pqf.preprocess import standardise
    sig = {}
    for r in rows:
        data = _platform_format((REPO / r["path"]).read_bytes())
        img = standardise(cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR))
        sig[r["path"]] = view_signature(img)
    out = {}
    for sid in dict.fromkeys(r["set_id"] for r in rows):
        reps = []
        for r in [x for x in rows if x["set_id"] == sid]:
            s = sig[r["path"]]
            if all(view_distance(s, t) >= NEAR_DUPLICATE for t in reps):
                reps.append(s)
        out[sid] = len(reps)
    return out


def do_list() -> list:
    rows = candidate_products()
    OUT.mkdir(parents=True, exist_ok=True)
    ov = dataset_overlap({r["sha256"] for r in rows})
    v = view_counts(rows)
    summary = []
    for sid in dict.fromkeys(r["set_id"] for r in rows):
        mem = [r for r in rows if r["set_id"] == sid]
        keep = len(mem) >= MIN_PHOTOS and v[sid] >= MIN_VIEWS
        summary.append({"set_id": sid, "group": mem[0]["group"], "photos": len(mem),
                        "distinct_views": v[sid], "kept": keep,
                        "paths": ";".join(r["path"] for r in mem)})
    for name, data in (("candidate_sets.csv", summary), ("candidate_photos.csv", rows)):
        with open(OUT / name, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    print("candidate files that are dataset/holdout files:", ov)
    for s in summary:
        print(f"{s['set_id']:22s} photos {s['photos']:2d}  views {s['distinct_views']:2d}  "
              f"{'KEEP' if s['kept'] else 'drop'}")
    return summary


def median_scores(runs: list) -> dict:
    return {k: float(st.median(r[k] for r in runs)) for k in runs[0]}


def do_score() -> None:
    import cv2
    import numpy as np
    from backend.api.main import _platform_format
    from backend.pqf import config
    from backend.pqf.combination import ImageDecision, decide_image
    from backend.pqf.pipeline import process_batch
    from backend.pqf.pipeline.views import view_signature
    from backend.pqf.preprocess import standardise
    from backend.pqf.semantic import evaluate_semantic
    from backend.pqf.technical import compute_tqs, t0_compliance

    summary = do_list()
    keep = [s["set_id"] for s in summary if s["kept"]]
    photos = [r for r in csv.DictReader(open(OUT / "candidate_photos.csv", encoding="utf-8"))
              if r["set_id"] in keep]
    raw = OUT / "set_scores_raw.jsonl"
    done = {}
    if raw.exists():                       # resumable: finished photos are never re-called
        for line in raw.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            done[d["path"]] = d
    calls = fails = 0
    for r in photos:
        if r["path"] in done:
            continue
        data = _platform_format((REPO / r["path"]).read_bytes())
        img0 = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        rec = {"set_id": r["set_id"], "path": r["path"], "sha256": r["sha256"], "runs": []}
        if not t0_compliance(img0):
            rec.update(t0=False)
        else:
            img = standardise(img0)
            tech = compute_tqs(img, check_gate=False)
            sig = view_signature(img)
            rec.update(t0=True, tqs=tech.tqs, tech=dict(tech.scores),
                       hard_reject=bool(tech.hard_reject),
                       view_sig={"hash": np.asarray(sig["hash"]).astype(int).tolist(),
                                 "sil": np.asarray(sig["sil"]).astype(int).tolist()})
            if not tech.hard_reject:
                mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                for _ in range(REPEATS):
                    s = evaluate_semantic(data, mime)
                    calls += 1
                    if s.ok:
                        rec["runs"].append(dict(s.scores))
                    else:
                        fails += 1
                        rec.setdefault("errors", []).append(str(s.error)[:120])
                    time.sleep(PACE_S)
        with open(raw, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        done[r["path"]] = rec
        print(f"{r['set_id']} {Path(r['path']).name} ok_runs={len(rec['runs'])} calls={calls}",
              flush=True)

    rows_out, selection = [], {}
    for sid in keep:
        decs = []
        for r in [p for p in photos if p["set_id"] == sid]:
            rec = done[r["path"]]
            sem = {}
            if not rec.get("t0") or rec.get("hard_reject"):
                d = ImageDecision(tqs=rec.get("tqs", 0.0) or 0.0, role="reject", passed=False,
                                  hard_rejected=True,
                                  reason="t0_platform_spec_fail" if not rec.get("t0")
                                  else "hard_reject_tqs_below_0.4")
            elif len(rec["runs"]) >= 2:
                sem = median_scores(rec["runs"])
                sqs = sum(config.SQS_WEIGHTS[k] * sem[k] for k in config.SQS_WEIGHTS)
                d = decide_image(rec["tqs"], sqs, sem)
            else:
                d = ImageDecision(tqs=rec["tqs"], role="reject", passed=False,
                                  reason="semantic_failed")
            sig = rec.get("view_sig")
            setattr(d, "view_sig", None if not sig else {
                "hash": np.asarray(sig["hash"]).astype(bool), "sil": np.asarray(sig["sil"]).astype(bool)})
            setattr(d, "path", rec["path"])
            setattr(d, "technical_scores", rec.get("tech") or {})
            decs.append(d)
            rows_out.append({"set_id": sid, "path": rec["path"], "sha256": rec["sha256"],
                             "ok_runs": len(rec["runs"]), "tqs": round(d.tqs, 4),
                             **{f"t_{k}": round(v, 4) for k, v in (rec.get("tech") or {}).items()},
                             **{f"s_{k}": round(v, 4) for k, v in sem.items()},
                             "sqs": round(d.sqs, 4), "fqs": round(d.fqs, 4), "role": d.role,
                             "passed": d.passed, "reason": d.reason})
        res = process_batch(decs)
        selection[sid] = {"pool": [d.path for d in decs],
                          "selected": [{"path": d.path, "role": d.role} for d in res.selected],
                          "certified": res.certified,
                          "fail_reasons": (res.recapture or {}).get("fail_reasons", [])}
    with open(OUT / "set_scores.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in rows_out for k in r)),
                           lineterminator="\n")
        w.writeheader()
        w.writerows(rows_out)
    (OUT / "set_selection.json").write_text(json.dumps(selection, indent=1), encoding="utf-8")
    print(json.dumps({"gemini_calls_this_run": calls, "failed_calls": fails,
                      "sets_scored": len(keep)}, indent=1))
    for sid, s in selection.items():
        print(sid, "selected", len(s["selected"]), "certified", s["certified"], s["fail_reasons"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    do_score() if a.score else do_list()
