# O1 criterion detection - calibration

Images: 52 (29 good, 23 with one known fault). Thresholds: specification v1.3.

| Criterion | Pass threshold | Detects its fault | False alarms on good images | AUC |
|---|---|---|---|---|
| T1 Sharpness | 0.2 | 2/4 (50%, 95% CI 15-85%) | 2/29 (7%, 95% CI 2-22%) | 0.888 |
| T2 Exposure | 0.6 | 2/8 (25%, 95% CI 7-59%) | 6/29 (21%, 95% CI 10-38%) | 0.491 |
| T3 Background | 0.55 | 4/4 (100%, 95% CI 51-100%) | 5/29 (17%, 95% CI 8-35%) | 0.974 |
| T4 BRISQUE | 0.6 | no constructed fault | 24/29 (83%, 95% CI 65-92%) | - |
| T5 PIQE | 0.55 | no constructed fault | 18/29 (62%, 95% CI 44-77%) | - |
| T6 Colour cast | 0.6 | no constructed fault | 1/29 (3%, 95% CI 1-17%) | - |

Paired within product (fault vs the same product's clean capture). Descriptive: with 4 pairs the smallest possible p is 0.0625.

| Fault | Criterion | Pairs | Score lower than clean | Below threshold | Clean passed, fault failed | Median change | Exact sign test p (one-sided) |
|---|---|---|---|---|---|---|---|
| BLUR | T1 Sharpness | 4 | 4/4 | 2/4 | 1/4 | -0.203 | 0.0625 |
| DARK | T2 Exposure | 4 | 3/4 | 2/4 | 2/4 | -0.189 | 0.125 |
| BRIGHT | T2 Exposure | 4 | 2/4 | 0/4 | 0/4 | +0.009 | 0.6875 |
| CLUTTER | T3 Background | 4 | 3/4 | 4/4 | 0/4 | -0.046 | 0.125 |

Framework verdict (image passes = FQS >= 0.55 and a role):

| | Rejected | Passed |
|---|---|---|
| Degraded | 1 | 0 |
| Good | 0 | 0 |

Sensitivity 1.0, specificity nan, balanced accuracy nan, MCC nan.
