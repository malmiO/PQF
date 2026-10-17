"""
abo_extend.py  -  the ABO CALIBRATION EXTENSION (decisions.md 2026-10-08).

WHY. The frozen ABO set has 25 calibration images, too few to place a 10th percentile
(the T4/T5 rule) with any precision. This adds about 60 new good catalogue images per
research category, used for CALIBRATION ONLY. The frozen split_v1 and its holdout are not
touched, and no extension image is ever scored as holdout.

HOW (same rules as the frozen set, abo_select.py, so the two are comparable):
  - same ABO categories as the frozen set (fashion accessories, cosmetics and care),
    same MIN_DIM, main image of each listing;
  - a NEW seed (20261008), recorded here and in the manifest;
  - every image id AND item id already in data/abo is excluded;
  - you review the samples by eye with the same rule as before (plain or white
    background, single product, sharp, no text banner or collage) and delete rejects;
  - originals are fetched into data/abo_extension/<category>/.

Usage, from the folder where the ABO archives are extracted (images/, listings/):
  python <repo>/research/dataset_tools/abo_extend.py --sample  --frozen <repo>/data/abo
  (delete rejects in dataset_review_ext/<category>/)
  python <repo>/research/dataset_tools/abo_extend.py --fetch   --out <repo>/data/abo_extension
Write the kept count per category and the seed into decisions.md.
"""
import argparse
import csv
import os
import random
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import abo_select as A  # noqa: E402  (reuses its readers; nothing in it is changed)

SEED = 20261008
PER_CATEGORY = 60
# Folder names used in the frozen set -> ABO product types (from abo_select.CATEGORY_MAP)
CATEGORIES = {"fashion_accessories": A.CATEGORY_MAP["fashion_accessories"],
              "cosmetics_care": A.CATEGORY_MAP["cosmetics"]}
REVIEW = "dataset_review_ext"
MANIFEST = "dataset_manifest_ext.csv"


def frozen_ids(frozen: Path):
    ids = {p.stem for p in frozen.rglob("*") if p.is_file()}
    items = set()
    for m in frozen.rglob("*manifest*.csv"):
        with open(m, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ids.add(r.get("abo_image_id", ""))
                items.add(r.get("abo_item_id", ""))
    return ids - {""}, items - {""}


def sample(frozen: Path):
    rnd = random.Random(SEED)
    img_idx = A.load_image_index()
    skip_img, skip_item = frozen_ids(frozen)
    print(f"Excluding {len(skip_img)} frozen image ids and {len(skip_item)} item ids")
    t2c = {t: c for c, ts in CATEGORIES.items() for t in ts}
    cand = defaultdict(list)
    for item in A.iter_listings():
        cat = t2c.get(A.norm_product_type(item.get("product_type")))
        mid, iid = item.get("main_image_id"), item.get("item_id", "")
        if not cat or not mid or mid not in img_idx or mid in skip_img or iid in skip_item:
            continue
        meta = img_idx[mid]
        if max(meta["height"], meta["width"]) < A.MIN_DIM:
            continue
        cand[cat].append((iid, mid))
    rows = []
    for cat, pool in cand.items():
        pool.sort()                      # deterministic before sampling
        picks = rnd.sample(pool, min(PER_CATEGORY, len(pool)))
        os.makedirs(os.path.join(REVIEW, cat), exist_ok=True)
        for iid, mid in picks:
            meta = img_idx[mid]
            src = os.path.join(A.SMALL_DIR, meta["path"])
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(meta["path"])[1]
            shutil.copyfile(src, os.path.join(REVIEW, cat, mid + ext))
            rows.append({"filename": mid + ext, "category": cat, "abo_item_id": iid,
                         "abo_image_id": mid, "abo_path": meta["path"],
                         "orig_height": meta["height"], "orig_width": meta["width"],
                         "seed": SEED, "use": "calibration_extension",
                         "source": "ABO (CC BY 4.0, credit Amazon.com)"})
        print(f"{cat:<22} candidates={len(pool):>6}  sampled={len(picks)}")
    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"Review {REVIEW}/ and delete rejects, then run --fetch.")


def fetch(out: Path):
    import requests
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if os.path.exists(os.path.join(REVIEW, r["category"], r["filename"]))]
    print(f"{len(kept)} of {len(rows)} kept after review")
    for r in kept:
        d = out / r["category"]
        d.mkdir(parents=True, exist_ok=True)
        dst = d / r["filename"]
        if dst.exists():
            continue
        ext = os.path.splitext(r["abo_path"])[1].lstrip(".")
        try:
            resp = requests.get(f"https://m.media-amazon.com/images/I/{r['abo_image_id']}.{ext}",
                                timeout=30)
            resp.raise_for_status()
            dst.write_bytes(resp.content)
            r["resolution"] = "original"
        except Exception as e:
            print(f"FAIL {r['filename']} ({e}); using the small copy")
            shutil.copyfile(os.path.join(REVIEW, r["category"], r["filename"]), dst)
            r["resolution"] = "small fallback"
    with open(out / "manifest_extension.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(kept[0]))
        w.writeheader()
        w.writerows(kept)
    by = defaultdict(int)
    for r in kept:
        by[r["category"]] += 1
    print(f"Done: {dict(by)} in {out}. Record these counts and seed {SEED} in decisions.md.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sample", action="store_true")
    g.add_argument("--fetch", action="store_true")
    ap.add_argument("--frozen", type=Path, help="the frozen data/abo folder (for exclusions)")
    ap.add_argument("--out", type=Path, default=Path("abo_extension"))
    a = ap.parse_args()
    if a.sample:
        if not a.frozen:
            sys.exit("--sample needs --frozen <repo>/data/abo")
        sample(a.frozen)
    else:
        fetch(a.out)
