"""
make_blind_packs.py  -  build the BLIND material for the photographers and experts
from the study log and the study photos copied off the phones (2026-10-07).

Inputs
  --log     research/results/study_log.jsonl (server copy) or the phone's copy
  --photos  a folder with the study photos exported from the phones (any file names;
            each photo is matched by its SHA-256, which is what the log records)
  --out     output folder (keep it OUTSIDE anything the raters see except the packs)
  --seed    random seed, recorded in the key files (default 20261007)

Outputs
  blind_pairs/pair_<id>_A.jpg, _B.jpg   for O2(b): per participant, the participant's OWN
        pick in each condition (made without seeing scores), for the slots chosen with
        --slots (pre-register the choice): "main" (default, 1 pair per participant) or
        "all" (main, angle1, angle2, detail: 4 pairs per participant, analysed per
        participant so pairs from one person are not counted as independent). Sides random.
  rater_sheet.csv                       rater, pair_id, preferred (A | B | tie) - to fill in
  blind_key.csv                         pair_id, A_is (guided | unguided)  - NOT for raters
  expert_sets/set_<id>/img_<n>.jpg      for O3: all photos of each participant's GUIDED
        session, renamed; experts pick the 4 they would use (main, 2 angles, detail)
  expert_sheet.csv                      expert, set_id, image, picked (0/1) - to fill in
  expert_key.csv                        set_id, image, sha256, participant  - NOT for experts
Raters and experts get only blind_pairs/ + rater_sheet.csv, or expert_sets/ + expert_sheet.csv.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path

from evalcommon import write_csv

IMG = {".jpg", ".jpeg", ".png"}


def load_log(p: Path) -> list:
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            if not str(e.get("product", "")).upper().startswith("SMOKE"):
                out.append(e)
    return out


def index_photos(folder: Path) -> dict:
    return {hashlib.sha256(f.read_bytes()).hexdigest(): f
            for f in folder.rglob("*") if f.suffix.lower() in IMG}


def build(log: list, photos: dict, out: Path, seed: int, slots=("main",)) -> dict:
    rng = random.Random(seed)
    picks = defaultdict(dict)       # participant -> condition -> own_picks
    captured = defaultdict(dict)    # participant -> condition -> photo hashes
    for e in log:
        if e["event"] == "own_picks":
            picks[e["participant"]][e["condition"]] = e.get("own_picks", {})
        if e["event"] == "capture_end" and e.get("photo_hashes"):
            captured[e["participant"]].setdefault(e["condition"], e["photo_hashes"])
    missing = set()
    # O2(b) blind pairs
    pairs_dir = out / "blind_pairs"
    pairs_dir.mkdir(parents=True, exist_ok=True)
    key, sheet = [], []
    for pid, slot in [(p, sl) for p in sorted(picks) for sl in slots]:
        g = picks[pid].get("GUIDED", {}).get(slot)
        u = picks[pid].get("UNGUIDED", {}).get(slot)
        if not g or not u:
            continue
        if g not in photos or u not in photos:
            missing |= {h for h in (g, u) if h not in photos}
            continue
        pair_id = f"{rng.randrange(16**6):06x}"
        a_is = rng.choice(["guided", "unguided"])
        a, b = (g, u) if a_is == "guided" else (u, g)
        shutil.copy2(photos[a], pairs_dir / f"pair_{pair_id}_A{photos[a].suffix.lower()}")
        shutil.copy2(photos[b], pairs_dir / f"pair_{pair_id}_B{photos[b].suffix.lower()}")
        key.append({"pair_id": pair_id, "A_is": a_is, "participant": pid, "slot": slot,
                    "seed": seed})
        sheet.append({"rater": "", "pair_id": pair_id, "preferred": ""})
    rng.shuffle(sheet)
    write_csv(out / "blind_key.csv", key)
    write_csv(out / "rater_sheet.csv", sheet)
    # O3 expert sets: the GUIDED session's photos
    ekey, esheet = [], []
    for pid in sorted(captured):
        hashes = [h for h in captured[pid].get("GUIDED", []) if h in photos]
        missing |= {h for h in captured[pid].get("GUIDED", []) if h not in photos}
        if not hashes:
            continue
        set_id = f"{rng.randrange(16**4):04x}"
        d = out / "expert_sets" / f"set_{set_id}"
        d.mkdir(parents=True, exist_ok=True)
        order = hashes[:]
        rng.shuffle(order)
        for n, h in enumerate(order, 1):
            name = f"img_{n:02d}{photos[h].suffix.lower()}"
            shutil.copy2(photos[h], d / name)
            ekey.append({"set_id": set_id, "image": name, "sha256": h, "participant": pid})
            esheet.append({"expert": "", "set_id": set_id, "image": name, "picked": ""})
    write_csv(out / "expert_key.csv", ekey)
    write_csv(out / "expert_sheet.csv", esheet)
    return {"pairs": len(key), "expert_sets": len({k['set_id'] for k in ekey}),
            "missing_photos": len(missing)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--photos", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=20261007)
    ap.add_argument("--slots", choices=["main", "all"], default="main")
    a = ap.parse_args()
    slots = ("main",) if a.slots == "main" else ("main", "angle1", "angle2", "detail")
    r = build(load_log(a.log), index_photos(a.photos), a.out, a.seed, slots)
    print(r)
    if r["missing_photos"]:
        print("WARNING: some logged photos were not found in --photos; export them from the phones.")
