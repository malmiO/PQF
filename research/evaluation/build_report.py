"""
build_report.py  -  one quantitative evaluation report (HTML + slide-ready PNG charts)
from whatever result files exist (2026-10-07).

  python research/evaluation/build_report.py --results research/results --out research/results/report
Looks for: o1*/summary.json, ai*/summary.json, system*/summary.json,
dq*/device_qualification.json, participants*/participants_summary.json.
Every table states its n, its source file and whether it is PRELIMINARY / SYNTHETIC.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import date
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evalcommon import LABEL, wilson  # noqa: E402

BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": GRID, "axes.labelcolor": INK2,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False,
                     "axes.spines.right": False, "font.family": "DejaVu Sans"})


def _save(fig, path):
    fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="white")
    plt.close(fig)


def chart_o1(s, path):
    per = s["per_criterion"]
    names = [LABEL[r["criterion"]] for r in per][::-1]
    fa = [r["false_alarm_rate"] * 100 for r in per][::-1]
    lo = [r["false_alarm_ci"][0] * 100 for r in per][::-1]
    hi = [r["false_alarm_ci"][1] * 100 for r in per][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    ax.barh(names, fa, color=BLUE, height=0.55)
    ax.errorbar(fa, range(len(fa)), xerr=[[a - b for a, b in zip(fa, lo)], [b - a for a, b in zip(fa, hi)]],
                fmt="none", ecolor=INK2, capsize=3, lw=1)
    for i, v in enumerate(fa):
        ax.text(v + 2, i + 0.22, f"{v:.0f}%", color=INK, fontsize=10)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Good images flagged as failing (%), 95% CI")
    ax.set_title(f"False alarms on good images (n = {s['n_good']})", loc="left", color=INK)
    ax.grid(axis="x", color=GRID, lw=0.6)
    _save(fig, path)


def chart_paired(s, path):
    pr = s.get("paired") or []
    if not pr:
        return False
    labels = [f"{r['fault'].title()} -> {LABEL[r['criterion']].split()[0]}" for r in pr]
    low = [r["score_lower_than_clean"] / r["n_pairs"] * 100 for r in pr]
    flg = [r["flagged_below_threshold"] / r["n_pairs"] * 100 for r in pr]
    fig, ax = plt.subplots(figsize=(7.5, 3.8))
    y = range(len(pr))
    ax.barh([i + 0.2 for i in y], low, height=0.38, color=BLUE, label="Score lower than the clean photo")
    ax.barh([i - 0.2 for i in y], flg, height=0.38, color=ORANGE, label="Flagged below the pass threshold")
    ax.set_yticks(list(y)); ax.set_yticklabels(labels)
    ax.invert_yaxis(); ax.set_xlim(0, 110)
    for i, r in enumerate(pr):
        ax.text(102, i, f"n={r['n_pairs']}", va="center", color=INK2, fontsize=9)
    ax.set_xlabel("% of fault photos (paired with the same product's clean photo)")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=2, fontsize=9)
    ax.set_title("Does each criterion react to its own fault?", loc="left", color=INK)
    ax.grid(axis="x", color=GRID, lw=0.6)
    _save(fig, path)
    return True


def chart_ai(s, path):
    rows = [r for r in s["summary"] if r["level"] == 2 and r["group"] == "all"]
    names = [r["description"].split(" (")[0] for r in rows][::-1]
    de = [r["median_product_deltaE"] for r in rows][::-1]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.barh(names, de, color=AQUA, height=0.55)
    ax.axvline(2.3, color=INK2, lw=1, ls="--")
    ax.text(2.45, -0.75, "just noticeable, dE 2.3", color=INK2, fontsize=9)
    for i, v in enumerate(de):
        ax.text(v + 0.15, i, f"{v:.1f}", va="center", color=INK, fontsize=10)
    ax.set_xlabel("Median colour change of the product, CIEDE2000 dE (level 2)")
    ax.set_title(f"Product colour change after enhancement (n = {rows[0]['n']})", loc="left", color=INK)
    ax.grid(axis="x", color=GRID, lw=0.6)
    _save(fig, path)


def chart_masking(s, path):
    rows = [r for r in s["summary"] if r["group"] == "all"]
    ops = list(dict.fromkeys(r["operator"] for r in rows))
    desc = {r["operator"]: r["description"].split(" (")[0] for r in rows}
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    for k, (lv, col) in enumerate(((1, "#9ec5f0"), (2, "#5b9be3"), (3, BLUE))):
        vals = [next(r for r in rows if r["operator"] == o and r["level"] == lv) for o in ops]
        share = [100 * v["masked_sharpness"] / v["failing_before_sharpness"] if v["failing_before_sharpness"] else 0
                 for v in vals]
        ax.barh([i + (k - 1) * 0.26 for i in range(len(ops))], share, height=0.24, color=col,
                label=f"strength {lv}")
    ax.set_yticks(range(len(ops))); ax.set_yticklabels([desc[o] for o in ops]); ax.invert_yaxis()
    n_fail = rows[0]["failing_before_sharpness"]
    ax.set_xlabel(f"% of the {n_fail} photos that FAILED T1 and PASS after enhancement")
    ax.set_title("Enhancement can hide a sharpness fault", loc="left", color=INK)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_xlim(0, 100)
    ax.grid(axis="x", color=GRID, lw=0.6)
    _save(fig, path)


def table(headers, rows):
    h = "".join(f"<th>{html.escape(str(x))}</th>" for x in headers)
    b = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{h}</tr></thead><tbody>{b}</tbody></table>"


def pct(k, n):
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({100 * k / n:.0f}%; {100 * lo:.0f}-{100 * hi:.0f})" if n else "-"


def main(results: Path, out: Path, include_demo: bool = False):
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for f in sorted(results.glob("o1*/summary.json")):
        s = json.loads(f.read_text())
        tag = f.parent.name
        chart_o1(s, out / f"{tag}_false_alarms.png")
        has_p = chart_paired(s, out / f"{tag}_paired.png")
        rows = [[r["label"], r["threshold"], pct(r["detected"], r["n_faulty"]) if r["n_faulty"] else "no constructed fault",
                 pct(r["false_alarms"], r["n_good"]), r["auc"] if r["auc"] is not None else "-"]
                for r in s["per_criterion"]]
        sec = (f"<h2>O1 Criterion detection: {html.escape(s['subset'])}</h2>"
               f"<p class=src>Source: {html.escape(str(f))}. Images {s['n_images']} ({s['n_good']} good, "
               f"{s['n_degraded']} with one known fault). Spec v1.3 thresholds. Brackets: 95% Wilson CI.</p>"
               + table(["Criterion", "Threshold", "Detects its fault", "False alarms on good", "AUC"], rows)
               + f"<img src='{tag}_false_alarms.png'>")
        if has_p:
            sec += "<h3>Paired within product</h3>" + table(
                ["Fault", "Criterion", "Pairs", "Lower than clean", "Below threshold", "Median change", "Sign test p (descriptive)"],
                [[r["fault"], LABEL[r["criterion"]], r["n_pairs"], r["score_lower_than_clean"],
                  r["flagged_below_threshold"], r["median_change"], r["sign_test_p_one_sided"]]
                 for r in s["paired"]]) + f"<img src='{tag}_paired.png'>"
        v = s.get("verdict", {})
        if v.get("n"):
            sec += "<h3>Framework verdict</h3>" + table(
                ["", "Rejected", "Passed"], [["Degraded", v["degraded_rejected"], v["degraded_passed"]],
                                           ["Good", v["good_rejected"], v["good_passed"]]]) + (
                f"<p>Sensitivity {v['sensitivity']}, specificity {v['specificity']}, balanced accuracy "
                f"{v['balanced_accuracy']}, MCC {v['mcc']}.</p>")
        parts.append(sec)
    for f in sorted(results.glob("ai*/summary.json")):
        s = json.loads(f.read_text())
        tag = f.parent.name
        chart_ai(s, out / f"{tag}_colour.png")
        chart_masking(s, out / f"{tag}_masking.png")
        rows = [[r["description"], r["level"], r["group"], r["n"],
                 f"{r['masked_sharpness']} of {r['failing_before_sharpness']}", f"{r['d_sharpness']:+.3f}",
                 f"{r['d_colorcast']:+.3f}", r["median_product_deltaE"]]
                for r in s["summary"] if r["level"] in (1, 3)]
        parts.append("<h2>Threat to validity: phone-style automatic enhancement</h2>"
                     f"<p class=src>Source: {html.escape(str(f))}. Simulated operators, not vendor algorithms.</p>"
                     + table(["Operator", "Level", "Group", "n", "T1 fail->pass", "T1 change", "T6 change",
                              "Product dE (median)"], rows) + f"<img src='{tag}_masking.png'><img src='{tag}_colour.png'>")
    for f in sorted(results.glob("system*/summary.json")):
        s = json.loads(f.read_text())
        rows = [["Live guidance, server time per frame (224 px)", f"median {s['guidance_ms']['median']} ms, p90 {s['guidance_ms']['p90']} ms", s['guidance_ms']['n']],
                ["Technical scoring per photo", f"median {s['technical_scoring_ms']['median']} ms, p90 {s['technical_scoring_ms']['p90']} ms", s['technical_scoring_ms']['n']],
                ["Same photo scored twice", f"{s['determinism']['identical_rescores']} identical; max difference {s['determinism'].get('max_abs_score_difference', '-')}", s['determinism']['of']],
                ["View signature after JPEG re-encoding", f"max distance {s['view_signature_jpeg75']['max_distance']}; false 'different view' {s['view_signature_jpeg75']['false_different_views']}", s['view_signature_jpeg75']['of']]]
        if s.get("video_render"):
            rows.append(["Video render", f"{s['video_render']['seconds']} s for a {s['video_render']['video_seconds']} s video", 1])
        if s.get("tests"):
            rows.append(["Automated tests", s["tests"]["summary"], s["tests"].get("passed", "-")])
        parts.append("<h2>Software quality (ISO/IEC 25010:2023)</h2>"
                     f"<p class=src>Source: {html.escape(str(f))}. Network time excluded.</p>"
                     + table(["Measure", "Result", "n"], rows))
    for f in sorted(results.glob("dq*/device_qualification.json")):
        s = json.loads(f.read_text())
        for name, d in s["devices"].items():
            parts.append(f"<h2>Device and environment qualification: {html.escape(d['device'])} - {d['verdict']}</h2>"
                         + table(["Test", "Status", "Measured", "Limit"],
                                 [[t["test"], t["status"], t["measured"], t["limit"]]
                                  for t in d["device_tests"] + d["environment_tests"]]))
    for f in sorted(results.glob("study*/study_summary.json")):
        s = json.loads(f.read_text())
        o2, o3, o4 = s["O2"], s["O3"], s["O4"]
        rows = [["Participants / sessions", f"{s['participants']} / {s['sessions']}", ""]]
        for m, lab in (("fqs", "O2 FQS (primary), guided - unguided"), ("tqs", "O2 TQS (secondary)")):
            t = o2.get(m, {})
            if "p_one_sided" in t:
                rows.append([lab, f"HL {t['hodges_lehmann']} (95% CI {t['hl_95ci']}), Wilcoxon one-sided "
                             f"p = {t['p_one_sided']}, r = {t['effect_size_r']}, guided better in "
                             f"{t['guided_better']}", t["n_participants"]])
        c = o2.get("certified_first")
        if c:
            rows.append(["O2 first set certified", f"guided {c['guided_rate']} vs unguided {c['unguided_rate']}, "
                         f"McNemar exact p = {c['mcnemar_exact_p']}", c["pairs"]])
        b = o2.get("blind_preference")
        if isinstance(b, dict):
            rows.append(["O2 blind photographer preference (per participant)",
                         f"{b['participants_guided']} guided vs {b['participants_unguided']} unguided "
                         f"(share {b['share_guided']}, 95% CI {b['wilson_95ci']}), binomial p = "
                         f"{b['binomial_p_one_sided']}; {b['pairs']} pairs, {b['raters']} raters", b["participants"]])
        else:
            rows.append(["O2 blind photographer preference", "not collected", ""])
        rows.append(["O2 pre-registered claim 'measurably improves'",
                     "MET" if o2.get("claim_measurably_improves") else "NOT MET", ""])
        for k, lab in (("participants_guided", "O3 framework set vs participant's own picks (guided)"),
                       ("participants_unguided", "O3 framework set vs participant's own picks (unguided)"),
                       ("experts", "O3 framework set vs experts' blind picks")):
            if k in o3:
                v = o3[k]
                rows.append([lab, f"mean Jaccard {v['mean_jaccard']}, kappa {v['cohen_kappa_photos']}",
                             v.get("sessions", v.get("sets_rated"))])
        if "sus" in o4:
            u = o4["sus"]
            rows.append(["O4 SUS", f"{u['mean']} (SD {u['sd']}, 95% CI {u['ci95']}), {u['adjective']}; "
                         f"vs 68 p = {u['vs_68_p']}", u["n"]])
        for k, t in (o4.get("tasks") or {}).items():
            rows.append([f"O4 task: {k}", f"{t['completed']}/{t['n']} completed (95% CI {t['completion_ci95']}), "
                         f"median {t['median_time_s']} s", t["n"]])
        parts.append("<h2>Participant evaluation (O2-O4)</h2>"
                     f"<p class=src>Source: {html.escape(str(f))}.</p>" + table(["Measure", "Result", "n"], rows))
    for f in sorted(results.glob("participants*/participants_summary.json")):
        s = json.loads(f.read_text())
        if s.get("SYNTHETIC_DEMO_DO_NOT_REPORT") and not include_demo:
            continue
        warn = "<p class=warn>SYNTHETIC DEMO DATA - pipeline check only, not a result.</p>" \
            if s.get("SYNTHETIC_DEMO_DO_NOT_REPORT") else ""
        o2, o3, o4 = s["O2"], s["O3"], s["O4"]
        rows = []
        if "fqs" in o2:
            t = o2["fqs"]
            rows.append(["O2 framework score (FQS), guided - unguided", f"HL {t['hodges_lehmann']} (95% CI {t['hl_95ci']}), "
                         f"Wilcoxon p = {t['p_one_sided']}, r = {t['effect_size_r']}", t["n_participants"]])
        if "blind_preference" in o2:
            b = o2["blind_preference"]
            rows.append(["O2 blind preference for the guided photo", f"{b['share_guided']} (95% CI {b['wilson_95ci']}), "
                         f"binomial p = {b['binomial_p_one_sided']}", b["judgements"]])
        rows.append(["O2 pre-registered claim 'measurably improves'", "MET" if o2.get("claim_measurably_improves") else "NOT MET", ""])
        for who in ("participant", "expert"):
            if who in o3:
                rows.append([f"O3 overlap with {who} picks", f"mean Jaccard {o3[who]['mean_jaccard']}, kappa {o3[who]['cohen_kappa_images']}", o3[who]["sets"]])
        if "sus" in o4:
            u = o4["sus"]
            rows.append(["O4 SUS", f"{u['mean']} (SD {u['sd']}, 95% CI {u['ci95']}), {u['adjective']}; vs 68 p = {u['vs_68_p']}", u["n"]])
        for k, t in (o4.get("tasks") or {}).items():
            rows.append([f"O4 task completion: {k}", f"{t['completed']}/{t['n']} (95% CI {t['completion_ci95']}), median {t['median_time_s']} s", t["n"]])
        parts.append("<h2>Participant evaluation (O2-O4)</h2>" + warn
                     + table(["Measure", "Result", "n"], rows))
    css = ("body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#fcfcfb;color:#0b0b0b}"
           ".w{max-width:980px;margin:0 auto;padding:24px 16px 60px}h1{margin:0 0 6px}"
           "h2{margin-top:36px;border-top:1px solid #e4e3df;padding-top:18px}"
           "table{border-collapse:collapse;width:100%;font-size:14px;margin:10px 0}"
           "th,td{border-bottom:1px solid #e4e3df;padding:6px 8px;text-align:left;vertical-align:top}"
           "th{color:#52514e;font-weight:600}img{max-width:100%;margin:10px 0}"
           ".src{color:#52514e;font-size:13px}.warn{background:#fff3e0;padding:8px;border-radius:6px}")
    doc = (f"<!doctype html><meta charset=utf-8><title>PQF evaluation report</title><style>{css}</style>"
           f"<div class=w><h1>PQF evaluation report</h1><p class=src>Generated {date.today()} by "
           f"research/evaluation/build_report.py. Every figure is computed from the files named under it.</p>"
           + "".join(parts) + "</div>")
    (out / "report.html").write_text(doc, encoding="utf-8")
    print("wrote", out / "report.html")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--include-demo", action="store_true", help="show SYNTHETIC demo data (testing only)")
    a = ap.parse_args()
    main(a.results, a.out, a.include_demo)
