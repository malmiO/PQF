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
    # The model that actually answered (resp.model_version), so a result file can
    # say which model produced it even if the configured name were an alias.
    # "mock" in mock mode.
    model_version: str = ""


# The model_version of the most recent successful call, for /health.
LAST_MODEL_VERSION: str = ""


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
                          justification="[mock] deterministic score", ok=True,
                          model_version="mock")


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

    from . import gemini_common as gc

    def _do_call():
        # A fresh client per attempt, carrying the explicit per-call timeout.
        client = genai.Client(http_options=gc.http_options(types), api_key=api_key)
        return client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                build_prompt(),
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
            ],
            config=types.GenerateContentConfig(
                temperature=config.GEMINI_TEMPERATURE,
            ),
        )

    try:
        resp = gc.call_with_retry(_do_call, label="evaluate")
        result = _parse_response(resp.text)
        # The version that answered; fall back to the configured name.
        result.model_version = str(getattr(resp, "model_version", None) or config.GEMINI_MODEL)
        if result.ok:
            global LAST_MODEL_VERSION
            LAST_MODEL_VERSION = result.model_version
        return result
    except Exception as e:  # network / quota / safety / model-not-found etc.
        # Keep the reason code in the error so the API/study log can classify it.
        # A failed call is NOT cached (there is no semantic cache).
        return SemanticResult(ok=False,
                              error=f"gemini call failed [{gc.reason(str(e))}]: {e}")


def evaluate_semantic(image_bytes: bytes, mime: str = "image/jpeg") -> SemanticResult:
    """Evaluate one image's semantic quality. Uses mock mode if PQF_SEMANTIC_MOCK=1
    or if no API key is present (so nothing crashes in a keyless environment).

    A deterministic score cache (score_cache) keyed on (sha256 of these exact
    image bytes, prompt version, model id) means a repeat of an identical image
    returns the identical result and makes NO new Gemini call (2026-10-14).
    Failed calls are never cached; mock mode is not cached (already deterministic)."""
    global LAST_MODEL_VERSION
    if os.environ.get("PQF_SEMANTIC_MOCK") == "1":
        LAST_MODEL_VERSION = "mock"
        return _mock_evaluate(image_bytes)
    if not os.environ.get("GEMINI_API_KEY"):
        # NO silent fallback (2026-10-01). Mock is opt in via PQF_SEMANTIC_MOCK=1.
        return SemanticResult(ok=False, error="GEMINI_API_KEY not set")

    from . import score_cache as _sc
    from dataclasses import asdict
    key = _sc.key_for(image_bytes, config.PROMPT_VERSION, config.GEMINI_MODEL)
    cached = _sc.get(key)
    if cached is not None:
        result = SemanticResult(**cached)
        if result.model_version:
            LAST_MODEL_VERSION = result.model_version
        return result

    result = _gemini_evaluate(image_bytes, mime)
    if result.ok:  # only successful results are cached
        _sc.put(key, asdict(result))
    return result
