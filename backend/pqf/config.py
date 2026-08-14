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
CALIBRATED_SHARPNESS_SMAX = 1000.0   # placeholder → set in Phase B

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
CALIBRATED_COLORCAST_CMAX = 20.0     # placeholder → set in Phase B
T6_MIN_NEUTRAL_FRACTION = 0.05       # below this, T6 abstains → returns 1.0
T6_PASS_THRESHOLD = 0.60             # initial; final value from calibration

# ===========================================================================
# STUB BELOW — DO NOT USE UNTIL FILLED from PQF_Specification_v1.2.docx
# (semantic criteria weights, MCDM combination, gate/role thresholds)
# ===========================================================================

# Semantic Quality Score (SQS) — five criteria (S1-S5). Spec states weights
# (0.25 / 0.25 / 0.25 / 0.15 / 0.10) but NOT yet mapped to which criterion —
# confirm against the spec's semantic-criteria section before filling this in.
SQS_WEIGHTS = None  # TODO: {"composition": ?, "feature_visibility": ?, "professionalism": ?, "angle_informativeness": ?, "lighting_style": ?}

# MCDM combination: FQS = alpha*TQS + beta*SQS
# Spec states alpha=0.40, beta=0.60 — CONFIRM before use (do not assume).
FQS_ALPHA = None   # TODO: 0.40 per config stub — confirm against spec
FQS_BETA = None    # TODO: 0.60 per config stub — confirm against spec
FQS_PASS_THRESHOLD = None  # TODO: 0.55 per config stub — confirm against spec

# Role classification + quality gate — TODO, fill when Phase D is reached
FQS_REJECT_BELOW = None
FQS_HERO_ABOVE = None

# ---------------------------------------------------------------------------
# Semantic evaluator (Phase C)
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-flash"        # pinned; exact id set in client
GEMINI_TEMPERATURE = 0.0
PROMPT_VERSION = "pqf-sem-v1"
