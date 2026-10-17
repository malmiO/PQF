"""
Combination (Phase D) — merge technical + semantic scores into the Final Quality
Score (FQS) and classify each image's role.

Spec v1.3:
  - Section 5:  FQS = alpha*TQS + beta*SQS   (alpha=0.40, beta=0.60)
                HARD REJECT before combination: TQS < 0.40
                PASS: FQS >= 0.55
  - Section 4.3: role classification (hero / angle / detail / reject), first
                matching rule wins in priority order.

All thresholds are read from config (which is spec-aligned), so this module
contains no magic numbers — the spec drives behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config


# TQS below this is hard-rejected BEFORE the semantic stage even runs (spec Sec 3/5).
TQS_HARD_REJECT = getattr(config, "TQS_HARD_REJECT", 0.40)


@dataclass
class ImageDecision:
    """The framework's full decision for a single image."""
    tqs: float = 0.0
    sqs: float = 0.0
    fqs: float = 0.0
    role: str = "reject"
    passed: bool = False              # FQS >= FQS_PASS_THRESHOLD
    hard_rejected: bool = False       # TQS < TQS_HARD_REJECT (semantic skipped)
    semantic_scores: dict = field(default_factory=dict)
    reason: str = ""


def combine_fqs(tqs: float, sqs: float) -> float:
    """FQS = alpha*TQS + beta*SQS (spec Section 5)."""
    return float(config.FQS_ALPHA * tqs + config.FQS_BETA * sqs)


def classify_role(fqs: float, semantic_scores: dict) -> str:
    """Assign a role using the spec's rules (config.ROLE_RULES), first match wins.

    A rule matches when FQS >= its fqs_min AND every named per-criterion minimum
    is met. If no rule matches, the image is 'reject'.
    """
    for role in config.ROLE_PRIORITY:
        rule = config.ROLE_RULES[role]
        if fqs < rule["fqs_min"]:
            continue
        if all(semantic_scores.get(k, 0.0) >= v
               for k, v in rule["criteria_min"].items()):
            return role
    return "reject"


def decide_image(tqs: float,
                 sqs: float,
                 semantic_scores: dict | None = None) -> ImageDecision:
    """Produce the full per-image decision from the two engine scores.

    Order matches the spec: TQS hard-reject gate first (semantic is skipped for a
    hard-rejected image in the real pipeline), then FQS, then role + pass check.
    """
    semantic_scores = semantic_scores or {}

    # 1. Hard reject on technical quality before anything else.
    if tqs < TQS_HARD_REJECT:
        return ImageDecision(
            tqs=tqs, sqs=sqs, fqs=0.0, role="reject",
            passed=False, hard_rejected=True,
            semantic_scores=semantic_scores,
            reason=f"hard_reject_tqs_below_{TQS_HARD_REJECT}",
        )

    # 2. Combine.
    fqs = combine_fqs(tqs, sqs)

    # 3. Role + overall pass.
    role = classify_role(fqs, semantic_scores)
    passed = fqs >= config.FQS_PASS_THRESHOLD and role != "reject"

    return ImageDecision(
        tqs=tqs, sqs=sqs, fqs=fqs, role=role,
        passed=passed, hard_rejected=False,
        semantic_scores=semantic_scores,
        reason="ok" if passed else "below_fqs_pass_or_no_role",
    )
