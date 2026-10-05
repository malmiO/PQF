"""
PQF Pipeline (Phase D) - the end-to-end framework orchestrator.

This is the top level that makes the framework a single artefact. It runs each
image through the full flow and assembles a batch into the two user facing
outputs.

Per image flow, in specification order.
    standardise -> T0 platform gate -> technical engine (TQS)
                   |  hard reject if TQS below threshold, semantic is skipped
                   v
                   semantic evaluator (SQS)
                   |
                   v
                   combine -> FQS -> role -> pass or fail

Batch flow.
    score all -> keep passing -> select best set -> set level gate ->
    certify and build the role tagged output, or return a re capture signal.

The engines are imported lazily so batch logic can be tested with injected
scores without loading OpenCV or contacting the semantic model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..combination import decide_image, check_gate, ImageDecision


@dataclass
class BatchResult:
    certified: bool = False
    selected: list = field(default_factory=list)
    role_sets: dict = field(default_factory=dict)
    recapture: dict | None = None
    all_decisions: list = field(default_factory=list)


def score_image_from_scores(tqs: float, sqs: float, semantic_scores: dict,
                            path: str | None = None) -> ImageDecision:
    """Build a decision from already computed engine scores. Test friendly."""
    d = decide_image(tqs, sqs, semantic_scores)
    if path is not None:
        setattr(d, "path", path)
    return d


def _attach(d: ImageDecision, path: str | None) -> ImageDecision:
    if path is not None:
        setattr(d, "path", path)
    return d


def score_image(image_bytes: bytes, path: str | None = None,
                mime: str = "image/jpeg") -> ImageDecision:
    """Run one image through the complete framework.

    Accepts raw encoded image bytes. Decoding and standardisation happen here so
    that callers do not need to know the working resolution.
    """
    import numpy as np
    import cv2

    from ..preprocess import standardise
    from ..technical import compute_tqs

    # Decode the encoded bytes into an image array.
    # Trust the bytes, not the caller, for the type sent to the semantic model.
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"

    buf = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return _attach(ImageDecision(role="reject", passed=False,
                                     hard_rejected=True,
                                     reason="decode_failed"), path)

    # T0 platform compliance is checked on the ORIGINAL image, per the
    # specification, because standardising first would upscale an undersized
    # original to the working size and let it pass the resolution check.
    from ..technical import t0_compliance
    if not t0_compliance(img):
        return _attach(ImageDecision(role="reject", passed=False,
                                     hard_rejected=True,
                                     reason="t0_platform_spec_fail"), path)

    # Mandatory preprocessing before any metric is computed.
    img = standardise(img)

    # Technical engine. T0 is re-checked internally and will pass here.
    tech = compute_tqs(img, check_gate=False)  # T0 already checked on the original

    # Defensive. Should not trigger, since T0 was checked on the original above.
    if not tech.passed_gate:
        return _attach(ImageDecision(tqs=tech.tqs, role="reject", passed=False,
                                     hard_rejected=True,
                                     reason="t0_platform_spec_fail"), path)

    # Technical hard reject. Stop here, no semantic call, which also saves quota.
    if tech.hard_reject:
        d = decide_image(tech.tqs, 0.0, {})
        # Keep the per criterion technical scores so a hard-rejected image can
        # still report its weakest technical criterion (2026-10-05). Without
        # this the batch had no scores to explain the rejection, so the app
        # showed "Retake this one" with no reason.
        setattr(d, "technical_scores", tech.scores)
        return _attach(d, path)

    # Semantic evaluator.
    from ..semantic import evaluate_semantic
    sem = evaluate_semantic(image_bytes, mime)

    if not sem.ok:
        return _attach(ImageDecision(tqs=tech.tqs, role="reject", passed=False,
                                     reason=f"semantic_failed. {sem.error}"), path)

    d = decide_image(tech.tqs, sem.sqs, sem.scores)
    # Keep the per criterion technical scores available for reporting.
    setattr(d, "technical_scores", tech.scores)
    return _attach(d, path)


def _meets(role: str, d) -> bool:
    """True if a decision satisfies the specification's rule for a role."""
    rule = config.ROLE_RULES[role]
    return d.fqs >= rule["fqs_min"] and all(
        (d.semantic_scores or {}).get(k, 0.0) >= v
        for k, v in rule["criteria_min"].items())


def _assign_roles_in_set(passing: list) -> list:
    """Resolve roles across the SET, not image by image (fixed 2026-10-03).

    Each image is first classified on its own by the specification's rules,
    hero first. That turned every strong photograph into a hero, so a good
    angled shot was never counted as an angle and the gate could not be passed
    by taking better photographs. A set has ONE main shot, so:
      1. the highest FQS hero stays the hero;
      2. every OTHER hero is re-labelled angle, or else detail, if it meets
         that role's rule;
      3. a hero that meets neither stays an alternative hero.
    Images already labelled angle or detail are untouched. The rules and
    thresholds are the specification's own (config.ROLE_RULES), unchanged.
    """
    ranked = sorted(passing, key=lambda d: d.fqs, reverse=True)
    heroes = [d for d in ranked if d.role == "hero_shot"]
    for d in heroes[1:]:
        for role in ("angle_shot", "detail_shot"):
            if _meets(role, d):
                d.role = role
                break
    return ranked


def _select_best_set(passing: list) -> list:
    """Select the set forwarded to the gate, role aware (fixed 2026-10-03).

    The old version kept the top images by FQS whatever their role, so a batch
    of more than six could drop the only detail shot. The set now takes what the
    gate requires first (one hero, the angles, one detail), each the best of its
    role, then fills the remaining places by FQS, up to the gate maximum.
    """
    from ..combination.gate import (GATE_SET_MAX, GATE_MIN_HEROES,
                                    GATE_MIN_ANGLES, GATE_MIN_DETAILS)
    ranked = _assign_roles_in_set(passing)
    need = {"hero_shot": GATE_MIN_HEROES, "angle_shot": GATE_MIN_ANGLES,
            "detail_shot": GATE_MIN_DETAILS}
    chosen = []
    for role, n in need.items():
        chosen += [d for d in ranked if d.role == role][:n]
    for d in ranked:
        if len(chosen) >= GATE_SET_MAX:
            break
        if d not in chosen:
            chosen.append(d)
    return sorted(chosen[:GATE_SET_MAX], key=lambda d: d.fqs, reverse=True)


def process_batch(images: list) -> BatchResult:
    """Process a batch of images.

    `images` may be a list of (image_bytes, path) tuples, or a list of already
    scored ImageDecision objects for testing.
    """
    decisions = []
    for item in images:
        if isinstance(item, ImageDecision):
            decisions.append(item)
        else:
            image_bytes, path = item
            decisions.append(score_image(image_bytes, path))

    passing = [d for d in decisions if d.passed]
    selected = _select_best_set(passing)
    gate = check_gate(selected)

    role_sets = {"hero_shot": [], "angle_shot": [], "detail_shot": []}
    for d in selected:
        if d.role in role_sets:
            role_sets[d.role].append(d)

    if gate.certified:
        return BatchResult(certified=True, selected=selected,
                           role_sets=role_sets, recapture=None,
                           all_decisions=decisions)

    recapture = {
        "gate_status": "fail",
        "fail_reasons": gate.fail_reasons,
        "instruction": gate.instruction,
        "counts": gate.counts,
    }
    return BatchResult(certified=False, selected=selected,
                       role_sets=role_sets, recapture=recapture,
                       all_decisions=decisions)
