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

Paired within product (fault vs the same product's clean capture). Descriptive: with 4 pairs the smallest possible p is 0.0625.

| Fault | Criterion | Pairs | Score lower than clean | Below threshold | Clean passed, fault failed | Median change | Exact sign test p (one-sided) |
|---|---|---|---|---|---|---|---|
| BLUR | T1 Sharpness | 4 | 4/4 | 2/4 | 1/4 | -0.203 | 0.0625 |
| DARK | T2 Exposure | 4 | 3/4 | 2/4 | 2/4 | -0.189 | 0.125 |
| BRIGHT | T2 Exposure | 4 | 2/4 | 0/4 | 0/4 | +0.009 | 0.6875 |
| CLUTTER | T3 Background | 4 | 3/4 | 4/4 | 0/4 | -0.046 | 0.125 |

Researcher clean captures (not in the good group): below threshold: T1 1/4, T3 4/4, T6 1/4; framework passed 0/0.

## Controlled synthetic faults (each against its own clean ABO original)

| Fault | Level | Criterion | Flagged below threshold | Clean passed, fault failed | Score lower | Median change | Sign test p | Framework rejected |
|---|---|---|---|---|---|---|---|---|
| BLUR | 1 | T1 Sharpness | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.966 | 0.0 | - |
| BLUR | 2 | T1 Sharpness | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.994 | 0.0 | - |
| BLUR | 3 | T1 Sharpness | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.998 | 0.0 | - |
| BRIGHT | 1 | T2 Exposure | 9/25 (36%, 95% CI 20-55%) | 7/25 | 11/25 | +0.000 | 0.411901 | - |
| BRIGHT | 2 | T2 Exposure | 11/25 (44%, 95% CI 27-63%) | 9/25 | 12/25 | +0.000 | 0.331812 | - |
| BRIGHT | 3 | T2 Exposure | 10/25 (40%, 95% CI 23-59%) | 9/25 | 13/25 | -0.032 | 0.261734 | - |
| CAST | 1 | T6 Colour cast | 25/25 (100%, 95% CI 87-100%) | 25/25 | 25/25 | -0.998 | 0.0 | - |
| CAST | 2 | T6 Colour cast | 25/25 (100%, 95% CI 87-100%) | 25/25 | 25/25 | -0.998 | 0.0 | - |
| CAST | 3 | T6 Colour cast | 0/25 (0%, 95% CI 0-13%) | 0/25 | 0/25 | +0.002 | 1.0 | - |
| CLUTTER | 1 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.910 | 0.0 | - |
| CLUTTER | 2 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.910 | 0.0 | - |
| CLUTTER | 3 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.910 | 0.0 | - |
| DARK | 1 | T2 Exposure | 14/25 (56%, 95% CI 37-73%) | 9/25 | 20/25 | -0.363 | 0.002039 | - |
| DARK | 2 | T2 Exposure | 24/25 (96%, 95% CI 80-99%) | 19/25 | 24/25 | -0.593 | 1e-06 | - |
| DARK | 3 | T2 Exposure | 25/25 (100%, 95% CI 87-100%) | 19/25 | 25/25 | -0.819 | 0.0 | - |
| GREYBG | 1 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.909 | 0.0 | - |
| GREYBG | 2 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.910 | 0.0 | - |
| GREYBG | 3 | T3 Background | 25/25 (100%, 95% CI 87-100%) | 24/25 | 25/25 | -0.910 | 0.0 | - |
| JPEG | 1 | T5 PIQE | 21/25 (84%, 95% CI 65-94%) | 3/25 | 22/25 | -0.030 | 7.8e-05 | - |
| JPEG | 2 | T5 PIQE | 23/25 (92%, 95% CI 75-98%) | 5/25 | 22/25 | -0.068 | 7.8e-05 | - |
| JPEG | 3 | T5 PIQE | 25/25 (100%, 95% CI 87-100%) | 7/25 | 25/25 | -0.127 | 0.0 | - |
| NOISE | 1 | T4 BRISQUE | 0/25 (0%, 95% CI 0-13%) | 0/25 | 0/25 | +0.585 | 1.0 | - |
| NOISE | 2 | T4 BRISQUE | 1/25 (4%, 95% CI 1-20%) | 0/25 | 0/25 | +0.515 | 1.0 | - |
| NOISE | 3 | T4 BRISQUE | 5/25 (20%, 95% CI 9-39%) | 0/25 | 0/25 | +0.447 | 1.0 | - |
| OFFCENTRE | 1 | S1 Centring | not scored | | | | | |
| OFFCENTRE | 2 | S1 Centring | not scored | | | | | |
| OFFCENTRE | 3 | S1 Centring | not scored | | | | | |
