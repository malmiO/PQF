"""
decode_blind.py  -  turn the photographers' blind A/B answers into guided/unguided.

Raters see only blind_pairs/ (pair_<id>_A.jpg, pair_<id>_B.jpg, sides random). Their
answers go in o2_blind_preference.csv (rater, pair_id, preferred = A | B | tie). The
key blind_key.csv (pair_id, A_is = guided | unguided) is kept away from the raters.
Output: o2_blind_preference_decoded.csv (rater, pair_id, preferred = guided|unguided|tie),
the file analysis_participants.py reads.

Usage: python research/evaluation/decode_blind.py --dir <session export folder>
"""
from __future__ import annotations

import argparse
from pathlib import Path

from evalcommon import read_csv, write_csv


def decode(answers: list, key: list) -> list:
    k = {r["pair_id"]: r["A_is"].strip().lower() for r in key}
    out = []
    for r in answers:
        pid, pref = r["pair_id"], r["preferred"].strip().upper()
        if pid not in k:
            raise SystemExit(f"pair {pid} is not in the key")
        if k[pid] not in ("guided", "unguided"):
            raise SystemExit(f"key for {pid} must be guided or unguided")
        if pref == "TIE":
            v = "tie"
        elif pref == "A":
            v = k[pid]
        elif pref == "B":
            v = "unguided" if k[pid] == "guided" else "guided"
        else:
            raise SystemExit(f"answer {r['preferred']!r} for {pid}: use A, B or tie")
        out.append({"rater": r["rater"], "pair_id": pid, "preferred": v})
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    a = ap.parse_args()
    rows = decode(read_csv(a.dir / "o2_blind_preference.csv"), read_csv(a.dir / "blind_key.csv"))
    write_csv(a.dir / "o2_blind_preference_decoded.csv", rows)
    print(f"decoded {len(rows)} answers -> {a.dir / 'o2_blind_preference_decoded.csv'}")
