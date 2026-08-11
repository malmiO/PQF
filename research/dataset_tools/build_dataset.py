"""
build_dataset.py — Final PQF dataset assembly + one-time stratified split.

Run from the `dataset/` root (the folder containing abo/ and phone/):

  Step 1 — build & merge manifests, check counts (safe to re-run):
      python build_dataset.py --assemble

  Step 2 — the ONE-TIME split (refuses to overwrite an existing split):
      python build_dataset.py --split

Filename convention for phone images (enforced):
  phone/validation/<category>/pNN_CODE.jpg
  CODE ∈ CLEAN | V-BLUR | V-DARK | V-BRIGHT | V-CLUTTER | V-OFFCENTRE | V-ANGLE
"""

import argparse, csv, os, random, re, sys
from collections import Counter, defaultdict

ABO_DIR = "abo"
ABO_MANIFEST = os.path.join(ABO_DIR, "dataset_manifest_final.csv")
PHONE_DIR = os.path.join("phone", "validation")
MASTER = "master_manifest.csv"
SPLIT_FILE = os.path.join("splits", "split_v1.csv")

CALIBRATION_FRACTION = 0.40   # 40% calibration / 60% holdout (spec §6.2)
SEED = 20260711               # fixed & reported: reproducible split

CODE_MAP = {          # code -> (role, violated_criterion)
    "CLEAN":       ("good",     ""),
    "V-BLUR":      ("degraded", "T1"),
    "V-DARK":      ("degraded", "T2"),
    "V-BRIGHT":    ("degraded", "T2"),
    "V-CLUTTER":   ("degraded", "T3"),
    "V-OFFCENTRE": ("degraded", "S1"),
    "V-ANGLE":     ("degraded", "S4"),
}
FNAME_RE = re.compile(r"^(p\d{2})_(" + "|".join(CODE_MAP) + r")\.(jpg|jpeg|png)$",
                      re.IGNORECASE)

FIELDS = ["filename", "relpath", "category", "source", "role",
          "violated_criterion", "product_id", "abo_item_id", "licence"]


def build_phone_rows():
    rows, problems = [], []
    if not os.path.isdir(PHONE_DIR):
        sys.exit(f"Missing {PHONE_DIR}/ — create it and add renamed images.")
    for cat in sorted(os.listdir(PHONE_DIR)):
        catdir = os.path.join(PHONE_DIR, cat)
        if not os.path.isdir(catdir):
            continue
        for fname in sorted(os.listdir(catdir)):
            m = FNAME_RE.match(fname)
            if not m:
                problems.append(os.path.join(cat, fname))
                continue
            pid, code = m.group(1).lower(), m.group(2).upper()
            role, crit = CODE_MAP[code]
            rows.append({
                "filename": fname,
                "relpath": os.path.join(PHONE_DIR, cat, fname),
                "category": cat,
                "source": "phone_capture",
                "role": role,
                "violated_criterion": crit,
                "product_id": pid,
                "abo_item_id": "",
                "licence": "own capture",
            })
    return rows, problems


