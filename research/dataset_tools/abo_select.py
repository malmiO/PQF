"""
abo_select.py — Build a PQF validation dataset from Amazon Berkeley Objects.

USAGE (run from the folder where you extracted the archives, so that
`images/` and `listings/` directories exist):

  Pass 1 — discover what categories exist:
      python abo_select.py --discover
      -> writes product_type_counts.csv (open it, pick your category strings)

  Pass 2 — sample images per category into review folders:
      python abo_select.py --sample
      -> copies small images into dataset_review/<category>/ and
         writes dataset_manifest.csv (your provenance sheet)

  Pass 3 — after you delete unwanted images from the review folders,
  fetch full-resolution originals for the survivors:
      python abo_select.py --fetch-originals
      -> downloads originals into dataset_final/<category>/

Requires: Python 3.8+, `requests` only for pass 3 (pip install requests).
License note: ABO is CC BY 4.0 — credit Amazon.com in your dissertation.
"""

import argparse, csv, glob, gzip, json, os, random, shutil
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# EDIT THIS after running --discover: map your 5 research categories to the
# exact product_type strings found in product_type_counts.csv.
# The strings below are educated guesses — VERIFY them against the counts file.
# ---------------------------------------------------------------------------
CATEGORY_MAP = {
    "fashion_accessories": ["EARRING", "NECKLACE", "BRACELET", "JEWELRY",
                            "WATCH", "SUNGLASSES", "HANDBAG", "WALLET"],
    "clothing":            ["SHIRT", "DRESS", "PANTS", "SWEATER", "SKIRT",
                            "OUTERWEAR", "SHOES", "SANDAL"],
    "cosmetics":           ["SKIN_CARE_AGENT", "SKIN_CARE_PRODUCT",
                            "HAIR_CARE_PRODUCT", "COSMETIC_CASE", "SHAMPOO"],
    "home_decor":          ["HOME_DECOR", "VASE", "PICTURE_FRAME", "SCULPTURE",
                            "CANDLE_HOLDER", "PLANTER", "LAMP"],
    # food is expected to be thin/absent in ABO — it will come from your own
    # controlled captures instead. Leave this here so the script reports it.
    "food":                ["GROCERY", "FOOD", "SNACK_FOOD", "BEVERAGE"],
}

PER_CATEGORY = 30          # how many candidate images to sample per category
MIN_DIM = 500              # skip images whose original is smaller than this
SEED = 42                  # fixed seed -> reproducible sampling (report it!)

IMAGES_CSV = "images/metadata/images.csv.gz"
LISTING_GLOB = "listings/metadata/listings_*.json.gz"
SMALL_DIR = "images/small"
REVIEW_DIR = "dataset_review"
FINAL_DIR = "dataset_final"
MANIFEST = "dataset_manifest.csv"


