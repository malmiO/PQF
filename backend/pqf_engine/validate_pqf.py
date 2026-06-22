"""
PQF Validation — Cohen's Kappa and Threshold Optimisation
===========================================================

    "Cohen's kappa (TQS vs expert) >= 0.75  -> Substantial agreement,
     PQF thresholds are validated."
    "Overall accuracy >= 80%"
    "If target not reached -> revise thresholds, re-run, repeat."

INPUTS
  tqs_results.csv      (produced by dataset_runner.py)
  expert_ratings.csv   (filled in from the expert rating form — must
                        contain columns: filepath, expert_pass [0 or 1])

WHAT THIS SCRIPT DOES
  1. Merges the two CSVs on filepath.
  2. Reports Cohen's kappa + accuracy at the PQF spec's current hard-reject
     threshold (TQS >= 0.40 -> pipeline says "pass").
  3. Runs a grid search over candidate TQS thresholds (0.20-0.60) and
     reports the threshold that maximises kappa.
  4. Lists every image where the pipeline and the expert DISAGREE, along
     with which individual criteria failed — this is the diagnostic list
     used to decide whether to adjust a specific criterion's threshold
     rather than just the overall TQS cutoff.
  5. Prints a clear VALIDATED / NOT YET VALIDATED verdict.

WHY Cohen's kappa instead of plain accuracy:
Accuracy alone can be misleading on an imbalanced dataset (e.g. if 90% of
images are "good", a pipeline that always says "pass" gets 90% accuracy
while being useless). Cohen's kappa corrects for the agreement that would
be expected by chance, which is the standard metric for this type of
human-vs-automated-system agreement study and is explicitly required by
the PQF Specification and the dissertation methodology.
"""

import sys
import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, accuracy_score, confusion_matrix


TARGET_KAPPA = 0.75
TARGET_ACCURACY = 0.80
CURRENT_TQS_THRESHOLD = 0.40
GRID_RANGE = np.arange(0.20, 0.62, 0.02)


def load_and_merge(tqs_csv: str, expert_csv: str) -> pd.DataFrame:
    tqs_df = pd.read_csv(tqs_csv)
    expert_df = pd.read_csv(expert_csv)

    merged = tqs_df.merge(expert_df, on="filepath", how="inner")

    missing = len(tqs_df) - len(merged)
    if missing > 0:
        print(f"WARNING: {missing} images in {tqs_csv} have no matching "
              f"row in {expert_csv} (expert rating missing) and were dropped.")

    return merged


def kappa_at_threshold(df: pd.DataFrame, threshold: float) -> dict:
    pipeline_pass = (df["tqs"] >= threshold).astype(int)
    expert_pass = df["expert_pass"].astype(int)

    kappa = cohen_kappa_score(expert_pass, pipeline_pass)
    accuracy = accuracy_score(expert_pass, pipeline_pass)
    cm = confusion_matrix(expert_pass, pipeline_pass, labels=[0, 1])

    return {
        "threshold": round(threshold, 2),
        "kappa": round(kappa, 4),
        "accuracy": round(accuracy, 4),
        "confusion_matrix": cm.tolist(),  # rows=expert[fail,pass], cols=pipeline[fail,pass]
    }


def grid_search(df: pd.DataFrame, thresholds=GRID_RANGE) -> pd.DataFrame:
    rows = [kappa_at_threshold(df, t) for t in thresholds]
    out = pd.DataFrame(rows)
    return out.drop(columns=["confusion_matrix"])


def disagreement_report(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    pipeline_pass = (df["tqs"] >= threshold).astype(int)
    expert_pass = df["expert_pass"].astype(int)
    disagree = df[pipeline_pass != expert_pass].copy()
    disagree["pipeline_pass"] = pipeline_pass[pipeline_pass != expert_pass]

    cols = ["filepath", "tqs", "pipeline_pass", "expert_pass", "failed_criteria"]
    return disagree[cols].sort_values("tqs")


def print_confusion(cm, title):
    print(f"\n  {title}")
    print(f"pipeline=FAIL   pipeline=PASS")
    print(f"  expert=FAIL     {cm[0][0]:>13}   {cm[0][1]:>13}")
    print(f"  expert=PASS     {cm[1][0]:>13}   {cm[1][1]:>13}")


def main(tqs_csv: str, expert_csv: str):
    df = load_and_merge(tqs_csv, expert_csv)
    n = len(df)
    print(f"Loaded {n} images with both TQS scores and expert ratings.\n")

    if n == 0:
        print("No matched rows — check that the 'filepath' columns in both "
              "CSVs use the same values.")
        return

    # ── Step 1: current spec threshold ─────────────────────────────────
    current = kappa_at_threshold(df, CURRENT_TQS_THRESHOLD)
    print(f"=== Current PQF threshold (TQS >= {CURRENT_TQS_THRESHOLD}) ===")
    print(f"  Cohen's kappa : {current['kappa']:.4f}")
    print(f"  Accuracy      : {current['accuracy']:.4f}")
    print_confusion(current["confusion_matrix"], "Confusion matrix")

    # ── Step 2: grid search ─────────────────────────────────────────────
    grid = grid_search(df)
    best = grid.loc[grid["kappa"].idxmax()]
    print(f"\n=== Threshold grid search (0.20 - 0.60) ===")
    print(grid.to_string(index=False))
    print(f"\n  Best threshold : TQS >= {best['threshold']}")
    print(f"  Best kappa     : {best['kappa']:.4f}")
    print(f"  Best accuracy  : {best['accuracy']:.4f}")

    # ── Step 3: disagreements at best threshold ─────────────────────────
    disagreements = disagreement_report(df, best["threshold"])
    print(f"\n=== Disagreements at best threshold ({len(disagreements)} of {n}) ===")
    if len(disagreements) > 0:
        print(disagreements.to_string(index=False))
        print("\n  Tip: if many disagreements share the same entry in "
              "'failed_criteria', that specific criterion's threshold "
              "(Section 2 of the PQF Specification) may need adjustment "
              "rather than the overall TQS cutoff.")
    else:
        print("  None — perfect agreement at this threshold.")

    # ── Step 4: verdict ───────────────────────────────────────────────
    print("\n=== Validation verdict (PQF Specification Section 6.2) ===")
    if best["kappa"] >= TARGET_KAPPA and best["accuracy"] >= TARGET_ACCURACY:
        print(f"  PQF VALIDATED — kappa {best['kappa']:.3f} >= {TARGET_KAPPA} "
              f"and accuracy {best['accuracy']:.3f} >= {TARGET_ACCURACY}")
        print(f"  -> Update PQF Specification v1.1: TQS hard-reject "
              f"threshold = {best['threshold']}")
    else:
        print(f"  PQF NOT YET VALIDATED — best kappa {best['kappa']:.3f} "
              f"(target {TARGET_KAPPA}), best accuracy {best['accuracy']:.3f} "
              f"(target {TARGET_ACCURACY})")
        print("  -> Review the disagreement list above. Consider revising "
              "individual criterion thresholds in Section 2 (e.g. the "
              "background purity ratio, or the BRISQUE/NIQE/PIQE cutoffs) "
              "and re-run dataset_runner.py + validate_pqf.py.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python validate_pqf.py <tqs_results.csv> <expert_ratings.csv>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
