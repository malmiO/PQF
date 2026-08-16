"""
abo_rebuild.py — Rebuild dataset_manifest.csv from the ACTUAL contents of
dataset_review/, whatever folder names you used, then you can fetch originals.

Run from the same folder as abo_select.py:
    python abo_rebuild.py
Then:
    python abo_select.py --fetch-originals
"""

import csv, glob, gzip, json, os

# same paths you set in abo_select.py — edit if yours differ
IMAGES_CSV = "abo-images-small/images/metadata/images.csv.gz"
LISTING_GLOB = "abo-listings/listings/metadata/listings_*.json.gz"
REVIEW_DIR = "dataset_review"
MANIFEST = "dataset_manifest.csv"


def norm_product_type(raw):
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


# 1. image_id -> path/size lookup
img_idx = {}
with gzip.open(IMAGES_CSV, "rt", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        img_idx[row["image_id"]] = {
            "path": row["path"],
            "height": int(row["height"] or 0),
            "width": int(row["width"] or 0),
        }
print(f"Loaded {len(img_idx)} image records.")

# 2. image_id -> (item_id, product_type) provenance lookup (one pass)
prov = {}
for fn in sorted(glob.glob(LISTING_GLOB)):
    with gzip.open(fn, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            mid = item.get("main_image_id")
            if mid:
                prov[mid] = (item.get("item_id", ""),
                             norm_product_type(item.get("product_type")))
            for oid in item.get("other_image_id", []) or []:
                prov.setdefault(oid, (item.get("item_id", ""),
                                      norm_product_type(item.get("product_type"))))
print(f"Loaded provenance for {len(prov)} image ids.")

# 3. Walk dataset_review: every file in every subfolder becomes a manifest row.
rows, unknown = [], []
for cat in sorted(os.listdir(REVIEW_DIR)):
    catdir = os.path.join(REVIEW_DIR, cat)
    if not os.path.isdir(catdir):
        continue
    for fname in sorted(os.listdir(catdir)):
        image_id, ext = os.path.splitext(fname)
        meta = img_idx.get(image_id)
        if meta is None:
            unknown.append(os.path.join(cat, fname))
            continue
        item_id, ptype = prov.get(image_id, ("", ""))
        rows.append({
            "filename": fname,
            "category": cat,                # folder name = category, as-is
            "abo_item_id": item_id,
            "abo_product_type": ptype,
            "abo_image_id": image_id,
            "abo_path": meta["path"],
            "orig_height": meta["height"],
            "orig_width": meta["width"],
            "source": "ABO (CC BY 4.0, credit Amazon.com)",
            "role": "good",
        })

with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"\nRebuilt {MANIFEST} with {len(rows)} rows from these folders:")
for cat in sorted({r['category'] for r in rows}):
    n = sum(1 for r in rows if r["category"] == cat)
    print(f"  {cat:<25} {n}")
if unknown:
    print(f"\nWARNING — {len(unknown)} files not found in ABO index "
          f"(renamed files or non-ABO images?):")
    for u in unknown[:10]:
        print(f"  {u}")
    print("These were skipped. Non-ABO images belong in your degraded/"
          "own-capture set with their own manifest, not this one.")
print("\nNow run:  python abo_select.py --fetch-originals")
