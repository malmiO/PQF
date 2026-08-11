"""
narrow_categories.py — Reduce the ABO good-half to the chosen categories.

Run from the dataset/ root (the folder containing abo/).
Edit KEEP below if your two category folder names differ.

  python narrow_categories.py --dry-run   # show what would change, touch nothing
  python narrow_categories.py             # actually move unused cats to _archived/

Nothing is deleted permanently: unused category folders are MOVED to
abo/_archived_categories/ so you can restore them if you ever re-expand.
"""

import argparse, csv, os, shutil

ABO_DIR = "abo"
MANIFEST = os.path.join(ABO_DIR, "dataset_manifest_final.csv")
ARCHIVE = os.path.join(ABO_DIR, "_archived_categories")

# --- the two categories you are keeping ---
KEEP = {"fashion_accessories", "cosmetics_care"}


def main(dry):
    if not os.path.isdir(ABO_DIR):
        raise SystemExit("Run from the dataset/ root (abo/ not found).")

    # 1. category folders present
    cats = [d for d in os.listdir(ABO_DIR)
            if os.path.isdir(os.path.join(ABO_DIR, d)) and not d.startswith("_")]
    to_archive = [c for c in cats if c not in KEEP]
    to_keep = [c for c in cats if c in KEEP]

    print("Keeping :", ", ".join(sorted(to_keep)) or "(none!)")
    print("Archiving:", ", ".join(sorted(to_archive)) or "(none)")
    missing = KEEP - set(cats)
    if missing:
        print("WARNING — expected categories not found:", ", ".join(missing))

    # 2. move unused folders
    if not dry:
        os.makedirs(ARCHIVE, exist_ok=True)
    for c in to_archive:
        src = os.path.join(ABO_DIR, c)
        dst = os.path.join(ARCHIVE, c)
        print(f"  move {src} -> {dst}")
        if not dry:
            shutil.move(src, dst)

    # 3. rewrite manifest to only kept categories
    if os.path.exists(MANIFEST):
        with open(MANIFEST, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
            fields = rows[0].keys() if rows else []
        kept = [r for r in rows if r.get("category") in KEEP]
        print(f"\nmanifest: {len(rows)} rows -> {len(kept)} rows kept")
        by = {}
        for r in kept:
            by[r["category"]] = by.get(r["category"], 0) + 1
        for c, n in sorted(by.items()):
            print(f"  {c:<25}{n}")
        if not dry and rows:
            # back up then rewrite
            shutil.copyfile(MANIFEST, MANIFEST + ".bak")
            with open(MANIFEST, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(fields))
                w.writeheader()
                w.writerows(kept)
            print(f"  manifest rewritten (backup: {os.path.basename(MANIFEST)}.bak)")
    else:
        print("No ABO manifest found — skipping manifest step.")

    print("\nDry run — nothing changed." if dry else "\nDone.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    main(ap.parse_args().dry_run)
