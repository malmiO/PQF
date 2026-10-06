"""
Semantic evaluator (Phase C) — SQS from a vision-language model.

Design rules baked in:
- Determinism: temperature 0 (config.GEMINI_TEMPERATURE).
- Versioned prompt: config.PROMPT_VERSION recorded with every result.
- Robust parsing: malformed model output never crashes a batch; it's flagged.
- NON-CIRCULARITY: this evaluator is NEVER used as a human-reference rater in
  validation (enforced by how validation is run, not here) — see methodology.
- Offline-testable: MOCK mode returns deterministic scores with no API call, so
  the pipeline and tests run without a key or credit.

Env:
  GEMINI_API_KEY   — API key (loaded from .env, never committed)
  PQF_SEMANTIC_MOCK=1 — force mock mode (used by tests / dry runs)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from .. import config
from .prompt import build_prompt, SEMANTIC_CRITERIA, ROLE_OPTIONS


@dataclass
class SemanticResult:
    scores: dict = field(default_factory=dict)   # per-criterion 0..1
    sqs: float = 0.0
    role: str = "reject"
    justification: str = ""
    prompt_version: str = config.PROMPT_VERSION
    ok: bool = True                               # False if parsing/model failed
    error: str = ""


def _clip01(x) -> float:
    try:
        return float(max(0.0, min(1.0, float(x))))
    except (TypeError, ValueError):
        return 0.0


def _aggregate_sqs(scores: dict) -> float:
    w = config.SQS_WEIGHTS
    return float(sum(w[k] * scores.get(k, 0.0) for k in w))


def _parse_response(text: str) -> SemanticResult:
    """Parse strict-JSON model output; tolerate stray markdown fences/whitespace."""
    raw = text.strip()
    # strip ```json ... ``` fences if the model added them
    fence = re.search(r"\{.*\}", raw, re.DOTALL)
    if not fence:
        return SemanticResult(ok=False, error="no JSON object in response")
    try:
        data = json.loads(fence.group(0))
    except json.JSONDecodeError as e:
        return SemanticResult(ok=False, error=f"JSON decode error: {e}")

    scores_in = data.get("scores", {})
    scores = {k: _clip01(scores_in.get(k, 0.0)) for k, _ in SEMANTIC_CRITERIA}
    role = data.get("role", "reject")
    if role not in ROLE_OPTIONS:
        role = "reject"
    return SemanticResult(
        scores=scores,
        sqs=_aggregate_sqs(scores),
        role=role,
        justification=str(data.get("justification", ""))[:300],
        ok=True,
    )


# ---------------------------------------------------------------------------
# Mock mode — deterministic, no API. Scores derive from a hash of the input so
# results are stable across runs (useful for pipeline tests + reliability plumbing).
# ---------------------------------------------------------------------------
def _mock_evaluate(image_bytes: bytes) -> SemanticResult:
    import hashlib
    h = hashlib.sha256(image_bytes).digest()
    scores = {}
    for i, (k, _) in enumerate(SEMANTIC_CRITERIA):
        scores[k] = round((h[i] / 255.0), 3)  # deterministic 0..1 per criterion
    sqs = _aggregate_sqs(scores)
    role = "hero_shot" if sqs >= 0.6 else ("detail_shot" if sqs >= 0.4 else "reject")
    return SemanticResult(scores=scores, sqs=sqs, role=role,
                          justification="[mock] deterministic score", ok=True)


# ---------------------------------------------------------------------------
# Real Gemini call — uses the NEW google-genai SDK (the old google-generativeai
# package reached end-of-life 2025-11-30). Install: pip install google-genai
# ---------------------------------------------------------------------------
def _gemini_evaluate(image_bytes: bytes, mime: str = "image/jpeg") -> SemanticResult:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return SemanticResult(ok=False, error="GEMINI_API_KEY not set")
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return SemanticResult(
            ok=False,
            error="google-genai not installed (pip install google-genai)",
        )

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                build_prompt(),
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
            ],
            config=types.GenerateContentConfig(
                temperature=config.GEMINI_TEMPERATURE,
            ),
        )
        return _parse_response(resp.text)
    except Exception as e:  # network / quota / safety / model-not-found etc.
        return SemanticResult(ok=False, error=f"gemini call failed: {e}")


def evaluate_semantic(image_bytes: bytes, mime: str = "image/jpeg") -> SemanticResult:
    """Evaluate one image's semantic quality. Uses mock mode if PQF_SEMANTIC_MOCK=1
    or if no API key is present (so nothing crashes in a keyless environment)."""
    if os.environ.get("PQF_SEMANTIC_MOCK") == "1":
        return _mock_evaluate(image_bytes)
    if not os.environ.get("GEMINI_API_KEY"):
        # NO silent fallback (2026-10-01). Mock is opt in via PQF_SEMANTIC_MOCK=1.
        return SemanticResult(ok=False, error="GEMINI_API_KEY not set")
    return _gemini_evaluate(image_bytes, mime)
