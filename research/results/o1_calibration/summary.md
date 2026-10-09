# O1 criterion detection - calibration

Images: 52 (25 good catalogue images, 23 with one known fault, 4 researcher clean captures used only as pair anchors). Thresholds: specification v1.3.

| Criterion | Pass threshold | Detects its fault | False alarms on good images | AUC |
|---|---|---|---|---|
| T1 Sharpness | 0.2 | 2/4 (50%, 95% CI 15-85%) | 1/25 (4%, 95% CI 1-20%) | 0.91 |
| T2 Exposure | 0.6 | 2/8 (25%, 95% CI 7-59%) | 6/25 (24%, 95% CI 11-43%) | 0.485 |
| T3 Background | 0.55 | 4/4 (100%, 95% CI 51-100%) | 1/25 (4%, 95% CI 1-20%) | 1.0 |
| T4 BRISQUE | 0.6 | no constructed fault | 24/25 (96%, 95% CI 80-99%) | - |
| T5 PIQE | 0.55 | no constructed fault | 18/25 (72%, 95% CI 52-86%) | - |
| T6 Colour cast | 0.6 | no constructed fault | 0/25 (0%, 95% CI 0-13%) | - |
| S1 Centring | 0.6 | 4/4 (100%, 95% CI 51-100%) | 0/25 (0%, 95% CI 0-13%) | 1.0 |
| S2 Feature visibility | 0.6 | no constructed fault | 0/25 (0%, 95% CI 0-13%) | - |
| S3 Marketing suitability | 0.6 | no constructed fault | 0/25 (0%, 95% CI 0-13%) | - |
| S4 Angle value | 0.5 | 0/3 (0%, 95% CI 0-56%) | 0/25 (0%, 95% CI 0-13%) | 0.86 |
| S5 Lighting and style | 0.5 | no constructed fault | 0/25 (0%, 95% CI 0-13%) | - |

Paired within product (fault vs the same product's clean capture). Descriptive: with 4 pairs the smallest possible p is 0.0625.

| Fault | Criterion | Pairs | Score lower than clean | Below threshold | Clean passed, fault failed | Median change | Exact sign test p (one-sided) |
|---|---|---|---|---|---|---|---|
| BLUR | T1 Sharpness | 4 | 4/4 | 2/4 | 1/4 | -0.203 | 0.0625 |
| DARK | T2 Exposure | 4 | 3/4 | 2/4 | 2/4 | -0.189 | 0.125 |
| BRIGHT | T2 Exposure | 4 | 2/4 | 0/4 | 0/4 | +0.009 | 0.6875 |
| CLUTTER | T3 Background | 4 | 3/4 | 4/4 | 0/4 | -0.046 | 0.125 |
| OFFCENTRE | S1 Centring | 4 | 4/4 | 4/4 | 3/4 | -0.550 | 0.0625 |
| ANGLE | S4 Angle value | 3 | 0/3 | 0/3 | 0/3 | +0.200 | 1.0 |

Researcher clean captures (not in the good group): below threshold: T1 1/4, T3 4/4, T6 1/4, S1 1/4, S2 1/4, S3 1/4, S4 1/4, S5 1/4; framework passed 3/4.

Framework verdict (image passes = FQS >= 0.55 and a role):

| | Rejected | Passed |
|---|---|---|
| Degraded | 19 | 4 |
| Good | 0 | 25 |

Sensitivity 0.826, specificity 1.0, balanced accuracy 0.913, MCC 0.844.