def norm_product_type(raw):
    """product_type may be a string or a list of {'value': ...} dicts."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip().upper()
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            return str(first.get("value", "")).strip().upper()
        return str(first).strip().upper()
    return ""


def iter_listings():
    files = sorted(glob.glob(LISTING_GLOB))
    if not files:
        raise SystemExit(f"No listing files found at {LISTING_GLOB} — "
                         "run this script from the extraction root.")
    for fn in files:
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def load_image_index():
    if not os.path.exists(IMAGES_CSV):
        raise SystemExit(f"{IMAGES_CSV} not found — extract abo-images-small.tar first.")
    idx = {}
    with gzip.open(IMAGES_CSV, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            idx[row["image_id"]] = {
                "path": row["path"],
                "height": int(row["height"] or 0),
                "width": int(row["width"] or 0),
            }
    return idx


def cmd_discover():
    counts = Counter()
    for item in iter_listings():
        pt = norm_product_type(item.get("product_type"))
        if pt:
            counts[pt] += 1
    with open("product_type_counts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_type", "listing_count"])
        for pt, c in counts.most_common():
            w.writerow([pt, c])
    print(f"Found {len(counts)} distinct product types "
          f"-> product_type_counts.csv")
    print("Top 25:")
    for pt, c in counts.most_common(25):
        print(f"  {pt:<40} {c}")


def cmd_sample():
    random.seed(SEED)
    img_idx = load_image_index()
    type_to_cat = {t: cat for cat, types in CATEGORY_MAP.items() for t in types}

    candidates = defaultdict(list)   # category -> list of (item_id, pt, image_id)
    for item in iter_listings():
        pt = norm_product_type(item.get("product_type"))
        cat = type_to_cat.get(pt)
        if not cat:
            continue
        mid = item.get("main_image_id")
        if not mid or mid not in img_idx:
            continue
        meta = img_idx[mid]
        if max(meta["height"], meta["width"]) < MIN_DIM:
            continue  # original too small for reliable IQA metrics
        candidates[cat].append((item.get("item_id", ""), pt, mid))

    os.makedirs(REVIEW_DIR, exist_ok=True)
    rows = []
    for cat in CATEGORY_MAP:
        pool = candidates.get(cat, [])
        picks = random.sample(pool, min(PER_CATEGORY, len(pool)))
        outdir = os.path.join(REVIEW_DIR, cat)
        os.makedirs(outdir, exist_ok=True)
        copied = 0
        for item_id, pt, image_id in picks:
            meta = img_idx[image_id]
            src = os.path.join(SMALL_DIR, meta["path"])
            if not os.path.exists(src):
                continue
            ext = os.path.splitext(meta["path"])[1]
            dst = os.path.join(outdir, f"{image_id}{ext}")
            shutil.copyfile(src, dst)
            copied += 1
            rows.append({
                "filename": f"{image_id}{ext}",
                "category": cat,
                "abo_item_id": item_id,
                "abo_product_type": pt,
                "abo_image_id": image_id,
                "abo_path": meta["path"],
                "orig_height": meta["height"],
                "orig_width": meta["width"],
                "source": "ABO (CC BY 4.0, credit Amazon.com)",
                "role": "good",
            })
        print(f"{cat:<22} candidates={len(pool):>6}  copied={copied}")

    with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else
                           ["filename"])
        w.writeheader()
        w.writerows(rows)
    print(f"\nReview folders in ./{REVIEW_DIR}/ — DELETE any image you don't "
          f"want, then run --fetch-originals.\nManifest: {MANIFEST}")


def cmd_fetch_originals():
    import requests
    # survivors = files still present in review folders
    with open(MANIFEST, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    kept = []
    for r in rows:
        if os.path.exists(os.path.join(REVIEW_DIR, r["category"], r["filename"])):
            kept.append(r)
    print(f"{len(kept)} of {len(rows)} images kept after review.")

    for r in kept:
        outdir = os.path.join(FINAL_DIR, r["category"])
        os.makedirs(outdir, exist_ok=True)
        dst = os.path.join(outdir, r["filename"])
        if os.path.exists(dst):
            continue
        ext = os.path.splitext(r["abo_path"])[1].lstrip(".")
        url = f"https://m.media-amazon.com/images/I/{r['abo_image_id']}.{ext}"
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            with open(dst, "wb") as fh:
                fh.write(resp.content)
            print(f"ok   {r['category']}/{r['filename']}")
        except Exception as e:
            # fallback: keep the small version and flag it in the manifest
            print(f"FAIL {r['filename']} ({e}) — falling back to small copy")
            shutil.copyfile(
                os.path.join(REVIEW_DIR, r["category"], r["filename"]), dst)
            r["role"] = "good (small-res fallback — consider replacing)"

    # write the final manifest for the dissertation appendix
    final_manifest = os.path.join(FINAL_DIR, "dataset_manifest_final.csv")
    with open(final_manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(kept[0].keys()))
        w.writeheader()
        w.writerows(kept)
    print(f"\nDone. Final images in ./{FINAL_DIR}/, manifest: {final_manifest}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--discover", action="store_true")
    g.add_argument("--sample", action="store_true")
    g.add_argument("--fetch-originals", action="store_true")
    args = ap.parse_args()
    if args.discover:
        cmd_discover()
    elif args.sample:
        cmd_sample()
    else:
        cmd_fetch_originals()
