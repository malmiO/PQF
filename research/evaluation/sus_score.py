"""
sus_score.py  -  System Usability Scale scoring from the Google Form CSV export (2026-10-15).

Brooke (1996): odd items score x - 1, even items score 5 - x, the sum is multiplied by 2.5
(0-100). Reports mean, SD, a 95 % t confidence interval, the Bangor et al. (2009) adjective
and the distance from the Sauro and Lewis (2016) benchmark of 68.

Input: the form's CSV. The 10 SUS items are found by header ("1.", "Q1", "SUS 1", "Item 1" ...
numbered 1-10) or, failing that, are the FIRST 10 columns whose answers are all integers 1-5.
Extra items (age, free text, ...) are ignored. Force the columns with --item-cols 2-11
(1-based, inclusive). A respondent with a missing SUS item is listed and left out.

  python research/evaluation/sus_score.py --csv form.csv --out research/results/study/sus
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics as st
from pathlib import Path

from scipy import stats

# Bangor, Kortum & Miller (2009), mean SUS of each adjective rating; the nearest wins.
BANGOR = [(12.5, "Worst imaginable"), (20.3, "Awful"), (35.7, "Poor"), (50.9, "OK"),
          (71.4, "Good"), (85.5, "Excellent"), (90.9, "Best imaginable")]
BENCHMARK = 68.0
HEADER = re.compile(r"^\s*(?:sus\s*)?(?:q|item)?\s*0?(\d{1,2})\s*[\.\):\-]?(\s|$)", re.IGNORECASE)


def adjective(score: float) -> str:
    return min(BANGOR, key=lambda a: abs(a[0] - score))[1]


def sus_item_score(position: int, x: int) -> int:
    """position 1-10; odd items x - 1, even items 5 - x."""
    return x - 1 if position % 2 == 1 else 5 - x


def respondent_score(answers: list) -> float:
    if len(answers) != 10 or any(not (1 <= a <= 5) for a in answers):
        raise ValueError("a SUS response is 10 answers, each 1-5")
    return 2.5 * sum(sus_item_score(i, a) for i, a in enumerate(answers, 1))


def _int(v):
    m = re.match(r"^\s*([1-5])\b", str(v or ""))
    return int(m.group(1)) if m else None


def find_item_columns(header: list, rows: list, forced: str | None = None) -> list:
    """Indices of SUS items 1..10, in order."""
    if forced:
        lo, hi = (int(x) for x in forced.split("-"))
        cols = list(range(lo - 1, hi))
        if len(cols) != 10:
            raise SystemExit("--item-cols must span exactly 10 columns")
        return cols
    named = {}
    for i, h in enumerate(header):
        m = HEADER.match(h or "")
        if m and 1 <= int(m.group(1)) <= 10 and int(m.group(1)) not in named:
            named[int(m.group(1))] = i
    if len(named) == 10:
        return [named[k] for k in range(1, 11)]
    cols = []
    for i in range(len(header)):
        vals = [r[i] for r in rows if i < len(r) and str(r[i]).strip()]
        if vals and all(_int(v) is not None for v in vals):
            cols.append(i)
    if len(cols) < 10:
        raise SystemExit(f"found {len(cols)} columns of 1-5 answers, need 10: use --item-cols")
    return cols[:10]


def score_csv(path: Path, forced: str | None = None) -> dict:
    with open(path, newline="", encoding="utf-8-sig") as f:
        data = list(csv.reader(f))
    header, rows = data[0], [r for r in data[1:] if any(c.strip() for c in r)]
    cols = find_item_columns(header, rows, forced)
    scores, skipped = [], []
    for n, r in enumerate(rows, 1):
        vals = [_int(r[c]) if c < len(r) else None for c in cols]
        if any(v is None for v in vals):
            skipped.append(n)
            continue
        scores.append({"respondent": n, "sus": respondent_score(vals), "answers": vals})
    return {"items": [header[c] for c in cols], "scores": scores, "skipped_rows": skipped}


def summarise(scores: list) -> dict:
    v = [s["sus"] for s in scores]
    n = len(v)
    if not n:
        return {"n": 0}
    out = {"n": n, "mean": round(st.mean(v), 2), "min": min(v), "max": max(v)}
    out["adjective"] = adjective(out["mean"])
    if n >= 2:
        sd = st.stdev(v)
        h = stats.t.ppf(0.975, n - 1) * sd / n ** 0.5
        t = stats.ttest_1samp(v, BENCHMARK)
        out.update({"sd": round(sd, 2), "ci95": [round(out["mean"] - h, 2), round(out["mean"] + h, 2)],
                    "t_vs_68": round(float(t.statistic), 3), "p_two_sided_vs_68": round(float(t.pvalue), 4)})
    else:
        out["note"] = "n = 1: no SD or interval"
    out["below_50_preregistered_failure"] = out["mean"] < 50
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--item-cols", help="1-based inclusive, e.g. 2-11")
    a = ap.parse_args()
    r = score_csv(a.csv, a.item_cols)
    s = summarise(r["scores"])
    print(json.dumps({"summary": s, "skipped_rows": r["skipped_rows"],
                      "item_columns": r["items"]}, indent=1))
    if a.out:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "sus_summary.json").write_text(json.dumps({"summary": s, **r}, indent=1),
                                                encoding="utf-8")
        with open(a.out / "sus_scores.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["respondent", "sus", "adjective"])
            for x in r["scores"]:
                w.writerow([x["respondent"], x["sus"], adjective(x["sus"])])
