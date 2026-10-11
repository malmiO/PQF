"""
o1_detection.py  -  Objective 1: does each criterion detect the fault it is meant to
detect, and leave good images alone? (known-groups construct validity, 2026-10-07)

Design. The frozen dataset holds professional catalogue images (ABO, good), the
researcher's clean captures (good) and single-fault captures whose fault is known BY
CONSTRUCTION (T1 blur, T2 dark/bright, T3 clutter, S1 off-centre, S4 poor angle). For
each criterion we report, at the SPECIFICATION's pass threshold:
  detection rate    share of images with that fault that the criterion flags
  false-alarm rate  share of GOOD images the criterion flags
  AUC               threshold-free discrimination between the two groups
with Wilson 95% intervals and the n behind every percentage (decisions.md 2026-08-05:
"per criterion accuracy is reported WITH sample size").
And at framework level: good vs degraded against the framework's verdict.

Usage (repo root):
  python research/evaluation/o1_detection.py --data data --split data/splits/split_v1.csv \
         --subset holdout --semantic --out research/results/o1_holdout
  --manifest <dir>/manifest.csv adds the controlled synthetic faults made by
  synthetic_faults.py (only those whose source image is in --subset). They are reported
  in their OWN section (by fault and level, paired with their ABO original), never mixed
  into the real-capture table.
  --semantic calls the Gemini evaluator (cached by image hash in <out>/semantic_cache.json,
  so a re-run costs nothing). Without it only T0-T6 are evaluated.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

from evalcommon import (SPEC_PASS, SPEC_PASS_V13, TECH, SEM, LABEL, VIOLATION, discover, apply_split,
                        sha, wilson, auc, fmt_ci, write_csv, save_json, environment,
                        platform_format)


def score_all(rows, semantic: bool, cache_path: Path, delay: float):
    import cv2
    from backend.pqf.preprocess import standardise
    from backend.pqf.technical import compute_tqs, t0_compliance
    from backend.pqf.combination import decide_image
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if semantic:
        from backend.pqf.semantic import evaluate_semantic
    out = []
    for i, r in enumerate(rows, 1):
        img = cv2.imread(r["path"], cv2.IMREAD_COLOR)
        rec = dict(r)
        if img is None:
            rec.update(t0=False, error="decode_failed"); out.append(rec); continue
        rec["width"], rec["height"] = img.shape[1], img.shape[0]
        img = platform_format(img)                 # as the API does before scoring
        rec["t0"] = bool(t0_compliance(img))
        t = time.perf_counter()
        tech = compute_tqs(standardise(img), check_gate=False)
        rec["tech_ms"] = round(1000 * (time.perf_counter() - t), 1)
        rec.update({k: round(v, 4) for k, v in tech.scores.items()})
        rec["tqs"] = round(tech.tqs, 4)
        rec["hard_reject"] = bool(tech.hard_reject)
        if semantic and rec["t0"] and not tech.hard_reject:
            key = sha(r["path"])
            if key not in cache or not cache[key].get("ok"):   # old failed entries are retried
                data = Path(r["path"]).read_bytes()
                mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
                if (img.shape[1], img.shape[0]) != (rec["width"], rec["height"]):
                    data, mime = cv2.imencode(".png", img)[1].tobytes(), "image/png"
                s = evaluate_semantic(data, mime)
                res = {"ok": s.ok, "scores": s.scores, "sqs": s.sqs, "error": s.error}
                if not s.ok and ("not set" in str(s.error) or "API key" in str(s.error)
                                 or "PERMISSION_DENIED" in str(s.error)):
                    raise SystemExit(f"Semantic evaluator cannot run: {s.error}. Put GEMINI_API_KEY "
                                     "in the repo's .env (it is loaded automatically, never printed).")
                if s.ok:   # only real answers are cached; a failed call is retried next run
                    cache[key] = res
                    cache_path.write_text(json.dumps(cache, indent=1))
                time.sleep(delay)
            else:
                res = cache[key]
            s = res
            if s["ok"]:
                rec.update({k: round(v, 4) for k, v in s["scores"].items()})
                rec["sqs"] = round(s["sqs"], 4)
                d = decide_image(tech.tqs, s["sqs"], s["scores"])
                rec.update(fqs=round(d.fqs, 4), role=d.role, passed=bool(d.passed))
            else:
                rec.update(semantic_error=s["error"])
        if semantic and (not rec["t0"] or tech.hard_reject):
            rec.update(role="reject", passed=False)
        out.append(rec)
        print(f"\r{i}/{len(rows)}", end="", flush=True)
    print()
    return out


def summarise(rec: list) -> dict:
    good = [r for r in rec if r["label"] == "good"]
    crit = [c for c in TECH + SEM if any(c in r for r in rec)]
    per = []
    for c in crit:
        thr = SPEC_PASS[c]
        g = [r[c] for r in good if c in r]
        bad = [r[c] for r in rec if r.get("target") == c and c in r]
        fa = sum(1 for v in g if v < thr)
        det = sum(1 for v in bad if v < thr)
        row = {"criterion": c, "label": LABEL[c], "threshold": thr,
               "n_good": len(g), "false_alarms": fa,
               "false_alarm_rate": round(fa / len(g), 3) if g else None,
               "false_alarm_ci": [round(x, 3) for x in wilson(fa, len(g))],
               "n_faulty": len(bad), "detected": det,
               "detection_rate": round(det / len(bad), 3) if bad else None,
               "detection_ci": [round(x, 3) for x in wilson(det, len(bad))] if bad else None,
               "auc": round(auc(g, bad), 3) if bad else None}
        per.append(row)
    # framework verdict, only where a verdict exists
    v = [r for r in rec if "passed" in r]
    tp = sum(1 for r in v if r["label"] == "degraded" and not r["passed"])
    fn = sum(1 for r in v if r["label"] == "degraded" and r["passed"])
    tn = sum(1 for r in v if r["label"] == "good" and r["passed"])
    fp = sum(1 for r in v if r["label"] == "good" and not r["passed"])
    verdict = {"n": len(v), "degraded_rejected": tp, "degraded_passed": fn,
               "good_passed": tn, "good_rejected": fp}
    if v:
        import math
        sens = tp / (tp + fn) if tp + fn else float("nan")
        spec = tn / (tn + fp) if tn + fp else float("nan")
        den = math.sqrt((tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)) or float("nan")
        verdict.update(sensitivity=round(sens, 3), specificity=round(spec, 3),
                       balanced_accuracy=round((sens + spec) / 2, 3),
                       mcc=round((tp * tn - fp * fn) / den, 3))
    # Paired, within product: each faulty capture against the SAME product's clean
    # capture (same phone, room and session), so only the fault differs.
    from scipy.stats import binomtest   # exact sign test; with n = 4 the floor is p = 0.0625
    clean = {r["product"]: r for r in rec if r["source"] == "researcher_capture"
             and r["label"] == "reference"}
    paired = []
    for fault, c in VIOLATION.items():
        prs = [(clean[r["product"]], r) for r in rec if r["fault"] == fault
               and r["product"] in clean and c in r and c in clean[r["product"]]]
        if not prs:
            continue
        d = [f[c] - g[c] for g, f in prs]
        lower = sum(1 for x in d if x < 0)
        newly = sum(1 for g, f in prs if g[c] >= SPEC_PASS[c] > f[c])
        flagged = sum(1 for g, f in prs if f[c] < SPEC_PASS[c])
        nz = [x for x in d if x != 0]
        p = float(binomtest(sum(x < 0 for x in nz), len(nz), 0.5,
                            alternative="greater").pvalue) if nz else 1.0
        others = {o: round(st.median(f[o] - g[o] for g, f in prs), 3)
                  for o in TECH if o != c and o in prs[0][1]}
        paired.append({"fault": fault, "criterion": c, "n_pairs": len(prs),
                       "score_lower_than_clean": lower, "flagged_below_threshold": flagged,
                       "clean_passed_fault_failed": newly,
                       "median_change": round(st.median(d), 3),
                       "sign_test_p_one_sided": round(p, 4),
                       "median_change_other_criteria": others})
    by_source = {}
    for src in sorted({r["source"] for r in good}):
        s = [r for r in good if r["source"] == src]
        by_source[src] = {c: round(sum(1 for r in s if c in r and r[c] < SPEC_PASS[c]) / len(s), 3)
                          for c in crit}
    # Researcher CLEAN captures: reported on their own (evidence for the environment rule).
    ref = [r for r in rec if r["label"] == "reference"]
    reference = {"n": len(ref),
                 "below_threshold": {c: sum(1 for r in ref if c in r and r[c] < SPEC_PASS[c])
                                     for c in crit},
                 "framework_passed": sum(1 for r in ref if r.get("passed") is True),
                 "framework_n": sum(1 for r in ref if "passed" in r)}
    return {"n_images": len(rec), "n_good": len(good),
            "n_degraded": sum(1 for r in rec if r["label"] == "degraded"),
            "n_reference": len(ref), "reference_clean_captures": reference,
            "faults": {f: sum(1 for r in rec if r["fault"] == f) for f in VIOLATION},
            "per_criterion": per, "verdict": verdict, "paired": paired,
            "false_alarm_rate_by_good_source": by_source,
            "t0_fail": sum(1 for r in rec if not r.get("t0", True)),
            "hard_reject": {"good": sum(1 for r in good if r.get("hard_reject")),
                            "degraded": sum(1 for r in rec if r["label"] == "degraded"
                                            and r.get("hard_reject"))},
            "median_tech_ms": sorted(r.get("tech_ms", 0) for r in rec)[len(rec) // 2]}


def load_manifest(path: Path, subset: str | None) -> list:
    """Synthetic faulty images whose ABO source is in the chosen split part."""
    from evalcommon import read_csv
    rows = []
    for m in read_csv(path):
        if subset and m["split"] != subset:
            continue
        rows.append({"path": str(path.parent / m["relpath"]), "relpath": m["relpath"],
                     "category": m["category"], "source": "synthetic",
                     "product": f"abo/{Path(m['source']).stem}", "label": "degraded",
                     "fault": m["fault"], "level": int(m["level"]),
                     "target": m["target"], "params": m["params"]})
    return rows


def summarise_synthetic(rec: list) -> list:
    """Each synthetic image against ITS OWN clean ABO original: same picture, only the
    constructed fault differs. One row per fault x level."""
    from scipy.stats import binomtest
    clean = {r["product"]: r for r in rec if r["source"] == "ABO"}
    syn = [r for r in rec if r["source"] == "synthetic"]
    out = []
    for fault, lv in sorted({(r["fault"], r["level"]) for r in syn}):
        grp = [r for r in syn if r["fault"] == fault and r["level"] == lv]
        c = grp[0]["target"]
        prs = [(clean[r["product"]], r) for r in grp
               if r["product"] in clean and c in r and c in clean[r["product"]]]
        row = {"fault": fault, "level": lv, "criterion": c, "n": len(grp),
               "n_pairs": len(prs)}
        if prs:
            d = [f[c] - g[c] for g, f in prs]
            nz = [x for x in d if x != 0]
            flagged = sum(1 for _, f in prs if f[c] < SPEC_PASS[c])
            row.update(
                flagged=flagged,
                flagged_rate=round(flagged / len(prs), 3),
                flagged_ci=[round(x, 3) for x in wilson(flagged, len(prs))],
                clean_passed_fault_failed=sum(1 for g, f in prs if g[c] >= SPEC_PASS[c] > f[c]),
                score_lower=sum(1 for x in d if x < 0),
                median_change=round(st.median(d), 3),
                sign_test_p_one_sided=round(float(binomtest(
                    sum(x < 0 for x in nz), len(nz), 0.5, alternative="greater").pvalue), 6)
                if nz else 1.0,
                median_change_other_criteria={
                    o: round(st.median(f[o] - g[o] for g, f in prs), 3)
                    for o in TECH if o != c and o in prs[0][1] and o in prs[0][0]})
        v = [r for r in grp if "passed" in r]
        if v:
            row["framework_rejected"] = sum(1 for r in v if not r["passed"])
            row["framework_n"] = len(v)
        out.append(row)
    return out


def markdown_synthetic(rows: list) -> str:
    L = ["", "## Controlled synthetic faults (each against its own clean ABO original)", "",
         "| Fault | Level | Criterion | Flagged below threshold | Clean passed, fault failed | "
         "Score lower | Median change | Sign test p | Framework rejected |",
         "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r["n_pairs"]:
            L.append(f"| {r['fault']} | {r['level']} | {LABEL[r['criterion']]} | not scored | | | | | |")
            continue
        fw = f"{r['framework_rejected']}/{r['framework_n']}" if "framework_n" in r else "-"
        L.append(f"| {r['fault']} | {r['level']} | {LABEL[r['criterion']]} | "
                 f"{fmt_ci(r['flagged'], r['n_pairs'])} | {r['clean_passed_fault_failed']}/{r['n_pairs']} | "
                 f"{r['score_lower']}/{r['n_pairs']} | {r['median_change']:+.3f} | "
                 f"{r['sign_test_p_one_sided']} | {fw} |")
    return "\n".join(L) + "\n"


def _threshold_note() -> str:
    """Say which thresholds the table used: the specification's (v1.3), and where the
    server's own calibrated values (config.TQS_PASS_THRESHOLDS, v1.4.0) differ, which."""
    diff = [f"{LABEL[k].split('(')[0].strip()} {SPEC_PASS[k]:g}" for k in ("brisque", "piqe")
            if SPEC_PASS[k] != SPEC_PASS_V13[k]]
    if not diff:
        return "specification v1.3."
    return ("specification v1.3, except " + " and ".join(diff) +
            " (calibrated, v1.4.0; the server's own thresholds).")


