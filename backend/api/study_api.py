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

EVENTS = {"session_start", "capture_end", "own_picks", "batch_result", "video_ready",
          # v1.4.0 (2026-10-15): events the app logs in study mode
          "photo_captured", "help_card_shown", "setup_check_shown", "restart"}
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
           "photo_hashes", "own_picks", "framework_selection", "photos", "gate", "times",
           "model_version", "tier",
           # v1.4.0 (2026-10-15): what the app sends, each only on its own event (EXTRA_BY_EVENT)
           "group", "device_model", "app_version", "app_build", "apk_version",
           "condition_order", "same_product_as_first",
           "hash", "shot_requested", "retake_of", "source", "width", "height",
           "exif_orientation", "role", "seconds", "retakes", "photos_kept",
           "guidance_ms"}

# The new fields are accepted ONLY on the event that carries them. Anything else, and any
# field not listed in ALLOWED at all, is refused (400), so the log stays codes and numbers.
EXTRA_BY_EVENT = {
    "session_start": {"group", "device_model", "app_version", "app_build", "apk_version",
                      "condition_order", "same_product_as_first"},
    "photo_captured": {"hash", "shot_requested", "retake_of", "source", "width", "height",
                       "exif_orientation"},
    "help_card_shown": {"role", "seconds"},
    "setup_check_shown": {"role", "retakes"},
    "restart": {"role", "photos_kept"},
    # v1.4.0 (2026-10-15): round trip of each successful /guidance call, in ms. Empty in the
    # unguided condition, which makes no call.
    "capture_end": {"guidance_ms"},
}
MAX_GUIDANCE_MS_ENTRIES = 300
MAX_GUIDANCE_MS = 60000
GROUPS = {"seller", "non_expert"}
SOURCES = {"in_app", "upload"}
DEVICE_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+-]{0,47}$")
APP_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
APP_BUILD = re.compile(r"^\d{1,6}$")
APK_VERSION = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\+\d{1,6}$")
# Belt and braces: nothing that looks like a key, token or credential is stored, whatever
# field it arrives in (the field patterns above already make this very unlikely).
SECRET_LIKE = re.compile(
    r"(AIza[0-9A-Za-z_-]{16,}|sk-[A-Za-z0-9_-]{16,}|-----BEGIN|bearer\s|api[_-]?key|"
    r"passw(or)?d|secret|token\s*[=:]|authorization)", re.IGNORECASE)

# The model that answered a batch (v1.4.0-rc) and the API tier. Codes only: letters,
# digits, dot, dash, underscore; model_version up to 64 characters, tier up to 16.
MODEL_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
TIER = re.compile(r"^[A-Za-z0-9._-]{1,16}$")


def log_path() -> Path:
    """Where the study log is appended:
    PQF_STUDY_LOG (a file; tests use a temp file), else PQF_STUDY_DIR/study_log.jsonl
    (a deployed server points this at a persistent volume, because a container's
    own disk is wiped on every redeploy), else research/results/study_log.jsonl."""
    import os
    override = os.environ.get("PQF_STUDY_LOG")
    if override:
        return Path(override)
    folder = os.environ.get("PQF_STUDY_DIR")
    if folder:
        return Path(folder) / "study_log.jsonl"
    return Path(__file__).resolve().parents[2] / "research" / "results" / "study_log.jsonl"


def _num(v, name):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"{name} must be a number")
    return round(float(v), 4)


def _hash(v, name):
    if not isinstance(v, str) or not HASH.match(v):
        raise ValueError(f"{name} must be a SHA-256 hex hash")
    return v


EXTRA_BY_EVENT_ALL = set().union(*EXTRA_BY_EVENT.values())


