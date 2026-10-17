"""rescore_study.py - READ-ONLY re-scoring analysis of an exported study zip
(item 4, 2026-10-14). Changes no framework code.

For every photo the study log scored it:
  1. reproduces the server's pipeline EXACTLY - the same _platform_format
     (orientation + 4:5 crop) then score_image - and checks the rescored TQS
     equals the logged TQS within 0.001, listing any mismatch. (TQS is
     deterministic, so this should always match.)
  2. with the score cache OFF, scores each photo N times (default 3) and reports
     per-criterion SD, the SQS range and role agreement - the non-determinism
     that the new cache removes - next to the August test-retest figures.

Usage (pinned venv, from the repo root):
    .venv/Scripts/python.exe research/evaluation/rescore_study.py \
        --dir path/to/unzipped_export --reps 3 [--max-photos N]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

# Re-scoring must be real, and must never use mock. The variance pass needs the cache OFF
# (default); the dry-run zip mode of 2026-10-15 can be run with --cache on (1 run, cached).
_CACHE = "on" if sys.argv[1:] and "--cache" in sys.argv and \
    sys.argv[sys.argv.index("--cache") + 1:][:1] == ["on"] else "off"
os.environ["PQF_SCORE_CACHE"] = _CACHE
os.environ.pop("PQF_SEMANTIC_MOCK", None)

from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv()

import cv2                                            # noqa: E402
import numpy as np                                     # noqa: E402

from backend.api.main import _platform_format        # noqa: E402  (server 4:5 crop)
from backend.pqf.preprocess import standardise        # noqa: E402
from backend.pqf.technical import compute_tqs, t0_compliance  # noqa: E402
from backend.pqf.semantic import evaluate_semantic    # noqa: E402


def _tqs_only(formatted_bytes: bytes) -> float:
    """TQS exactly as score_image computes it (decode -> t0 -> standardise ->
    compute_tqs), with NO semantic/Gemini call. Deterministic."""
    img = cv2.imdecode(np.frombuffer(formatted_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return 0.0
    if not t0_compliance(img):     # score_image returns a reject with tqs 0.0
        return 0.0
    return float(compute_tqs(standardise(img), check_gate=False).tqs)

# Coventry August 2026 test-retest baseline (from the dissertation appendix),
# shown alongside the new figures. Override with --august-sqs-range if needed.
AUGUST_SQS_RANGE = 0.092   # the observed same-image SQS spread that motivated this


def _logged_scores(log_path: Path) -> dict:
    """hash -> {tqs, sqs, role} from batch_result events (first occurrence)."""
    out = {}
    if not log_path.exists():
        return out
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("event") != "batch_result":
            continue
        for p in e.get("photos", []):
            h = p.get("hash")
            if h and h not in out:
                out[h] = {"tqs": p.get("tqs"), "sqs": p.get("sqs"),
                          "role": p.get("role")}
    return out


def _photos(root: Path):
    photos_dir = root / "study" / "photos"
    if not photos_dir.is_dir():
        photos_dir = root / "photos" if (root / "photos").is_dir() else root
    for p in sorted(photos_dir.rglob("*.jpg")):
        yield p.parent.name, p.stem, p


def run_zip(args) -> int:
    """Zip mode (2026-10-15): check exported study zips against the server pipeline.

    Per zip: CRC and file-name == sha256; every hash the log mentions is in the zip; every
    log entry passes the SERVER's own validator (study_api.validate). Every logged photo is
    re-scored through _platform_format + score_image (ONE run, cache as --cache) and the
    rescored TQS must equal the logged TQS within 0.001. Writes under --out:
      rescored_photos.csv       per photo: logged vs rescored scores, all 11 criteria, ms
      rescored_decisions.json   what analysis_study.py needs to rebuild a set offline
      rescore_report.json       counts, timing, Gemini calls (cache misses), mismatches
    The key is needed only for photos that are not already in the score cache."""
    import csv
    from backend.pqf.semantic import score_cache as sc
    from backend.pqf.pipeline import score_image
    import studyzip as sz

    out = Path(args.out or "research/results/dryrun/rescore")
    out.mkdir(parents=True, exist_ok=True)
    report = {"zips": [], "cache": args.cache}
    all_photos, logs = {}, []
    for zp in args.zip:
        r = sz.read_zip(Path(zp))
        logged_h = sz.logged_hashes(r["log"])
        ok, errs = sz.schema_check(r["log"])
        missing = {k: sorted(h[:10] for h in v if h not in r["photos"])
                   for k, v in logged_h.items()}
        report["zips"].append({
            "zip": str(zp), "log_entries": len(r["log"]), "photos_in_zip": len(r["photos"]),
            "crc_ok": not r["bad_crc"], "name_sha256_mismatch": len(r["name_mismatch"]),
            "schema_accepted": ok, "schema_rejected": [list(e) for e in errs],
            "hashes_logged_not_in_zip": missing,
            "all_logged_hashes_present": all(not v for v in missing.values())})
        all_photos.update(r["photos"])
        logs.append(r["log"])
    merged = sz.merge_logs(logs)
    (out / "merged_log.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in merged), encoding="utf-8")

    meta, logged = {}, {}
    for e in merged:
        if e["event"] == "batch_result":
            for p in e.get("photos", []):
                logged.setdefault(p["hash"], p)
                meta.setdefault(p["hash"], (e["participant"], e["condition"], e["product"],
                                            e.get("session", "")))
    before = sc.stats()
    rows, decisions, mismatches, times = [], {}, [], []
    for h in sorted(logged):
        if h not in all_photos:
            continue
        data = _platform_format(all_photos[h])
        t = time.perf_counter()
        d = score_image(data, path=None)
        ms = round(1000 * (time.perf_counter() - t), 1)
        times.append(ms)
        tq = round(_tqs_only(data), 4)
        lt = logged[h].get("tqs")
        match = lt is not None and abs(tq - round(float(lt), 4)) <= 0.001
        if not match:
            mismatches.append((h[:10], lt, tq))
        ts = getattr(d, "technical_scores", None) or {}
        ss = d.semantic_scores or {}
        p, c, prod, sess = meta[h]
        rows.append({"hash": h, "participant": p, "condition": c, "product": prod,
                     "session": sess, "logged_tqs": lt, "rescored_tqs": tq,
                     "tqs_match": match, "logged_sqs": logged[h].get("sqs"),
                     "rescored_sqs": round(d.sqs, 4), "logged_fqs": logged[h].get("fqs"),
                     "rescored_fqs": round(d.fqs, 4), "logged_role": logged[h].get("role"),
                     "rescored_role": d.role, "reason": d.reason, "ms": ms,
                     **{f"t_{k}": round(v, 4) for k, v in ts.items()},
                     **{f"s_{k}": round(v, 4) for k, v in ss.items()}})
        sig = getattr(d, "view_sig", None)
        decisions[h] = {"tqs": d.tqs, "sqs": d.sqs, "fqs": d.fqs, "role": d.role,
                        "passed": d.passed, "hard_rejected": d.hard_rejected,
                        "reason": d.reason, "semantic_scores": ss, "technical_scores": ts,
                        "view_sig": None if not sig else {
                            "hash": np.asarray(sig["hash"]).astype(int).tolist(),
                            "sil": np.asarray(sig["sil"]).astype(int).tolist()}}
    after = sc.stats()
    if rows:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(out / "rescored_photos.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    (out / "rescored_decisions.json").write_text(json.dumps(decisions), encoding="utf-8")
    sem = [r for r in rows if r["reason"] in ("ok", "below_fqs_pass_or_no_role")]
    report.update({
        "photos_logged": len(logged), "photos_rescored": len(rows),
        "logged_photos_not_in_any_zip": len([h for h in logged if h not in all_photos]),
        "tqs_checked": len(rows), "tqs_within_0.001": len(rows) - len(mismatches),
        "tqs_mismatches": [list(m) for m in mismatches],
        "time_per_photo_s": {
            "mean": round(statistics.mean(times) / 1000, 2) if times else None,
            "median": round(statistics.median(times) / 1000, 2) if times else None,
            "max": round(max(times) / 1000, 2) if times else None,
            "total": round(sum(times) / 1000, 1)},
        "gemini_calls_cache_misses": after["misses"] - before["misses"],
        "cache_hits": after["hits"] - before["hits"],
        "photos_that_reached_semantic": len(sem),
        "sqs_logged_vs_rescored": {
            "n": len(sem), "role_agree": sum(1 for r in sem
                                             if r["rescored_role"] == r["logged_role"]),
            "mean_abs_diff": round(statistics.mean(
                abs(float(r["rescored_sqs"]) - float(r["logged_sqs"] or 0)) for r in sem), 4)
            if sem else None}})
    (out / "rescore_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))
    return 0 if not mismatches else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", help="Unzipped export folder.")
    ap.add_argument("--zip", action="append", default=[],
                    help="Exported study zip (repeatable). Dry-run mode, see run_zip().")
    ap.add_argument("--cache", choices=["on", "off"], default="off")
    ap.add_argument("--out", help="Folder for the --zip outputs.")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--max-photos", type=int, default=0,
                    help="Limit the semantic variance pass (0 = all).")
    ap.add_argument("--august-sqs-range", type=float, default=AUGUST_SQS_RANGE)
    args = ap.parse_args()
    if args.zip:
        return run_zip(args)
    if not args.dir:
        ap.error("--dir or --zip is required")

    root = Path(args.dir)
    log_path = (root / "study_log.jsonl")
    if not log_path.exists():
        log_path = root / "study" / "study_log.jsonl"
    logged = _logged_scores(log_path)
    photos = list(_photos(root))
    print(f"photos on disk: {len(photos)}   logged (batch_result) photos: {len(logged)}")
    key = bool(os.environ.get("GEMINI_API_KEY"))
    print(f"semantic: LIVE (cache OFF), GEMINI_API_KEY present: {key}\n")

    # 1) TQS reproduction (deterministic, no Gemini) -------------------------
    print("== TQS reproduction (tolerance 0.001) ==")
    tqs_mismatch = []
    checked = 0
    for folder, h, path in photos:
        if h not in logged or logged[h].get("tqs") is None:
            continue
        formatted = _platform_format(path.read_bytes())
        rt = round(_tqs_only(formatted), 4)
        lt = round(float(logged[h]["tqs"]), 4)
        checked += 1
        if abs(rt - lt) > 0.001:
            tqs_mismatch.append((folder, h[:10], lt, rt))
    print(f"  checked {checked} photos; mismatches: {len(tqs_mismatch)}")
    for folder, hh, lt, rt in tqs_mismatch:
        print(f"    MISMATCH {folder}/{hh}  logged={lt}  rescored={rt}")
    if not tqs_mismatch and checked:
        print("  all rescored TQS match the logged TQS within 0.001.")

    # 2) SQS variance with cache OFF -----------------------------------------
    if args.reps <= 0:
        print("\n== SQS variance: skipped (--reps 0) ==")
        return 0
    sample = [(f, h, p) for (f, h, p) in photos]
    if args.max_photos:
        sample = sample[:args.max_photos]
    print(f"\n== SQS variance, {args.reps} reps, cache OFF "
          f"({len(sample)} photos) ==")
    per_crit_sds, sqs_ranges, role_disagreements = [], [], 0
    scored = 0
    for folder, h, path in sample:
        formatted = _platform_format(path.read_bytes())
        reps = []
        for _ in range(args.reps):
            r = evaluate_semantic(formatted, "image/jpeg")
            if r.ok:
                reps.append(r)
        if len(reps) < 2:
            print(f"  {folder}/{h[:10]}: only {len(reps)} ok reps "
                  f"(free-tier 503/slow) - skipped")
            continue
        scored += 1
        sqs_vals = [r.sqs for r in reps]
        rng = max(sqs_vals) - min(sqs_vals)
        sqs_ranges.append(rng)
        roles = {r.role for r in reps}
        if len(roles) > 1:
            role_disagreements += 1
        crits = reps[0].scores.keys()
        for c in crits:
            vals = [r.scores.get(c, 0.0) for r in reps]
            per_crit_sds.append(statistics.pstdev(vals))
        print(f"  {folder}/{h[:10]}: SQS range={rng:.3f} roles={roles}")

    print("\n== Summary ==")
    if sqs_ranges:
        print(f"  photos with >=2 ok reps: {scored}")
        print(f"  SQS range: mean={statistics.mean(sqs_ranges):.3f} "
              f"max={max(sqs_ranges):.3f}")
        print(f"  per-criterion SD: mean={statistics.mean(per_crit_sds):.3f} "
              f"max={max(per_crit_sds):.3f}")
        print(f"  role agreement: {scored - role_disagreements}/{scored} "
              f"photos agreed across reps")
        print(f"  August test-retest SQS range (baseline): "
              f"{args.august_sqs_range:.3f}")
        print("  NOTE: with the new score cache ON, an identical image returns "
              "an identical SQS, so this variance becomes 0 in production.")
    else:
        print("  no photos produced >=2 ok reps (free tier too slow/503). "
              "Re-run on the paid tier for the variance figures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
