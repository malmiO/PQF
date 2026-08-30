"""
PQF configuration — SINGLE SOURCE OF TRUTH for all thresholds and weights.

Design rule: no threshold or weight is hard-coded anywhere else. Calibration
touches ONLY this file, and only using the calibration split.

STATUS: T0-T6 / TQS section CONFIRMED (spec v1.2, including T6 added 2026-08-13).
        Semantic / MCDM / gate section still STUB — do not use until filled
        from docs/PQF_Specification_v1.2.docx section on S1-S5 weights.
"""

# ---------------------------------------------------------------------------
# Pre-processing
# ---------------------------------------------------------------------------
WORKING_LONGEST_SIDE = 1024

# ---------------------------------------------------------------------------
# T0 — Platform compliance gate (binary, mandatory, pre-metric)
# ---------------------------------------------------------------------------
T0_MIN_RESOLUTION = (640, 640)
T0_ASPECT_MIN = 0.8
T0_ASPECT_MAX = 1.91

# ---------------------------------------------------------------------------
# Technical Quality Score (TQS) — six weighted criteria, sum = 1.00
# v1.1 had five (0.25/0.20/0.20/0.20/0.15); v1.2 adds T6 and rebalances,
# preserving rank order (T1 still highest, T5 still lowest of the originals).
# ---------------------------------------------------------------------------
TQS_WEIGHTS = {
    "sharpness":  0.22,   # T1
    "exposure":   0.18,   # T2
    "background": 0.18,   # T3
    "brisque":    0.18,   # T4
    "piqe":       0.14,   # T5
    "colorcast":  0.10,   # T6  (added v1.2, 2026-08-13)
}
assert abs(sum(TQS_WEIGHTS.values()) - 1.0) < 1e-9, "TQS weights must sum to 1.00"

TQS_HARD_REJECT = 0.40

# ---------------------------------------------------------------------------
# Per-criterion parameters
# CALIBRATED_* are placeholders until Phase B calibration on the 52-image
# calibration split (data/splits/split_v1.csv). Do not tune on holdout.
# ---------------------------------------------------------------------------

# T1 — Sharpness (Laplacian variance). Resolution-dependent; only meaningful
# at WORKING_LONGEST_SIDE. sharpness_norm = clip(var / S_MAX, 0, 1).
CALIBRATED_SHARPNESS_SMAX = 2057.0   # placeholder → set in Phase B

# T2 — Exposure (mean luminance in [0,255]). Penalise distance from ideal band.
T2_IDEAL_LOW = 100.0
T2_IDEAL_HIGH = 180.0
T2_TOLERANCE = 60.0

# T3 — Background purity (fraction of near-white border pixels).
T3_WHITE_THRESHOLD = 220
T3_BORDER_FRACTION = 0.10

# T4 — BRISQUE (0..100, lower better). brisque_norm = clip(1 - raw/MAX, 0, 1)
T4_BRISQUE_MAX = 100.0

# T5 — PIQE (0..100, lower better). piqe_norm = clip(1 - raw/MAX, 0, 1)
T5_PIQE_MAX = 100.0

# T6 — Colour-cast detection (v1.2). Grey-world in the T3 neutral region only.
# Detects CAST CONDITIONS, not colour accuracy (needs an in-frame reference
# card — future work; see decisions.md 2026-08-13).
CALIBRATED_COLORCAST_CMAX = 5.0     # placeholder → set in Phase B
T6_MIN_NEUTRAL_FRACTION = 0.05       # below this, T6 abstains → returns 1.0
T6_PASS_THRESHOLD = 0.60             # initial; final value from calibration

# ===========================================================================
# STUB BELOW — DO NOT USE UNTIL FILLED from PQF_Specification_v1.2.docx
# (semantic criteria weights, MCDM combination, gate/role thresholds)
# ===========================================================================

# Semantic Quality Score (SQS) — five criteria (S1-S5), judged by the evaluator.
# CONFIRMED against PQF Specification v1.3, Section 4.1 (2026-08-18).
# Criterion keys match the spec AND the evaluator prompt exactly — these keys are
# the JSON keys the model returns, so they must not drift from the spec.
SQS_WEIGHTS = {
    "subject_centering":       0.25,   # S1
    "feature_visibility":      0.25,   # S2
    "marketing_suitability":   0.25,   # S3
    "angle_value":             0.15,   # S4
    "lighting_style_quality":  0.10,   # S5
}
assert abs(sum(SQS_WEIGHTS.values()) - 1.0) < 1e-9, "SQS weights must sum to 1.00"

# Per-criterion semantic pass thresholds (spec v1.3, Section 4.2).
# S1-S3 require >= 0.60; S4-S5 require >= 0.50. Used by the role/gate logic.
SQS_PASS_THRESHOLDS = {
    "subject_centering":       0.60,   # S1
    "feature_visibility":      0.60,   # S2
    "marketing_suitability":   0.60,   # S3
    "angle_value":             0.50,   # S4
    "lighting_style_quality":  0.50,   # S5
}

# MCDM combination: FQS = alpha*TQS + beta*SQS
# CONFIRMED against spec v1.3, Section 5 (2026-08-18): alpha=0.40, beta=0.60.
FQS_ALPHA = 0.40   # technical weight
FQS_BETA = 0.60    # semantic weight
assert abs(FQS_ALPHA + FQS_BETA - 1.0) < 1e-9, "FQS alpha+beta must sum to 1.00"

# Overall accept threshold (spec v1.3, Section 5): an image passes the framework
# gate at FQS >= 0.55 (in addition to any per-criterion pass rules below).
FQS_PASS_THRESHOLD = 0.55

# Role classification (spec v1.3, Section 4.3). Roles are assigned in priority
# order; the first rule whose conditions are all met wins. Encoded as data so the
# gate/classifier reads the spec's rules rather than hard-coding them.
#   hero_shot   : FQS >= 0.75 AND subject_centering >= 0.70 AND marketing_suitability >= 0.70
#   angle_shot  : FQS >= 0.60 AND angle_value >= 0.60
#   detail_shot : FQS >= 0.60 AND feature_visibility >= 0.70
#   reject      : anything below the above (incl. FQS < FQS_PASS_THRESHOLD)
ROLE_RULES = {
    "hero_shot":   {"fqs_min": 0.75, "criteria_min": {"subject_centering": 0.70,
                                                        "marketing_suitability": 0.70}},
    "angle_shot":  {"fqs_min": 0.60, "criteria_min": {"angle_value": 0.60}},
    "detail_shot": {"fqs_min": 0.60, "criteria_min": {"feature_visibility": 0.70}},
}
ROLE_PRIORITY = ["hero_shot", "angle_shot", "detail_shot"]  # first match wins; else reject

# ---------------------------------------------------------------------------
# Semantic evaluator (Phase C)
GEMINI_MODEL = "gemini-flash-lite-latest"     # pinned; exact id set in client
GEMINI_TEMPERATURE = 0.0
PROMPT_VERSION = "pqf-sem-v1"
