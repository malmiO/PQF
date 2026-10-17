"""
settings.py  -  constants of the VIDEO layer (v1.1.0, 2026-10-06).

None of these touch the framework (criteria, weights, thresholds, roles, gate live
in backend/pqf/config.py and are unchanged). Everything here acts only on COPIES of
certified photos, after certification, while a video is rendered.
"""

# --- Step 1: brightness matching (normalize.py) -----------------------------
# Background lightness every shot is brought to: the main shot's background L*,
# but never below this. Design prior, not a research finding.
TARGET_BG_L_MIN = 92.0
# Largest mean CIEDE2000 colour difference allowed on the PRODUCT pixels between
# the original and the corrected copy (about "just noticeable" for side by side
# viewing). Design prior, not a research finding.
MAX_PRODUCT_DE00 = 2.0
# Lightness above which the L* gain rolls off smoothly instead of clipping.
# Design prior, not a research finding.
KNEE_L = 85.0
# Product pixels sampled for the colour difference check (speed only).
DE_SAMPLE = 40000

# --- Step 3: callout guard --------------------------------------------------
# Two feature points closer than this share of the frame diagonal are treated as
# the same place, and the scene falls back to captions. Design prior, not a
# research finding.
CALLOUT_MIN_SEPARATION = 0.08

# --- Step 4: measured checklist ---------------------------------------------
# "Product fills the frame": the product's height in main and angle frames, as a
# share of its layout zone. Design prior, not a research finding.
FILL_MIN = 0.50
# "Brightness consistent": largest allowed spread of background L* across shots.
# Design prior, not a research finding.
BG_L_RANGE_MAX = 4.0
# Frames decoded per second when the finished video is measured.
MEASURE_FPS = 4
# The product name must be on screen before this time (seconds).
HOOK_SECONDS = 2.0
