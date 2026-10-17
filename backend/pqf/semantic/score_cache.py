"""Deterministic semantic-score cache (2026-10-14).

Gemini at temperature 0 is still not byte-for-byte deterministic, so the SAME
captured photo re-submitted during a study got slightly different SQS and
occasional role flips. This cache makes a repeat of an IDENTICAL image return
the IDENTICAL result and make NO new Gemini call.

Key = sha256(scored image bytes) + prompt version + model id. So a change to the
prompt or the pinned model naturally invalidates old entries (different key),
which is why the key includes both - it does NOT change any prompt/model.

Rules:
  - Only successful (ok=True) results are cached; failures are never cached.
  - Persisted to disk when a volume is mounted (survives restarts), else kept in
    an ephemeral temp dir and in memory.
  - Disable with PQF_SCORE_CACHE=off (used by the re-scoring analysis).

This module changes no criterion, weight, threshold, prompt or model id.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path

_LOCK = threading.Lock()
_MEM: dict[str, dict] = {}
_HITS = 0
_MISSES = 0


def enabled() -> bool:
    return os.environ.get("PQF_SCORE_CACHE", "on").lower() not in ("off", "0", "false")


def _dir() -> Path:
    """Where entries persist. A mounted volume (Railway) makes it durable; the
    temp fallback is ephemeral (lost on restart), which is still correct within
    a run."""
    explicit = os.environ.get("PQF_SCORE_CACHE_DIR")
    vol = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    base = explicit or (os.path.join(vol, "pqf_score_cache") if vol else None) \
        or os.path.join(tempfile.gettempdir(), "pqf_score_cache")
    p = Path(base)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def is_persistent() -> bool:
    return bool(os.environ.get("PQF_SCORE_CACHE_DIR")
               or os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"))


def key_for(image_bytes: bytes, prompt_version: str, model_id: str) -> str:
    h = hashlib.sha256(image_bytes).hexdigest()
    return hashlib.sha256(
        f"{h}|{prompt_version}|{model_id}".encode("utf-8")).hexdigest()


def get(key: str) -> dict | None:
    """Return the cached result dict, or None. Counts a hit/miss."""
    global _HITS, _MISSES
    if not enabled():
        return None
    with _LOCK:
        if key in _MEM:
            _HITS += 1
            return dict(_MEM[key])
    f = _dir() / f"{key}.json"
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            with _LOCK:
                _MEM[key] = data
                _HITS += 1
            return dict(data)
        except (OSError, ValueError):
            pass
    with _LOCK:
        _MISSES += 1
    return None


def put(key: str, result: dict) -> None:
    """Store a SUCCESSFUL result only. Never called for failures."""
    if not enabled():
        return
    with _LOCK:
        _MEM[key] = dict(result)
    try:
        (_dir() / f"{key}.json").write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass  # memory cache still serves this process


def stats() -> dict:
    with _LOCK:
        mem = len(_MEM)
        hits, misses = _HITS, _MISSES
    try:
        entries = len(list(_dir().glob("*.json")))
    except OSError:
        entries = mem
    return {"enabled": enabled(), "hits": hits, "misses": misses,
            "entries": entries, "persistent": is_persistent(),
            "dir": str(_dir())}
