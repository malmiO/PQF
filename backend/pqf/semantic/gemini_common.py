"""Shared Gemini call policy: an explicit per-call timeout and a bounded retry
on transient errors only. Used by the semantic evaluator and the video feature
locator so both behave the same (added 2026-10-13, Part B).

WHY THESE VALUES. gemini_probe.py measured raw first-attempt latency on the free
tier at ~50-101 s for a success, with intermittent 503s. So:
  - the per-call timeout is set ABOVE the measured max (120 s default), not a
    guess, so a genuinely slow success is not cut off; it is env-overridable.
  - only 429/503 (RESOURCE_EXHAUSTED / UNAVAILABLE) are retried, with
    exponential backoff that respects Retry-After. A TIMEOUT is NOT retried
    (the call was already slow; retrying only doubles quota/load).

This module changes NO criterion, weight, threshold, prompt or model id.
"""
from __future__ import annotations

import logging
import os
import re
import time

_LOG = logging.getLogger("pqf.gemini")

# Per-call HTTP timeout in milliseconds (google-genai HttpOptions.timeout is ms).
TIMEOUT_MS = int(os.environ.get("PQF_GEMINI_TIMEOUT_MS", "120000"))
# Extra attempts after the first, on transient errors only.
MAX_RETRIES = int(os.environ.get("PQF_GEMINI_MAX_RETRIES", "2"))
# Exponential backoff base (seconds) and ceiling.
BASE_BACKOFF_S = float(os.environ.get("PQF_GEMINI_BACKOFF_S", "2"))
MAX_BACKOFF_S = float(os.environ.get("PQF_GEMINI_BACKOFF_MAX_S", "20"))

_TRANSIENT = ("RESOURCE_EXHAUSTED", "UNAVAILABLE", " 429", " 503", "429 ", "503 ")
_REASONS = ("API_KEY_INVALID", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
            "NOT_FOUND", "INVALID_ARGUMENT", "UNAUTHENTICATED", "UNAVAILABLE",
            "DEADLINE_EXCEEDED")


def http_options(types):
    """An HttpOptions carrying the explicit per-call timeout."""
    return types.HttpOptions(timeout=TIMEOUT_MS)


def reason(text: str) -> str:
    up = (text or "").upper()
    for code in _REASONS:
        if code in up:
            return code
    for s in ("429",):
        if s in up:
            return "RESOURCE_EXHAUSTED"
    if "503" in up:
        return "UNAVAILABLE"
    return "other"


def is_transient(exc: Exception) -> bool:
    """429/503 only. A timeout (DEADLINE_EXCEEDED) is deliberately NOT transient:
    we never auto-resubmit a slow call."""
    t = str(exc).upper()
    return any(s.strip() in t for s in _TRANSIENT)


def _retry_after_s(exc: Exception) -> float | None:
    m = re.search(r"retry-?after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)",
                  str(exc), re.IGNORECASE)
    return float(m.group(1)) if m else None


def call_with_retry(do_call, label: str = "gemini"):
    """Run do_call() with a bounded retry on transient errors only.

    do_call: a zero-arg callable that performs ONE generate_content and returns
    its response (it should build its own client with http_options(types)).
    Raises the last exception if all attempts fail.
    """
    last = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return do_call()
        except Exception as e:  # noqa: BLE001
            last = e
            code = reason(str(e))
            transient = is_transient(e)
            _LOG.warning("%s attempt %d/%d failed: reason=%s transient=%s",
                         label, attempt + 1, MAX_RETRIES + 1, code, transient)
            if attempt < MAX_RETRIES and transient:
                delay = _retry_after_s(e) or (BASE_BACKOFF_S * (2 ** attempt))
                time.sleep(min(delay, MAX_BACKOFF_S))
                continue
            raise
    if last:
        raise last
