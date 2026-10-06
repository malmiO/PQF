"""
Quality Gate (Phase D) — set-level coverage check (spec v1.3, Section 7).

After per-image decisions are made and the best set is selected, the gate checks
whether the SET as a whole is good enough to certify. If any condition fails, a
structured re-capture signal is returned telling the user what to fix.

Spec Section 7 conditions:
  1. >= 1 hero_shot with FQS >= 0.75                -> no_hero_shot
  2. >= 2 angle_shots with distinct angles          -> insufficient_angles
  3. >= 1 detail_shot with feature_visibility>=0.70 -> no_detail_shot
  4. all selected images FQS >= 0.55                -> low_overall_quality
  5. selected set size 4-6 images                   -> insufficient_coverage
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config

# Gate parameters (spec Section 7). Kept here as named constants; if the spec
# ever parameterises these, move them to config.
GATE_MIN_HERO_FQS = 0.75
GATE_MIN_ANGLES = 2
GATE_MIN_DETAILS = 1
GATE_MIN_HEROES = 1
GATE_DETAIL_FEATVIS_MIN = 0.70
GATE_SET_MIN = 4
GATE_SET_MAX = 6


@dataclass
class GateResult:
    certified: bool = False
    fail_reasons: list = field(default_factory=list)
    instruction: str = ""
    counts: dict = field(default_factory=dict)


# Human-readable corrective instruction per fail reason.
_INSTRUCTIONS = {
    "no_hero_shot": "Retake a strong front-facing hero shot (well-lit, centred, sharp).",
    "insufficient_angles": "Capture at least two additional shots from different angles.",
    "no_detail_shot": "Add a close-up detail shot showing texture, label, or key feature.",
    "low_overall_quality": "One or more selected images are below the quality bar — retake them.",
    "insufficient_coverage": f"Provide {GATE_SET_MIN}-{GATE_SET_MAX} good images in total.",
}


def _distinct_angles(angles: list, heroes: list) -> list:
    """Angle shots that show DISTINCT views (spec Section 7, condition 2).

    Implemented 2026-10-06: the condition always said "distinct angles", but only
    the number of angle shots was counted, so two copies of the same view passed.
    An angle counts if its view differs from the main shot and from every angle
    already counted (views.NEAR_DUPLICATE). Images without a view signature (for
    example decisions built in tests from scores alone) count as distinct, which is
    the previous behaviour.
    """
    from ..pipeline.views import view_distance, NEAR_DUPLICATE
    kept = []
    for a in sorted(angles, key=lambda d: d.fqs, reverse=True):
        sa = getattr(a, "view_sig", None)
        if all(view_distance(sa, getattr(o, "view_sig", None)) >= NEAR_DUPLICATE
               for o in [*heroes, *kept]):
            kept.append(a)
    return kept


def check_gate(decisions: list) -> GateResult:
    """Run the set-level gate over a list of ImageDecision objects (the SELECTED set).

    Only images that individually passed should be in this set, but the gate is
    defensive and re-checks FQS on everything it's given.
    """
    heroes = [d for d in decisions if d.role == "hero_shot" and d.fqs >= GATE_MIN_HERO_FQS]
    angles = [d for d in decisions if d.role == "angle_shot"]
    details = [d for d in decisions if d.role == "detail_shot"
               and d.semantic_scores.get("feature_visibility", 0.0) >= GATE_DETAIL_FEATVIS_MIN]

    distinct = _distinct_angles(angles, heroes)
    counts = {
        "total": len(decisions),
        "hero": len(heroes),
        "angle": len(angles),
        "distinct_angles": len(distinct),
        "detail": len(details),
    }

    fails = []
    if len(heroes) < GATE_MIN_HEROES:
        fails.append("no_hero_shot")
    if len(distinct) < GATE_MIN_ANGLES:
        fails.append("insufficient_angles")
    if len(details) < GATE_MIN_DETAILS:
        fails.append("no_detail_shot")
    if any(d.fqs < config.FQS_PASS_THRESHOLD for d in decisions):
        fails.append("low_overall_quality")
    if not (GATE_SET_MIN <= len(decisions) <= GATE_SET_MAX):
        fails.append("insufficient_coverage")

    if not fails:
        return GateResult(certified=True, fail_reasons=[],
                          instruction="Set certified.", counts=counts)

    # Lead the instruction with the first (highest-priority) failure.
    instruction = _INSTRUCTIONS.get(fails[0], "Improve the image set and retry.")
    return GateResult(certified=False, fail_reasons=fails,
                      instruction=instruction, counts=counts)
