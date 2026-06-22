"""
convert_form_responses.py
==========================
Converts the CSV exports from the Google Form response spreadsheets
into the single expert_ratings.csv file that validate_pqf.py expects.

INPUTS
  One CSV per product, downloaded from the Google Sheets response
  spreadsheet (File -> Download -> CSV).
  Place all of them in one folder, e.g. "form_responses/".

  Each CSV has columns like:
      Timestamp | f01_chips_01.jpg | f01_chips_02.jpg | ... | f01_chips_20.jpg

  Column header  = filename (set by generate_rating_forms.gs).
  Cell values    = "Pass" or "Fail" (the expert's answer).

  If the expert completed the form more than once, only the LAST
  response row is used (most recent = most considered).

OUTPUTS
  expert_ratings.csv with columns:
      filepath        e.g. pqf_dataset/food/f01_chips/f01_chips_01.jpg
      expert_pass     1 = Pass, 0 = Fail

WHY we take the LAST response row (not first, not majority):
  The expert is one person rating at one sitting. If they re-submitted,
  the later response is the considered revision. "Majority vote" would
  require multiple experts — if you have access to a second photography
  expert, extend this script by averaging their responses, which gives
  a much stronger validation result and is worth mentioning in your
  dissertation methodology.
"""

import sys
import glob
import pathlib
import pandas as pd


def infer_filepath(filename: str, dataset_root: str) -> str:
    """
    Given a bare filename like 'f01_chips_07.jpg', reconstruct the
    relative filepath expected by validate_pqf.py.

    Naming convention: <category_prefix><number>_<product_name>_<NN>.jpg
    Category prefixes: 'f' -> food, 'a' -> fashion

    The product folder name is everything before the last underscore-padded
    shot number, e.g. 'f01_chips_07.jpg' -> product = 'f01_chips'.
    """
    stem = pathlib.Path(filename).stem          # e.g. f01_chips_07
    parts = stem.rsplit("_", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None

    product_id = parts[0]                       # f01_chips
    prefix = product_id[0].lower()

    category_map = {"f": "food", "a": "fashion"}
    category = category_map.get(prefix, "unknown")

    return f"{dataset_root}/{category}/{product_id}/{filename}"


def convert_responses(responses_dir: str,
                      dataset_root: str = "pqf_dataset",
                      output_csv: str = "expert_ratings.csv"):

    csv_files = glob.glob(f"{responses_dir}/*.csv")
    if not csv_files:
        print(f"No CSV files found in {responses_dir}/")
        return

    all_rows = []
    skipped = 0

    for csv_path in sorted(csv_files):
        df = pd.read_csv(csv_path)

        # Drop the Timestamp column if present
        image_cols = [c for c in df.columns if c.lower() != "timestamp"]

        if df.empty:
            print(f"  SKIP {csv_path} — no responses yet")
            continue

        # Use only the last submitted response
        last_row = df[image_cols].iloc[-1]

        for filename, verdict in last_row.items():
            filepath = infer_filepath(str(filename), dataset_root)
            if filepath is None:
                skipped += 1
                continue

            verdict_str = str(verdict).strip().lower()
            if verdict_str == "pass":
                expert_pass = 1
            elif verdict_str == "fail":
                expert_pass = 0
            else:
                print(f"  WARNING: unexpected verdict '{verdict}' "
                      f"for {filename} — skipping")
                skipped += 1
                continue

            all_rows.append({
                "filepath": filepath,
                "expert_pass": expert_pass,
            })

        print(f"  Processed {csv_path}  ({len(image_cols)} images)")

    if not all_rows:
        print("No rows produced. Check the CSV column headers match "
              "the expected filename format (e.g. f01_chips_01.jpg).")
        return

    out_df = pd.DataFrame(all_rows)
    out_df = out_df.drop_duplicates(subset=["filepath"], keep="last")
    out_df = out_df.sort_values("filepath")
    out_df.to_csv(output_csv, index=False)

    n = len(out_df)
    n_pass = int(out_df["expert_pass"].sum())
    n_fail = n - n_pass
    print(f"\nDone. {n} images written to {output_csv}")
    print(f"  Expert pass: {n_pass} ({n_pass/n*100:.0f}%)")
    print(f"  Expert fail: {n_fail} ({n_fail/n*100:.0f}%)")
    if skipped:
        print(f"  Skipped {skipped} unrecognised entries")
    print(f"\nNext step:  python validate_pqf.py tqs_results.csv {output_csv}")


if __name__ == "__main__":
    responses_dir = sys.argv[1] if len(sys.argv) > 1 else "form_responses"
    dataset_root  = sys.argv[2] if len(sys.argv) > 2 else "pqf_dataset"
    output_csv    = sys.argv[3] if len(sys.argv) > 3 else "expert_ratings.csv"
    convert_responses(responses_dir, dataset_root, output_csv)
