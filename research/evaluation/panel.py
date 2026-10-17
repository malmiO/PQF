"""
panel.py  -  statistics for the AI-judge panel (J1-J3), shared by analysis_study.py --panel and
human_crosscheck.py --panel. Pure functions, no API, no image access.

Panel decision for ONE item: the choice made by at least 2 VALID judges, else TIE.
A judge's own vote is already "consistent across both presentation orders, else tie"
(ai_judges.py writes it that way); a judge with no usable answer for the item is MISSING and is
not a valid judge for it. Judges that fail the known-answer gate are excluded from the panel.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from itertools import combinations
from pathlib import Path

GATE_MIN = 0.75             # accuracy on the 24 known pairs: below this the judge is excluded


def wilson(k: int, n: int, z: float = 1.96):
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def cohen_kappa(x: list, y: list) -> float:
    n = len(x)
    if not n:
        return float("nan")
    po = sum(a == b for a, b in zip(x, y)) / n
    cx, cy = Counter(x), Counter(y)
    pe = sum(cx[c] * cy[c] for c in set(cx) | set(cy)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def fleiss_kappa(rows: list) -> float:
    """rows: one list of labels per item, every item rated by the same number (>=2) of judges."""
    rows = [r for r in rows if r]
    if not rows:
        return float("nan")
    n = len(rows[0])
    if n < 2 or any(len(r) != n for r in rows):
        return float("nan")
    cats = sorted({c for r in rows for c in r})
    N = len(rows)
    pj = {c: sum(r.count(c) for r in rows) / (N * n) for c in cats}
    Pi = [(sum(r.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for r in rows]
    pe = sum(v * v for v in pj.values())
    pbar = sum(Pi) / N
    return (pbar - pe) / (1 - pe) if pe < 1 else float("nan")


def gwet_ac1(rows: list, q: int = 3) -> float:
    """Gwet's AC1 for n>=2 raters per item and q categories (default 3: two photos + tie).
    Stable when one category dominates, where Fleiss kappa collapses."""
    rows = [r for r in rows if r]
    if not rows:
        return float("nan")
    n = len(rows[0])
    if n < 2 or any(len(r) != n for r in rows):
        return float("nan")
    cats = sorted({c for r in rows for c in r})
    pa = sum((sum(r.count(c) ** 2 for c in cats) - n) / (n * (n - 1)) for r in rows) / len(rows)
    pi = {c: sum(r.count(c) for r in rows) / (len(rows) * n) for c in cats}
    pe = sum(v * (1 - v) for v in pi.values()) / (q - 1)
    return (pa - pe) / (1 - pe) if pe < 1 else float("nan")


def panel_label(labels: list, categories=None) -> str:
    """labels: the VALID judges' labels for one item. >=2 identical non-tie labels win, else tie."""
    c = Counter(l for l in labels if l != "tie")
    for lab, k in c.most_common():
        if k >= 2:
            return lab
    return "tie"


def known_answer_gate(key_rows: list, judge_votes: dict, judges: list) -> dict:
    """key_rows: pair_key.csv rows; judge_votes: pair_id -> judge -> 'clean'|'fault'|'tie'.
    Accuracy = share of the known pairs where the judge picked the CLEAN photo; ties and missing
    answers count as wrong. Excluded when accuracy < 0.75 (i.e. < 18/24)."""
    out = {}
    n = len(key_rows)
    for j in judges:
        right = sum(judge_votes.get(r["pair_id"], {}).get(j) == "clean" for r in key_rows)
        answered = sum(j in judge_votes.get(r["pair_id"], {}) for r in key_rows)
        lo, hi = wilson(right, n)
        out[j] = {"correct": right, "of": n, "answered": answered,
                  "accuracy": round(right / n, 3) if n else None,
                  "wilson_95ci": [round(lo, 3), round(hi, 3)],
                  "ties_or_wrong": n - right,
                  "included_in_panel": bool(n and right / n >= GATE_MIN)}
    return out


