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
    tech = compute_tqs(img)

    # Defensive. Should not trigger, since T0 was checked on the original above.
    if not tech.passed_gate:
        return _attach(ImageDecision(tqs=tech.tqs, role="reject", passed=False,
                                     hard_rejected=True,
                                     reason="t0_platform_spec_fail"), path)

    # Technical hard reject. Stop here, no semantic call, which also saves quota.
    if tech.hard_reject:
        return _attach(decide_image(tech.tqs, 0.0, {}), path)

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


def _select_best_set(passing: list) -> list:
    """Select the set forwarded to the gate. Best by FQS, capped at the gate maximum."""
    from ..combination.gate import GATE_SET_MAX
    ranked = sorted(passing, key=lambda d: d.fqs, reverse=True)
    return ranked[:GATE_SET_MAX]


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