def _refuse_secret_like(value, path="entry"):
    """Refuse any string anywhere in the entry that looks like a credential."""
    if isinstance(value, str):
        if SECRET_LIKE.search(value):
            raise ValueError(f"{path} looks like a secret and was not stored")
    elif isinstance(value, dict):
        for k, v in value.items():
            _refuse_secret_like(str(k), f"{path} key")
            _refuse_secret_like(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _refuse_secret_like(v, f"{path}[{i}]")


def _int(v, name, lo, hi, allow_none=False):
    if v is None and allow_none:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or not (lo <= v <= hi):
        raise ValueError(f"{name} must be a whole number {lo}..{hi}")
    return v


def _validate_new_fields(entry: dict, out: dict) -> None:
    """The fields the app added in v1.4.0, each checked against its own pattern."""
    if "group" in entry:
        if entry["group"] not in GROUPS:
            raise ValueError(f"group must be one of {sorted(GROUPS)}")
        out["group"] = entry["group"]
    if "device_model" in entry:
        v = entry["device_model"]
        if v != "" and not (isinstance(v, str) and DEVICE_MODEL.match(v)):
            raise ValueError("device_model must be a short model name")
        out["device_model"] = v
    for key, rx in (("app_version", APP_VERSION), ("app_build", APP_BUILD),
                    ("apk_version", APK_VERSION)):
        if key in entry:
            v = entry[key]
            if isinstance(v, int) and not isinstance(v, bool):
                v = str(v)
            if not (isinstance(v, str) and rx.match(v)):
                raise ValueError(f"{key} has the wrong form")
            out[key] = v
    if "condition_order" in entry:
        o = entry["condition_order"]
        if not (isinstance(o, list) and len(o) == 2 and set(o) == CONDITIONS):
            raise ValueError("condition_order is [GUIDED, UNGUIDED] in some order")
        out["condition_order"] = list(o)
    if "same_product_as_first" in entry:
        if not isinstance(entry["same_product_as_first"], bool):
            raise ValueError("same_product_as_first must be true or false")
        out["same_product_as_first"] = entry["same_product_as_first"]
    if "hash" in entry:
        out["hash"] = _hash(entry["hash"], "hash")
    if "shot_requested" in entry:
        if entry["shot_requested"] not in PICK_SLOTS:
            raise ValueError(f"shot_requested must be one of {sorted(PICK_SLOTS)}")
        out["shot_requested"] = entry["shot_requested"]
    if "retake_of" in entry:
        out["retake_of"] = (None if entry["retake_of"] is None
                            else _hash(entry["retake_of"], "retake_of"))
    if "source" in entry:
        if entry["source"] not in SOURCES:
            raise ValueError(f"source must be one of {sorted(SOURCES)}")
        out["source"] = entry["source"]
    for key in ("width", "height"):
        if key in entry:
            out[key] = _int(entry[key], key, 1, 30000, allow_none=True)
    if "exif_orientation" in entry:
        out["exif_orientation"] = _int(entry["exif_orientation"], "exif_orientation", 0, 8,
                                       allow_none=True)
    if "role" in entry:
        r = entry["role"]
        if r is not None and r not in ROLES:
            raise ValueError("role must be a pipeline role")
        out["role"] = r
    if "seconds" in entry:
        out["seconds"] = _int(entry["seconds"], "seconds", 0, 86400)
    if "retakes" in entry:
        out["retakes"] = _int(entry["retakes"], "retakes", 0, 100)
    if "photos_kept" in entry:
        out["photos_kept"] = _int(entry["photos_kept"], "photos_kept", 0, 200)
    if "guidance_ms" in entry:
        g = entry["guidance_ms"]
        if not isinstance(g, list) or len(g) > MAX_GUIDANCE_MS_ENTRIES:
            raise ValueError(f"guidance_ms is a list of at most {MAX_GUIDANCE_MS_ENTRIES} numbers")
        out["guidance_ms"] = [_int(v, "guidance_ms[]", 0, MAX_GUIDANCE_MS) for v in g]


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
    _refuse_secret_like(entry)
    own = EXTRA_BY_EVENT.get(out["event"], set())
    wrong = (EXTRA_BY_EVENT_ALL & set(entry)) - own
    if wrong:
        raise ValueError(f"{sorted(wrong)} not allowed on a {out['event']} entry")
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
    _validate_new_fields(entry, out)
    for key, rx in (("model_version", MODEL_VERSION), ("tier", TIER)):
        if key in entry:
            if out["event"] != "batch_result":
                raise ValueError(f"{key} is only allowed on batch_result entries")
            if not isinstance(entry[key], str) or not rx.match(entry[key]):
                raise ValueError(f"{key} must be a short code (letters, digits, . - _)")
            out[key] = entry[key]
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


@router.get("/study/log/download")
def study_log_download():
    """The study log as a file, for copying it off a deployed server (v1.1.0).
    Only when PQF_API_TOKEN is set: the protection middleware has then already
    checked the token. On a server without a token this is refused."""
    import os
    from fastapi.responses import FileResponse
    if not os.environ.get("PQF_API_TOKEN"):
        raise HTTPException(403, "Set PQF_API_TOKEN on the server to allow downloads.")
    p = log_path()
    if not p.exists():
        raise HTTPException(404, "No study log yet.")
    return FileResponse(str(p), media_type="application/x-ndjson",
                        filename="study_log.jsonl")


# --------------------------------------------------------------------------- order
def abba_order(participant: str) -> list:
    """The counterbalanced condition order for a participant code (ABBA over
    participants, A = UNGUIDED, B = GUIDED): P01 AB, P02 BA, P03 BA, P04 AB, P05 AB...
    The app shows the same order (study_session.dart)."""
    n = int(re.sub(r"\D", "", participant) or 0)
    ab = ["UNGUIDED", "GUIDED"]
    return ab if (n - 1) % 4 in (0, 3) else ab[::-1]