def build_abo_rows():
    if not os.path.exists(ABO_MANIFEST):
        sys.exit(f"Missing {ABO_MANIFEST} — did you rename dataset_final to abo/ ?")
    rows = []
    with open(ABO_MANIFEST, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append({
                "filename": r["filename"],
                "relpath": os.path.join(ABO_DIR, r["category"], r["filename"]),
                "category": r["category"],
                "source": "ABO",
                "role": "good",
                "violated_criterion": "",
                "product_id": "",
                "abo_item_id": r.get("abo_item_id", ""),
                "licence": "CC BY 4.0 (credit Amazon.com)",
            })
    return rows


def assemble():
    abo = build_abo_rows()
    phone, problems = build_phone_rows()
    allrows = abo + phone

    # verify every file actually exists on disk
    missing = [r["relpath"] for r in allrows if not os.path.exists(r["relpath"])]

    with open(MASTER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(allrows)

    print(f"master_manifest.csv written: {len(allrows)} images "
          f"({len(abo)} ABO + {len(phone)} phone)\n")
    print(f"{'category':<22}{'good':>6}{'degraded':>10}{'total':>8}")
    cats = sorted({r['category'] for r in allrows})
    for cat in cats:
        g = sum(1 for r in allrows if r["category"] == cat and r["role"] == "good")
        d = sum(1 for r in allrows if r["category"] == cat and r["role"] == "degraded")
        print(f"{cat:<22}{g:>6}{d:>10}{g+d:>8}")
    g = sum(1 for r in allrows if r["role"] == "good")
    d = len(allrows) - g
    print(f"{'TOTAL':<22}{g:>6}{d:>10}{len(allrows):>8}\n")

    viol = Counter(r["violated_criterion"] for r in allrows if r["role"] == "degraded")
    print("violations by criterion:", dict(sorted(viol.items())))

    if problems:
        print(f"\nWARNING — {len(problems)} phone files do NOT match the "
              f"pNN_CODE naming convention and were SKIPPED:")
        for pr in problems[:15]:
            print("  ", pr)
        print("Fix these names and re-run --assemble.")
    if missing:
        print(f"\nWARNING — {len(missing)} manifest rows point to files "
              f"missing on disk:")
        for m in missing[:15]:
            print("  ", m)
    if not problems and not missing:
        print("\nAll files matched and present. Ready for --split.")


def split():
    if os.path.exists(SPLIT_FILE):
        sys.exit(f"{SPLIT_FILE} already exists. The split is done ONCE and "
                 f"frozen (spec §6.2). Delete it manually only if you truly "
                 f"know why — and log that in decisions.md.")
    if not os.path.exists(MASTER):
        sys.exit("Run --assemble first.")

    with open(MASTER, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    # Stratify by (category, role). Keep each phone PRODUCT's images together
    # (a product's clean+violations must not straddle the split — the pairs
    # are only meaningful on the same side).
    rng = random.Random(SEED)
    assignment = {}

    # 1) phone images: assign whole products within (category) strata
    products = defaultdict(list)      # (category, product_id) -> rows
    for r in rows:
        if r["source"] == "phone_capture":
            products[(r["category"], r["product_id"])].append(r)
    by_cat = defaultdict(list)
    for (cat, pid), prs in products.items():
        by_cat[cat].append((pid, prs))
    for cat, plist in by_cat.items():
        plist.sort()
        rng.shuffle(plist)
        n_cal = max(1, round(len(plist) * CALIBRATION_FRACTION))
        for i, (pid, prs) in enumerate(plist):
            part = "calibration" if i < n_cal else "holdout"
            for r in prs:
                assignment[r["relpath"]] = part

    # 2) ABO images: plain stratified by category
    abo_by_cat = defaultdict(list)
    for r in rows:
        if r["source"] == "ABO":
            abo_by_cat[r["category"]].append(r)
    for cat, rlist in abo_by_cat.items():
        rlist.sort(key=lambda r: r["filename"])
        rng.shuffle(rlist)
        n_cal = round(len(rlist) * CALIBRATION_FRACTION)
        for i, r in enumerate(rlist):
            assignment[r["relpath"]] = "calibration" if i < n_cal else "holdout"

    os.makedirs("splits", exist_ok=True)
    with open(SPLIT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["relpath", "split", "seed"])
        for r in rows:
            w.writerow([r["relpath"], assignment[r["relpath"]], SEED])

    print(f"{SPLIT_FILE} written (seed={SEED}). Summary:\n")
    print(f"{'category':<22}{'cal good':>9}{'cal degr':>9}{'hold good':>10}{'hold degr':>10}")
    cats = sorted({r['category'] for r in rows})
    for cat in cats:
        cg = sum(1 for r in rows if r["category"] == cat and r["role"] == "good"
                 and assignment[r["relpath"]] == "calibration")
        cd = sum(1 for r in rows if r["category"] == cat and r["role"] == "degraded"
                 and assignment[r["relpath"]] == "calibration")
        hg = sum(1 for r in rows if r["category"] == cat and r["role"] == "good"
                 and assignment[r["relpath"]] == "holdout")
        hd = sum(1 for r in rows if r["category"] == cat and r["role"] == "degraded"
                 and assignment[r["relpath"]] == "holdout")
        print(f"{cat:<22}{cg:>9}{cd:>9}{hg:>10}{hd:>10}")
    ncal = sum(1 for v in assignment.values() if v == "calibration")
    print(f"\nTotal: {ncal} calibration / {len(rows)-ncal} holdout "
          f"({ncal/len(rows):.0%} / {(len(rows)-ncal)/len(rows):.0%})")
    print("\nTHE SPLIT IS NOW FROZEN. All threshold tuning: calibration only.")
    print("Log this in decisions.md with the seed and today's date.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--assemble", action="store_true")
    g.add_argument("--split", action="store_true")
    args = ap.parse_args()
    (assemble if args.assemble else split)()
