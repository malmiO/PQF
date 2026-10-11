# T4 / T5 threshold calibration (pre-registered rule, 2026-10-08)

Good calibration images: 125 (ABO, ABO_extension). Rule: P10 of normalised score over good calibration images, rounded down to 2 decimals.

| Criterion | Spec threshold (false alarms) | P10 | Bootstrap 95% CI | Proposed threshold | Raw equivalent | Calibration false alarms | Synthetic faults below (L1/L2/L3) |
|---|---|---|---|---|---|---|---|
| T4 BRISQUE | 0.6 (114/125) | 0.0 | [0.0, 0.054] | **0.0** | raw <= 100.0 | 0/125 | 0/25 / 0/25 / 0/25 |
| T5 PIQE | 0.55 (90/125) | 0.3349 | [0.306, 0.368] | **0.33** | raw <= 67.0 | 11/125 | 8/25 / 11/25 / 18/25 |

Copy the two proposed thresholds into backend/pqf/config.py as T4_PASS_THRESHOLD and T5_PASS_THRESHOLD (logged exception, v1.4.0). Do not adjust them after seeing the synthetic row: it is reported, not used.
