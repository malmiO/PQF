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
#
# v1.4.0 (2026-10-11): T4 EXCLUDED. This is the one logged exception to "no existing
# config value changes" (decisions.md 2026-10-11). The pre-registered condition
# (decisions.md 2026-10-08) was met on the pooled calibration set (n = 125): the 10th
# percentile of T4 is 0.0 (< 0.10), and synthetic noise RAISES T4 at every level
# (median change +0.585 / +0.515 / +0.447; 0/75 noisy images score lower). T4 is still
# computed and returned for reporting; it carries no weight and gives no feedback.
# The weights are the previous ones without T4, divided by 0.82 and rounded so that they
# sum to 1.00 and keep their order:
#   T1 0.22 -> 0.27, T2 0.18 -> 0.22, T3 0.18 -> 0.22, T4 0.18 -> 0.00,
#   T5 0.14 -> 0.17, T6 0.10 -> 0.12.
# ---------------------------------------------------------------------------
TQS_WEIGHTS = {
    "sharpness":  0.27,   # T1
    "exposure":   0.22,   # T2
    "background": 0.22,   # T3
    "brisque":    0.00,   # T4  (excluded in v1.4.0: failed construct validity in this domain)
    "piqe":       0.17,   # T5
    "colorcast":  0.12,   # T6  (added v1.2, 2026-08-13)
}
assert abs(sum(TQS_WEIGHTS.values()) - 1.0) < 1e-9, "TQS weights must sum to 1.00"

TQS_HARD_REJECT = 0.40

# Per-criterion pass thresholds (spec v1.3 s3; T4/T5 calibrated by the pre-registered rule,
# decisions.md 2026-10-08 and 2026-10-11: P10 of the normalised score over the pooled good
# calibration images, ABO calibration split + ABO extension, n = 125, rounded down to 2 dp).
# These replace the blanket "score < 0.40" cut for technical feedback. Nothing in TQS, SQS,
# FQS, the hard reject, roles, the gate or the selection depends on them.
T4_PASS_THRESHOLD = 0.0    # T4 excluded: no feedback is ever given for it (P10 = 0.0)
T5_PASS_THRESHOLD = 0.33   # P10 = 0.3349, bootstrap 95% CI [0.306, 0.368], raw PIQE <= 67
TQS_PASS_THRESHOLDS = {"sharpness": 0.20, "exposure": 0.60, "background": 0.55,
                       "brisque": T4_PASS_THRESHOLD, "piqe": T5_PASS_THRESHOLD,
                       "colorcast": 0.60}
assert set(TQS_PASS_THRESHOLDS) == set(TQS_WEIGHTS), "every technical criterion needs a pass threshold"

# ---------------------------------------------------------------------------
# Per-criterion parameters
# CALIBRATED_* are placeholders until Phase B calibration on the 52-image
# calibration split (data/splits/split_v1.csv). Do not tune on holdout.
# ---------------------------------------------------------------------------

# T1 — Sharpness (Laplacian variance). Resolution-dependent; only meaningful
# at WORKING_LONGEST_SIDE. sharpness_norm = clip(var / S_MAX, 0, 1).
CALIBRATED_SHARPNESS_SMAX = 1134.6   # placeholder → set in Phase B

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
# ---------------------------------------------------------------------------
# 2026-10-10: pinned for evaluation v1.4.0. The alias "gemini-flash-lite-latest" resolved
# to gemini-3.5-flash-lite on tools/model_check.py (callable). The alias can move to a
# different model during the study, which would change semantic scores with no code change.
GEMINI_MODEL = "gemini-3.5-flash-lite"
# The whole evaluation runs on the free Gemini tier (decided 2026-10; a limitation, disclosed).
GEMINI_TIER = "free"
GEMINI_TEMPERATURE = 0.0
PROMPT_VERSION = "pqf-sem-v1"

# --- Product-region localisation (added when T1/T2/T5 moved to product region) ---
# Catalogue composition means the product is the non-near-white area. These
# guard values keep the segmentation sane on unusual images.
PRODUCT_MIN_FRACTION = 0.02        # below this, fall back to the central region
PRODUCT_MAX_FRACTION = 0.90        # above this, segmentation failed -> central region
PRODUCT_BG_DELTA_MIN = 22          # min colour difference from the estimated background
PRODUCT_BG_DELTA_K = 4.0           # or 4 x the background's own unevenness, if larger
PRODUCT_BG_DELTA_MAX = 40          # cap, so an uneven border cannot swallow the product
PRODUCT_BG_MIN_MATCH = 0.60        # share of border that must match the estimate, else fall back
PRODUCT_FALLBACK_FRACTION = 0.50   # central box side fraction used as fallback
PRODUCT_CROP_MARGIN_PX = 12        # margin around the product bounding box
PIQE_MIN_CROP_PX = 64              # below this the crop is too small for PIQE
