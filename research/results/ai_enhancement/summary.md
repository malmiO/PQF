# Phone-style enhancement vs PQF verdicts

60 photos; each operator at 3 strengths. 'Masked' = a criterion that FAILED on the original PASSES after enhancement; 'Broken' = the reverse. Product colour change is CIEDE2000 delta E in the product region (above 2.3 is perceptible).

| Operator | Level | Group | n | T1 masked / failing | T1 mean change | T2 masked | T6 mean change | Product colour change, median dE | Share dE > 2.3 |
|---|---|---|---|---|---|---|---|---|---|
| Detail sharpening (unsharp mask) | 1 | all | 60 | 7 / 11 | +0.147 | 0 | -0.005 | 1.72 | 13% |
| Detail sharpening (unsharp mask) | 2 | all | 60 | 9 / 11 | +0.233 | 0 | -0.006 | 3.21 | 70% |
| Detail sharpening (unsharp mask) | 3 | all | 60 | 11 / 11 | +0.296 | 0 | -0.015 | 6.08 | 92% |
| Noise reduction / skin smoothing (bilateral) | 1 | all | 60 | 0 / 11 | +0.009 | 0 | +0.000 | 1.07 | 0% |
| Noise reduction / skin smoothing (bilateral) | 2 | all | 60 | 0 / 11 | -0.015 | 0 | +0.000 | 1.62 | 5% |
| Noise reduction / skin smoothing (bilateral) | 3 | all | 60 | 0 / 11 | -0.128 | 0 | +0.000 | 2.25 | 48% |
| Saturation boost ('vivid' / scene optimiser) | 1 | all | 60 | 0 / 11 | -0.003 | 0 | -0.007 | 1.38 | 5% |
| Saturation boost ('vivid' / scene optimiser) | 2 | all | 60 | 0 / 11 | -0.007 | 0 | -0.008 | 2.49 | 58% |
| Saturation boost ('vivid' / scene optimiser) | 3 | all | 60 | 0 / 11 | -0.011 | 0 | -0.034 | 3.95 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 1 | all | 60 | 8 / 11 | +0.109 | 0 | -0.003 | 6.6 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 2 | all | 60 | 9 / 11 | +0.130 | 0 | -0.004 | 8.99 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 3 | all | 60 | 11 / 11 | +0.146 | 0 | -0.004 | 11.99 | 100% |
| Auto brightening (gamma) | 1 | all | 60 | 0 / 11 | -0.022 | 0 | -0.028 | 2.33 | 55% |
| Auto brightening (gamma) | 2 | all | 60 | 0 / 11 | -0.053 | 0 | -0.069 | 4.94 | 100% |
| Auto brightening (gamma) | 3 | all | 60 | 0 / 11 | -0.123 | 0 | -0.169 | 9.05 | 100% |
| Scene white-balance shift (warmer) | 1 | all | 60 | 0 / 11 | -0.000 | 0 | -0.090 | 3.11 | 95% |
| Scene white-balance shift (warmer) | 2 | all | 60 | 0 / 11 | -0.001 | 0 | +0.041 | 6.01 | 100% |
| Scene white-balance shift (warmer) | 3 | all | 60 | 0 / 11 | -0.002 | 0 | +0.057 | 9.31 | 100% |
| Upscaling + sharpening (super-resolution-like) | 1 | all | 60 | 3 / 11 | +0.022 | 0 | -0.005 | 2.55 | 62% |
| Upscaling + sharpening (super-resolution-like) | 2 | all | 60 | 1 / 11 | -0.185 | 0 | -0.000 | 2.65 | 62% |
| Upscaling + sharpening (super-resolution-like) | 3 | all | 60 | 0 / 11 | -0.535 | 0 | +0.000 | 2.84 | 63% |