def load_gate(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def included_judges(gate: dict) -> list:
    return sorted(j for j, g in gate.items() if g["included_in_panel"])


def agreement_stats(votes: dict, judges: list) -> dict:
    """votes: item -> judge -> label. Fleiss kappa over items answered by ALL judges, pairwise
    Cohen kappa over the items each pair both answered."""
    res = {"judges": judges}
    full = [[v[j] for j in judges] for v in votes.values() if all(j in v for j in judges)]
    res["items_all_judges_answered"] = len(full)
    k = fleiss_kappa(full) if len(judges) >= 2 else float("nan")
    res["fleiss_kappa"] = None if math.isnan(k) else round(k, 3)
    ac = gwet_ac1(full) if len(judges) >= 2 else float("nan")
    res["gwet_ac1"] = None if math.isnan(ac) else round(ac, 3)
    res["raw_agreement_all_judges_identical"] = (
        round(sum(len(set(r)) == 1 for r in full) / len(full), 3) if full else None)
    pw = {}
    for a, b in combinations(judges, 2):
        both = [(v[a], v[b]) for v in votes.values() if a in v and b in v]
        kk = cohen_kappa([x for x, _ in both], [y for _, y in both])
        pw[f"{a}-{b}"] = {"items": len(both), "cohen_kappa": None if math.isnan(kk) else round(kk, 3),
                          "percent_agreement": round(100 * sum(x == y for x, y in both) / len(both), 1)
                          if both else None}
    res["pairwise_cohen"] = pw
    return res


def position_consistency(consistency_rows: list, judges: list) -> dict:
    """consistency_rows: ai_judge_consistency.csv rows (judge, item_id, valid_both_orders,
    consistent). Rate = consistent / items answered validly in both orders."""
    out = {}
    for j in judges:
        rs = [r for r in consistency_rows if r["judge"] == j]
        both = [r for r in rs if str(r["valid_both_orders"]) == "True"]
        ok = sum(str(r["consistent"]) == "True" for r in both)
        out[j] = {"items": len(rs), "valid_in_both_orders": len(both), "consistent": ok,
                  "position_consistency_rate": round(ok / len(both), 3) if both else None,
                  "missing_in_some_order": len(rs) - len(both)}
    return out


# ------------------------------------------------------------------ sheet transforms (A/B frame)
def panel_pair_rows(sheet_rows: list, judges: list, id_col: str = "pair_id") -> list:
    """Judge sheet rows (rater, pair_id, preferred A|B|tie|blank) -> one PANEL row per pair:
    the choice of >= 2 valid judges (blank = missing = not valid), else tie."""
    by = {}
    for r in sheet_rows:
        p = r.get("preferred", "").strip().upper()
        if r["rater"] in judges and p:
            by.setdefault(r[id_col], {})[r["rater"]] = "tie" if p in ("TIE", "NO DIFFERENCE") else p
    ids = list(dict.fromkeys(r[id_col] for r in sheet_rows))
    out = []
    for i in ids:
        lab = panel_label(list(by.get(i, {}).values()))
        out.append({"rater": "PANEL", id_col: i, "preferred": lab if lab == "tie" else lab,
                    "strength": ""})
    return out


def panel_set_rows(sheet_rows: list, judges: list, id_col: str) -> list:
    """Per (set, role): the photo number picked by >= 2 valid judges, else blank."""
    by = {}
    for r in sheet_rows:
        n = str(r.get("photo_no", "")).strip()
        if r["rater"] in judges and n.isdigit():
            by.setdefault((r[id_col], r["role"]), []).append(n)
    ids = list(dict.fromkeys(r[id_col] for r in sheet_rows))
    out = []
    for i in ids:
        for role in ("main", "angle1", "angle2", "detail"):
            c = Counter(by.get((i, role), [])).most_common(1)
            out.append({"rater": "PANEL", id_col: i, "role": role,
                        "photo_no": c[0][0] if c and c[0][1] >= 2 else ""})
    return out


def read_consistency(folder: Path, source: str) -> list:
    import csv
    p = folder / f"ai_judge_consistency_{source}.csv"
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def pairwise_set_jaccard(sheet_rows: list, judges: list, id_col: str) -> dict:
    """Judge-vs-judge Jaccard of the four picked photos, per set, over sets where BOTH judges gave
    four distinct picks (a judge-inconsistent role = no full set = not scored, never zero)."""
    from itertools import combinations as comb
    sets = {}
    for r in sheet_rows:
        n = str(r.get("photo_no", "")).strip()
        if r["rater"] in judges and n.isdigit():
            sets.setdefault((r[id_col], r["rater"]), {})[r["role"]] = n
    full = {k: set(v.values()) for k, v in sets.items() if len(v) == 4 and len(set(v.values())) == 4}
    out = {}
    for a, b in comb(judges, 2):
        js = [len(full[(i, a)] & full[(i, b)]) / len(full[(i, a)] | full[(i, b)])
              for i in {k[0] for k in full} if (i, a) in full and (i, b) in full]
        out[f"{a}-{b}"] = {"sets_compared": len(js),
                           "mean_jaccard": round(sum(js) / len(js), 3) if js else None}
    return out
