# Phone-style enhancement vs PQF verdicts

58 photos; each operator at 3 strengths. 'Masked' = a criterion that FAILED on the original PASSES after enhancement; 'Broken' = the reverse. Product colour change is CIEDE2000 delta E in the product region (above 2.3 is perceptible).

| Operator | Level | Group | n | T1 masked / failing | T1 mean change | T2 masked | T6 mean change | Product colour change, median dE | Share dE > 2.3 |
|---|---|---|---|---|---|---|---|---|---|
| Detail sharpening (unsharp mask) | 1 | all | 58 | 1 / 10 | +0.108 | 0 | +0.004 | 1.85 | 31% |
| Detail sharpening (unsharp mask) | 1 | blurred | 4 | 0 / 2 | +0.104 | 0 | -0.002 | 0.65 | 0% |
| Detail sharpening (unsharp mask) | 2 | all | 58 | 6 / 10 | +0.161 | 0 | +0.001 | 3.41 | 71% |
| Detail sharpening (unsharp mask) | 2 | blurred | 4 | 0 / 2 | +0.219 | 0 | -0.004 | 1.09 | 0% |
| Detail sharpening (unsharp mask) | 3 | all | 58 | 9 / 10 | +0.208 | 0 | -0.004 | 5.95 | 91% |
| Detail sharpening (unsharp mask) | 3 | blurred | 4 | 1 / 2 | +0.300 | 0 | -0.115 | 2.14 | 50% |
| Noise reduction / skin smoothing (bilateral) | 1 | all | 58 | 0 / 10 | +0.004 | 0 | +0.001 | 1.07 | 0% |
| Noise reduction / skin smoothing (bilateral) | 1 | blurred | 4 | 0 / 2 | -0.014 | 0 | +0.003 | 0.68 | 0% |
| Noise reduction / skin smoothing (bilateral) | 2 | all | 58 | 0 / 10 | -0.003 | 0 | +0.001 | 1.68 | 12% |
| Noise reduction / skin smoothing (bilateral) | 2 | blurred | 4 | 0 / 2 | -0.053 | 0 | +0.004 | 0.84 | 0% |
| Noise reduction / skin smoothing (bilateral) | 3 | all | 58 | 0 / 10 | -0.031 | 0 | +0.000 | 2.26 | 45% |
| Noise reduction / skin smoothing (bilateral) | 3 | blurred | 4 | 0 / 2 | -0.109 | 0 | +0.004 | 1.03 | 0% |
| Saturation boost ('vivid' / scene optimiser) | 1 | all | 58 | 0 / 10 | -0.003 | 0 | -0.007 | 1.57 | 22% |
| Saturation boost ('vivid' / scene optimiser) | 1 | blurred | 4 | 0 / 2 | -0.007 | 0 | -0.020 | 1.22 | 0% |
| Saturation boost ('vivid' / scene optimiser) | 2 | all | 58 | 0 / 10 | -0.007 | 0 | -0.054 | 2.91 | 76% |
| Saturation boost ('vivid' / scene optimiser) | 2 | blurred | 4 | 0 / 2 | -0.006 | 0 | -0.023 | 2.23 | 50% |
| Saturation boost ('vivid' / scene optimiser) | 3 | all | 58 | 0 / 10 | -0.009 | 0 | -0.098 | 4.58 | 91% |
| Saturation boost ('vivid' / scene optimiser) | 3 | blurred | 4 | 0 / 2 | -0.019 | 0 | -0.031 | 3.57 | 75% |
| Local tone mapping (HDR-like, CLAHE) | 1 | all | 58 | 0 / 10 | +0.076 | 0 | +0.017 | 6.45 | 98% |
| Local tone mapping (HDR-like, CLAHE) | 1 | blurred | 4 | 0 / 2 | +0.091 | 0 | +0.010 | 4.21 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 2 | all | 58 | 3 / 10 | +0.099 | 0 | +0.017 | 8.44 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 2 | blurred | 4 | 0 / 2 | +0.145 | 0 | +0.007 | 6.25 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 3 | all | 58 | 6 / 10 | +0.123 | 0 | +0.018 | 10.96 | 100% |
| Local tone mapping (HDR-like, CLAHE) | 3 | blurred | 4 | 1 / 2 | +0.240 | 0 | +0.008 | 8.35 | 100% |
| Auto brightening (gamma) | 1 | all | 58 | 0 / 10 | -0.014 | 0 | -0.027 | 1.77 | 9% |
| Auto brightening (gamma) | 1 | blurred | 4 | 0 / 2 | -0.008 | 0 | -0.111 | 1.95 | 50% |
| Auto brightening (gamma) | 2 | all | 58 | 0 / 10 | -0.027 | 1 | -0.028 | 3.83 | 98% |
| Auto brightening (gamma) | 2 | blurred | 4 | 0 / 2 | +0.002 | 0 | -0.116 | 4.14 | 100% |
| Auto brightening (gamma) | 3 | all | 58 | 0 / 10 | -0.066 | 1 | +0.005 | 7.25 | 100% |
| Auto brightening (gamma) | 3 | blurred | 4 | 0 / 2 | -0.007 | 0 | -0.166 | 7.73 | 100% |
| Scene white-balance shift (warmer) | 1 | all | 58 | 0 / 10 | -0.001 | 0 | -0.309 | 2.71 | 98% |
| Scene white-balance shift (warmer) | 1 | blurred | 4 | 0 / 2 | -0.001 | 0 | -0.209 | 3.44 | 100% |
| Scene white-balance shift (warmer) | 2 | all | 58 | 0 / 10 | -0.002 | 0 | -0.586 | 5.23 | 100% |
| Scene white-balance shift (warmer) | 2 | blurred | 4 | 0 / 2 | -0.002 | 0 | +0.073 | 6.5 | 100% |
| Scene white-balance shift (warmer) | 3 | all | 58 | 0 / 10 | -0.005 | 0 | -0.500 | 8.21 | 100% |
| Scene white-balance shift (warmer) | 3 | blurred | 4 | 0 / 2 | -0.006 | 0 | +0.073 | 10.01 | 100% |
| Upscaling + sharpening (super-resolution-like) | 1 | all | 58 | 0 / 10 | +0.041 | 0 | +0.001 | 2.68 | 62% |
| Upscaling + sharpening (super-resolution-like) | 1 | blurred | 4 | 0 / 2 | -0.083 | 0 | -0.002 | 1.08 | 0% |
| Upscaling + sharpening (super-resolution-like) | 2 | all | 58 | 0 / 10 | -0.045 | 0 | +0.001 | 2.77 | 64% |
| Upscaling + sharpening (super-resolution-like) | 2 | blurred | 4 | 0 / 2 | -0.168 | 0 | -0.001 | 1.12 | 0% |
| Upscaling + sharpening (super-resolution-like) | 3 | all | 58 | 0 / 10 | -0.464 | 0 | +0.001 | 2.96 | 66% |
| Upscaling + sharpening (super-resolution-like) | 3 | blurred | 4 | 0 / 2 | -0.274 | 0 | +0.001 | 1.19 | 0% |