def markdown(s: dict, title: str) -> str:
    L = [f"# {title}", "",
         f"Images: {s['n_images']} ({s['n_good']} good catalogue images, {s['n_degraded']} with one "
         f"known fault, {s.get('n_reference', 0)} researcher clean captures used only as pair anchors). "
         f"Thresholds: {_threshold_note()}", "",
         "| Criterion | Pass threshold | Detects its fault | False alarms on good images | AUC |",
         "|---|---|---|---|---|"]
    for r in s["per_criterion"]:
        det = fmt_ci(r["detected"], r["n_faulty"]) if r["n_faulty"] else "no constructed fault"
        L.append(f"| {r['label']} | {r['threshold']} | {det} | "
                 f"{fmt_ci(r['false_alarms'], r['n_good'])} | {r['auc'] if r['auc'] is not None else '-'} |")
    if s.get("paired"):
        L += ["", "Paired within product (fault vs the same product's clean capture). Descriptive: with 4 pairs the smallest possible p is 0.0625.", "",
              "| Fault | Criterion | Pairs | Score lower than clean | Below threshold | "
              "Clean passed, fault failed | Median change | Exact sign test p (one-sided) |",
              "|---|---|---|---|---|---|---|---|"]
        for r in s["paired"]:
            L.append(f"| {r['fault']} | {LABEL[r['criterion']]} | {r['n_pairs']} | "
                     f"{r['score_lower_than_clean']}/{r['n_pairs']} | {r['flagged_below_threshold']}/{r['n_pairs']} | "
                     f"{r['clean_passed_fault_failed']}/{r['n_pairs']} | {r['median_change']:+.3f} | "
                     f"{r['sign_test_p_one_sided']} |")
    ref = s.get("reference_clean_captures")
    if ref and ref["n"]:
        flag = ", ".join(f"{LABEL[c].split()[0]} {k}/{ref['n']}" for c, k in ref["below_threshold"].items() if k)
        L += ["", f"Researcher clean captures (not in the good group): below threshold: {flag or 'none'}; "
              f"framework passed {ref['framework_passed']}/{ref['framework_n']}."]
    v = s["verdict"]
    if v.get("n"):
        L += ["", "Framework verdict (image passes = FQS >= 0.55 and a role):", "",
              f"| | Rejected | Passed |", "|---|---|---|",
              f"| Degraded | {v['degraded_rejected']} | {v['degraded_passed']} |",
              f"| Good | {v['good_rejected']} | {v['good_passed']} |", "",
              f"Sensitivity {v.get('sensitivity')}, specificity {v.get('specificity')}, "
              f"balanced accuracy {v.get('balanced_accuracy')}, MCC {v.get('mcc')}."]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--split", type=Path)
    ap.add_argument("--subset", choices=["calibration", "holdout"])
    ap.add_argument("--semantic", action="store_true")
    ap.add_argument("--manifest", type=Path, help="synthetic_faults.py manifest.csv")
    ap.add_argument("--delay", type=float, default=4.0, help="seconds between model calls")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--rerun-holdout", action="store_true",
                    help="only with a reason recorded in decisions.md")
    a = ap.parse_args()
    # The holdout is scored ONCE, after everything is frozen (spec s6.2). The lock has
    # ONE fixed place and is written BEFORE scoring starts, so a new --out folder or a
    # crashed run cannot be used to look again.
    from evalcommon import REPO
    lock = REPO / "research" / "results" / "HOLDOUT_LOCK.txt"
    if a.subset == "holdout":
        if lock.exists() and not a.rerun_holdout:
            raise SystemExit(f"The holdout was already opened ({lock.read_text().strip()}). "
                             "Re-scoring needs --rerun-holdout and a decisions.md entry.")
        import datetime
        lock.parent.mkdir(parents=True, exist_ok=True)
        with open(lock, "a", encoding="utf-8") as f:
            f.write(f"opened {datetime.datetime.now().isoformat(timespec='seconds')}, "
                    f"split sha256 {sha(str(a.split))}, semantic={a.semantic}, "
                    f"rerun={a.rerun_holdout}\n")
    rows = apply_split(discover(a.data), a.split, a.subset)
    if not rows:
        raise SystemExit("No images found.")
    a.out.mkdir(parents=True, exist_ok=True)
    if a.manifest:
        if not a.subset:
            raise SystemExit("--manifest needs --subset (calibration or holdout).")
        syn = load_manifest(a.manifest, a.subset)
        print(f"{len(rows)} dataset images + {len(syn)} synthetic faults")
        rows = rows + syn
    rec = score_all(rows, a.semantic, a.out / "semantic_cache.json", a.delay)
    write_csv(a.out / "per_image.csv", rec)
    s = summarise([r for r in rec if r["source"] != "synthetic"])
    if a.manifest:
        s["synthetic"] = summarise_synthetic(rec)
    s["subset"] = a.subset or "all (no split applied)"
    s["environment"] = environment()
    if a.semantic:
        from evalcommon import model_version
        s["environment"]["gemini_model_version"] = model_version()
    save_json(a.out / "summary.json", s)
    md = markdown(s, f"O1 criterion detection - {s['subset']}")
    if s.get("synthetic"):
        md += markdown_synthetic(s["synthetic"])
    (a.out / "summary.md").write_text(md, encoding="utf-8")
    print(md)
