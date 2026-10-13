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


def _with_sig(sig, d, path):
    """Attach the view signature, then the path (2026-10-06)."""
    setattr(d, "view_sig", sig)
    return _attach(d, path)


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

    # View signature (2026-10-06): how this photo's view of the product looks, so
    # the set can prefer DIFFERENT angles and the gate can check that angle shots
    # are distinct, as spec Section 7 requires. Not a criterion; never scored.
    try:
        from .views import view_signature
        sig = view_signature(img)
    except Exception:
        sig = None

    # Technical engine. T0 is re-checked internally and will pass here.
    tech = compute_tqs(img, check_gate=False)  # T0 already checked on the original

    # Defensive. Should not trigger, since T0 was checked on the original above.
    if not tech.passed_gate:
        return _with_sig(sig, ImageDecision(tqs=tech.tqs, role="reject", passed=False,
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
        return _with_sig(sig, d, path)

    # Semantic evaluator.
    from ..semantic import evaluate_semantic
    sem = evaluate_semantic(image_bytes, mime)

    if not sem.ok:
        return _with_sig(sig, ImageDecision(tqs=tech.tqs, role="reject", passed=False,
                                     reason=f"semantic_failed. {sem.error}"), path)

    d = decide_image(tech.tqs, sem.sqs, sem.scores)
    # Keep the per criterion technical scores available for reporting.
    setattr(d, "technical_scores", tech.scores)
    # The model that answered, for the response and the study log (v1.4.0-rc).
    setattr(d, "model_version", getattr(sem, "model_version", ""))
    return _with_sig(sig, d, path)


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


# Best 4 to 5 (2026-10-06). The gate allows 4 to 6 images; a short video and a
# listing need 4 or 5. The set is the gate's required roles, each the best of its
# role, with the ANGLE PAIR chosen to be as different as possible from each other
# and from the main shot (Fan et al., KDD 2022: no two images from similar viewing
# angles), then at most one more photo, only if it shows a view not yet in the set.
# v1.1.0: exactly the four the gate requires (main, two distinct angles, detail),
# at the owner's request; extra photos are reported as "not needed".
SELECT_MAX = 4
DIVERSITY_FQS_WEIGHT = 0.25   # quality still counts: 0.1 FQS is worth 0.025 distance


def _dist(a, b) -> float:
    from .views import view_distance
    return view_distance(getattr(a, "view_sig", None), getattr(b, "view_sig", None))


def _min_dist(d, others) -> float:
    return min((_dist(d, o) for o in others), default=1.0)


def _select_best_set(passing: list) -> list:
    """Select the set forwarded to the gate (role aware 2026-10-03; diverse 2026-10-06).

    1. The main shot: the best hero. The detail: the best detail.
    2. The two angles: of all angle shots, the PAIR whose views differ most from
       each other and from the main shot, with FQS as a smaller second factor.
       An angle that repeats a view already chosen is left out.
    3. Fill to SELECT_MAX with the photo that adds the most different view, but
       never a near duplicate of a photo already chosen.
    Each image not chosen gets `selection_note` and, if it repeats a chosen view,
    `duplicate_of`, so the app can tell the owner why.
    """
    from itertools import combinations
    from .views import NEAR_DUPLICATE
    ranked = _assign_roles_in_set(passing)
    by = {r: [d for d in ranked if d.role == r]
          for r in ("hero_shot", "angle_shot", "detail_shot")}
    hero = by["hero_shot"][0] if by["hero_shot"] else None
    detail = by["detail_shot"][0] if by["detail_shot"] else None
    anchor = [hero] if hero else []

    angles = by["angle_shot"]
    if len(angles) >= 2:
        def pair_value(p):
            a, b = p
            spread = min(_dist(a, b), _min_dist(a, anchor), _min_dist(b, anchor))
            return spread + DIVERSITY_FQS_WEIGHT * (a.fqs + b.fqs) / 2
        pair = list(max(combinations(angles, 2), key=pair_value))
    else:
        pair = angles[:1]

    # An angle that repeats the main shot's view, or the other angle's, is not a
    # second view; leave it out so the gate asks for a real one.
    kept = []
    for a in pair:
        if _min_dist(a, anchor + kept) >= NEAR_DUPLICATE:
            kept.append(a)
    chosen = [d for d in [hero, *kept, detail] if d is not None]
    while len(chosen) < SELECT_MAX:
        pool = [d for d in ranked if d not in chosen
                and _min_dist(d, chosen) >= NEAR_DUPLICATE]
        if not pool:
            break
        chosen.append(max(pool, key=lambda d: _min_dist(d, chosen)
                          + DIVERSITY_FQS_WEIGHT * d.fqs))

    for d in ranked:
        if d in chosen:
            setattr(d, "selection_note", "selected")
            continue
        twin = min(chosen, key=lambda c: _dist(d, c), default=None)
        if twin is not None and _dist(d, twin) < NEAR_DUPLICATE:
            setattr(d, "selection_note", "same_view")
            setattr(d, "duplicate_of", twin)
        else:
            setattr(d, "selection_note", "not_needed")
    return chosen


def process_batch(images: list) -> BatchResult:
    """Process a batch of images.

    `images` may be a list of (image_bytes, path) tuples, or a list of already
    scored ImageDecision objects for testing.
    """
    # Score images with bounded concurrency (B3, 2026-10-13). Each image is
    # scored independently, so this changes only wall-clock time, never the
    # per-image scores. Order is preserved (results written back by position),
    # which the selection and the app's `index` rely on. Pre-scored
    # ImageDecision items (tests) pass straight through.
    import os as _os
    from concurrent.futures import ThreadPoolExecutor

    conc = max(1, int(_os.environ.get("PQF_BATCH_CONCURRENCY", "3")))
    decisions = [None] * len(images)
    to_score = []
    for i, item in enumerate(images):
        if isinstance(item, ImageDecision):
            decisions[i] = item
        else:
            image_bytes, path = item
            to_score.append((i, image_bytes, path))

    if to_score and conc > 1 and len(to_score) > 1:
        with ThreadPoolExecutor(max_workers=conc) as ex:
            scored = list(ex.map(
                lambda t: (t[0], score_image(t[1], t[2])), to_score))
        for i, d in scored:
            decisions[i] = d
    else:
        for i, b, p in to_score:
            decisions[i] = score_image(b, p)

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
