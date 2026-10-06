"""
study_api.py  -  POST /study/log for the evaluation sessions (v1.1.0, Step 7).

Each call appends ONE JSON line to research/results/study_log.jsonl. Only codes
and numbers are accepted: a participant code (P01...), a condition, a product
code, photo hashes (never images), the participant's own picks, the framework's
selection and scores, the gate result and timestamps. Any other field, or a value
that does not look like a code, is refused (400), so a name, face or contact
detail cannot end up in the log by mistake.

Mounted in main.py with: app.include_router(study_router)
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()
_LOCK = threading.Lock()

EVENTS = {"session_start", "capture_end", "own_picks", "batch_result", "video_ready"}
CONDITIONS = {"GUIDED", "UNGUIDED"}
PICK_SLOTS = {"main", "angle1", "angle2", "detail"}
ROLES = {"hero_shot", "angle_shot", "detail_shot", "reject", ""}   # pipeline role values
TIME_KEYS = {"session_start", "capture_end", "video_ready"}

PARTICIPANT = re.compile(r"^P\d{2,3}$")
PRODUCT = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T[\d:.]+(Z|[+-]\d{2}:?\d{2})?$")
MAX_BYTES = 64 * 1024

ALLOWED = {"event", "timestamp", "participant", "condition", "product", "session",
           "photo_hashes", "own_picks", "framework_selection", "photos", "gate", "times"}


def log_path() -> Path:
    """research/results/study_log.jsonl, or PQF_STUDY_LOG (tests use a temp file)."""
    import os
    override = os.environ.get("PQF_STUDY_LOG")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "research" / "results" / "study_log.jsonl"


def _num(v, name):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"{name} must be a number")
    return round(float(v), 4)


def _hash(v, name):
    if not isinstance(v, str) or not HASH.match(v):
        raise ValueError(f"{name} must be a SHA-256 hex hash")
    return v


def validate(entry: dict) -> dict:
    """The entry with only allowed, well formed fields; ValueError otherwise."""
    if not isinstance(entry, dict):
        raise ValueError("body must be a JSON object")
    extra = set(entry) - ALLOWED
    if extra:
        raise ValueError(f"fields not allowed: {sorted(extra)}")
    out = {}
    if entry.get("event") not in EVENTS:
        raise ValueError(f"event must be one of {sorted(EVENTS)}")
    out["event"] = entry["event"]
    if not PARTICIPANT.match(str(entry.get("participant", ""))):
        raise ValueError("participant must be a code like P01")
    out["participant"] = entry["participant"]
    if entry.get("condition") not in CONDITIONS:
        raise ValueError("condition must be GUIDED or UNGUIDED")
    out["condition"] = entry["condition"]
    if not PRODUCT.match(str(entry.get("product", ""))):
        raise ValueError("product must be a short code")
    out["product"] = entry["product"]
    if "session" in entry:
        if entry["session"] not in (1, 2):
            raise ValueError("session must be 1 or 2")
        out["session"] = entry["session"]
    if not STAMP.match(str(entry.get("timestamp", ""))):
        raise ValueError("timestamp must be ISO 8601")
    out["timestamp"] = entry["timestamp"]
    if "photo_hashes" in entry:
        out["photo_hashes"] = [_hash(h, "photo_hashes[]") for h in entry["photo_hashes"]]
    if "own_picks" in entry:
        picks = entry["own_picks"]
        if not isinstance(picks, dict) or set(picks) - PICK_SLOTS:
            raise ValueError(f"own_picks keys must be {sorted(PICK_SLOTS)}")
        out["own_picks"] = {k: _hash(v, f"own_picks.{k}") for k, v in picks.items()}
    if "framework_selection" in entry:
        sel = []
        for s in entry["framework_selection"]:
            if not isinstance(s, dict) or set(s) - {"hash", "role"} or s.get("role") not in ROLES:
                raise ValueError("framework_selection items are {hash, role}")
            sel.append({"hash": _hash(s["hash"], "selection.hash"), "role": s["role"]})
        out["framework_selection"] = sel
    if "photos" in entry:
        photos = []
        for p in entry["photos"]:
            keys = {"hash", "tqs", "sqs", "fqs", "role", "passed", "selected"}
            if not isinstance(p, dict) or set(p) - keys or p.get("role", "") not in ROLES:
                raise ValueError(f"photos items have keys {sorted(keys)}")
            photos.append({"hash": _hash(p["hash"], "photos.hash"),
                           "tqs": _num(p.get("tqs", 0), "tqs"), "sqs": _num(p.get("sqs", 0), "sqs"),
                           "fqs": _num(p.get("fqs", 0), "fqs"), "role": p.get("role", ""),
                           "passed": bool(p.get("passed")), "selected": bool(p.get("selected"))})
        out["photos"] = photos
    if "gate" in entry:
        g = entry["gate"]
        if not isinstance(g, dict) or set(g) - {"certified", "missing"}:
            raise ValueError("gate is {certified, missing}")
        missing = g.get("missing", [])
        if not isinstance(missing, list) or any(m not in ROLES for m in missing):
            raise ValueError("gate.missing is a list of roles")
        out["gate"] = {"certified": bool(g.get("certified")), "missing": missing}
    if "times" in entry:
        t = entry["times"]
        if not isinstance(t, dict) or set(t) - TIME_KEYS or \
                any(v is not None and not STAMP.match(str(v)) for v in t.values()):
            raise ValueError(f"times keys are {sorted(TIME_KEYS)}, ISO 8601 values")
        out["times"] = dict(t)
    return out


@router.post("/study/log")
async def study_log(request: Request):
    raw = await request.body()
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "Log entry too large.")
    try:
        entry = validate(json.loads(raw or b"{}"))
    except (ValueError, json.JSONDecodeError) as e:
        raise HTTPException(400, f"Invalid study log entry: {e}")
    entry["received_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    p = log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")
    return {"ok": True}


# --------------------------------------------------------------------------- order
def abba_order(participant: str) -> list:
    """The counterbalanced condition order for a participant code (ABBA over
    participants, A = UNGUIDED, B = GUIDED): P01 AB, P02 BA, P03 BA, P04 AB, P05 AB...
    The app shows the same order (study_session.dart)."""
    n = int(re.sub(r"\D", "", participant) or 0)
    ab = ["UNGUIDED", "GUIDED"]
    return ab if (n - 1) % 4 in (0, 3) else ab[::-1]
