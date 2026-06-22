"""
PQF Dataset Runner
==================
Walks the dataset folder structure described in the collection plan:

    pqf_dataset/
      food/
        f01_chips/   f01_01.jpg ... f01_20.jpg
        f02_sauce/   ...
      fashion/
        a01_tshirt/  a01_01.jpg ... a01_20.jpg
        ...

Runs the TQS engine (Section 2, PQF Spec) on every image and writes a single
CSV with one row per image containing:

    filepath, category, product_id, shot_number, expected_pass (1-10/11-20),
    tqs, pass, sharpness_raw, exposure_raw, background_raw,
    brisque_raw, niqe_raw, piqe_raw, failed_criteria

This CSV is the input to validate_pqf.py, which merges it with the expert
ratings collected via the Google Form and runs the Cohen's kappa / MCDM
grid-search experiments described in Section 4 and 6 of the PQF Spec.

WHY a separate "expected_pass" column derived from the shot number:
This is NOT used as ground truth (the expert rating is ground truth). It is
a quick sanity-check column so that, immediately after a shoot, you can spot
obvious data-collection mistakes (e.g. a "flawed" shot that the engine still
scores as a clear pass, suggesting the flaw wasn't strong enough and the shot
should be retaken) BEFORE sending 200 images to the expert for rating.
"""

import csv
import sys
from pathlib import Path

from tqs_engine import compute_tqs, PerceptualScorer


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


def discover_images(dataset_root: Path):
    """
    Expects:  dataset_root/<category>/<product_id>/<product_id>_<NN>.<ext>
    Returns a list of dicts with parsed metadata for each image found.
    """
    items = []
    for category_dir in sorted(dataset_root.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name  # "food" or "fashion"

        for product_dir in sorted(category_dir.iterdir()):
            if not product_dir.is_dir():
                continue
            product_id = product_dir.name  # e.g. "f01_chips"

            for img_path in sorted(product_dir.iterdir()):
                if img_path.suffix.lower() not in IMAGE_EXTENSIONS:
                    continue

                # filename pattern: <prefix>_<NN>.<ext>  -> shot number = NN
                stem = img_path.stem
                shot_number = None
                if "_" in stem:
                    tail = stem.rsplit("_", 1)[-1]
                    if tail.isdigit():
                        shot_number = int(tail)

                items.append({
                    "filepath": str(img_path),
                    "category": category,
                    "product_id": product_id,
                    "shot_number": shot_number,
                })
    return items


def run_dataset(dataset_root: str, output_csv: str, device: str = "cpu"):
    root = Path(dataset_root)
    images = discover_images(root)

    if not images:
        print(f"No images found under {dataset_root}. "
              f"Expected structure: <root>/<category>/<product_id>/<id>_<NN>.jpg")
        return

    print(f"Found {len(images)} images. Loading IQA models...")
    scorer = PerceptualScorer(device=device)

    fieldnames = [
        "filepath", "category", "product_id", "shot_number", "expected_pass",
        "tqs", "pass",
        "sharpness_raw", "sharpness_norm",
        "exposure_raw", "exposure_norm",
        "background_raw", "background_norm",
        "brisque_raw", "brisque_norm",
        "niqe_raw", "niqe_norm",
        "piqe_raw", "piqe_norm",
        "failed_criteria",
    ]

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, item in enumerate(images, 1):
            try:
                result = compute_tqs(item["filepath"], scorer)
            except Exception as e:
                print(f"  [{i}/{len(images)}] ERROR on {item['filepath']}: {e}")
                continue

            shot_no = item["shot_number"]
            # Shot list convention: shots 1-10 = good variations, 11-20 = flawed
            expected_pass = None
            if shot_no is not None:
                expected_pass = 1 if shot_no <= 10 else 0

            row = {
                "filepath": item["filepath"],
                "category": item["category"],
                "product_id": item["product_id"],
                "shot_number": shot_no,
                "expected_pass": expected_pass,
                "tqs": result["tqs"],
                "pass": int(result["pass"]),
                "failed_criteria": ";".join(result["failed_criteria"]),
            }
            for key in ["sharpness", "exposure", "background", "brisque", "niqe", "piqe"]:
                row[f"{key}_raw"] = result["scores"][key]["raw"]
                row[f"{key}_norm"] = result["scores"][key]["norm"]

            writer.writerow(row)

            if i % 10 == 0 or i == len(images):
                print(f"  [{i}/{len(images)}] {item['filepath']} -> "
                      f"TQS={result['tqs']:.3f}  pass={result['pass']}")

    print(f"\nDone. Results written to {output_csv}")
    print(f"Next step: rate these {len(images)} images blind using the "
          f"expert rating form, save as expert_ratings.csv, then run "
          f"validate_pqf.py")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python dataset_runner.py <dataset_root> [output_csv]")
        sys.exit(1)

    dataset_root = sys.argv[1]
    output_csv = sys.argv[2] if len(sys.argv) > 2 else "tqs_results.csv"
    run_dataset(dataset_root, output_csv)
