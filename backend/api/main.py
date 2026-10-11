"""
PQF API.

Exposes the Photography Quality Framework over HTTP so the mobile application
can use it. The framework itself lives in backend.pqf and is not duplicated
here. This layer only handles transport, validation and shaping of responses.

Endpoints
    GET  /health              liveness and configuration summary
    POST /score               score one image, full framework, returns a decision
    POST /guidance            fast on device style check, cheap criteria only
    POST /batch               score several images, select a set, run the gate
    GET  /criteria            the criteria, weights and thresholds in force

Run locally
    uvicorn backend.api.main:app --reload --host 0.0.0.0 --port 8000

The mobile client on a physical device cannot reach localhost on your machine,
so use your machine's LAN address, for example http://192.168.1.5:8000
"""
from __future__ import annotations

# Load secrets BEFORE anything reads the environment (fixed 2026-10-01:
# without this the server silently used mock semantic scores).
import os
from dotenv import load_dotenv
load_dotenv()

import io
import time
from typing import List

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..pqf import config
from ..pqf.pipeline import score_image, process_batch
from ..pqf.combination import ImageDecision

def _semantic_mode() -> str:
    if os.environ.get("PQF_SEMANTIC_MOCK") == "1":
        return "MOCK (testing only, scores are not real judgements)"
    return "LIVE" if os.environ.get("GEMINI_API_KEY") else "MISSING_KEY"


if _semantic_mode() == "MISSING_KEY":
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Put it in backend .env (local) or the "
        "host's environment variables (deployed). For offline tests only, "
        "set PQF_SEMANTIC_MOCK=1.")


app = FastAPI(
    title="Photography Quality Framework API",
    description="Scores product photographs against the PQF specification.",
    version="1.0.0",
)

# The mobile client is a separate origin. Open during development only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Access token (when PQF_API_TOKEN is set) and per-IP rate limits (v1.1.0).
from .protection import protect as _protect, router as _auth_router  # noqa: E402
app.middleware("http")(_protect)
app.include_router(_auth_router)

MAX_UPLOAD_BYTES = 12 * 1024 * 1024

# Live guidance parameters. Guidance trades precision for speed, because it runs
# repeatedly on a viewfinder frame rather than once on a capture decision.
GUIDANCE_LONGEST_SIDE = 512   # analysed size for live frames
GUIDANCE_PASS_MIN = 0.40      # exposure and background pass mark
GUIDANCE_SHARPNESS_MIN = 0.12 # lower than scoring, since variance falls with size

# Framing proxy bounds. A product filling between roughly a tenth and two
# thirds of the frame reads well in a catalogue listing. Outside that it is
# either lost or cramped.
GUIDANCE_MIN_PRODUCT_AREA = 0.10
GUIDANCE_MAX_PRODUCT_AREA = 0.68
GUIDANCE_CENTRE_TOLERANCE = 0.34

# Background diagnosis for live guidance (2026-10-05). A uniform border whose
# brightness is between these values is a plain background that reads grey.
GUIDANCE_BG_GREY_MIN = 140
GUIDANCE_BG_UNIFORM_SPREAD = 40
GREY_BACKGROUND_MSG = ("The background looks grey. Raise the brightness: tap the "
                       "product, then slide the brightness up.")

# Per shot framing for LIVE GUIDANCE only (added 2026-10-03). The certification
# rules are unchanged. A detail shot is a close up: the product legitimately fills
# the frame and touches its edges, so the main shot bounds would block it forever.
# (min product area, max product area, product may touch the edges)
# Auto zoom (v1.1.0). The size each shot type is zoomed towards, as the share of
# the scored region the product covers: the middle of its allowed range, so the
# zoom stops well inside it rather than at the edge. Design prior.
GUIDANCE_ZOOM_TARGET_AREA = {"main": 0.32, "angle": 0.32, "extra": 0.32, "detail": 0.55}
# Zoom never pushes the product closer than this to the frame edge (share of the
# half width / half height from the centre).
GUIDANCE_ZOOM_EDGE_LIMIT = 0.92
# A hint smaller than this change is not worth acting on (dead band).
GUIDANCE_ZOOM_MIN_STEP = 0.08

GUIDANCE_SHOT_FRAMING = {
    "main":   (GUIDANCE_MIN_PRODUCT_AREA, GUIDANCE_MAX_PRODUCT_AREA, False),
    "angle":  (GUIDANCE_MIN_PRODUCT_AREA, GUIDANCE_MAX_PRODUCT_AREA, False),
    "extra":  (GUIDANCE_MIN_PRODUCT_AREA, GUIDANCE_MAX_PRODUCT_AREA, False),
    "detail": (0.30, 1.00, True),
}


def _background_diagnosis(img) -> str:
    """Why the background check failed: 'grey' or 'cluttered' (added 2026-10-05).

    A plain light background that reads grey (a budget lightbox, auto exposure
    pulling white towards mid grey) is fixed by RAISING THE BRIGHTNESS, not by
    changing the surface. A cluttered background is fixed by changing the
    surface. Telling them apart: a plain background is UNIFORM in the border.
    """
    import numpy as np
    h, w = img.shape[:2]
    b = max(2, int(min(h, w) * config.T3_BORDER_FRACTION))
    border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3),
                             img[:, :b].reshape(-1, 3), img[:, -b:].reshape(-1, 3)])
    lum = border.mean(axis=1)
    p10, p90 = np.percentile(lum, 10), np.percentile(lum, 90)
    chroma = float(np.median(border.max(axis=1) - border.min(axis=1)))
    uniform = (p90 - p10) <= GUIDANCE_BG_UNIFORM_SPREAD and chroma <= 25
    if uniform and GUIDANCE_BG_GREY_MIN <= float(np.median(lum)) < config.T3_WHITE_THRESHOLD:
        return "grey"
    return "cluttered"


def _crop_to_platform(img):
    """Centre crop an image ARRAY to the platform aspect range (4:5 to 1.91:1).

    Same geometry as _platform_format, which crops the captured photo before
    scoring. Guidance uses it so the live checks look at exactly the region
    that will be scored, not the strips above and below it that will be
    thrown away (added 2026-10-03)."""
    lo, hi = config.T0_ASPECT_MIN, config.T0_ASPECT_MAX
    h, w = img.shape[:2]
    if w / h < lo:
        new_h = int(w / lo)
        top = (h - new_h) // 2
        return img[top:top + new_h, :]
    if w / h > hi:
        new_w = int(h * hi)
        left = (w - new_w) // 2
        return img[:, left:left + new_w]
    return img
# Declared content types we accept. octet-stream is included deliberately,
# because several HTTP clients, including Flutter's, omit the type on a
# multipart part and the transport defaults to octet-stream. Rejecting on the
# DECLARED type alone is unreliable, so the bytes are decoded and validated
# instead, which is the check that actually matters.
ALLOWED_MIME = {
    "image/jpeg", "image/jpg", "image/png", "image/webp",
    "application/octet-stream", None, "",
}


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------
class CriterionScore(BaseModel):
    name: str
    score: float
    weight: float
    passed: bool | None = None


class ScoreResponse(BaseModel):
    tqs: float
    sqs: float
    fqs: float
    role: str
    passed: bool
    hard_rejected: bool
    reason: str
    technical: List[CriterionScore]
    semantic: List[CriterionScore]
    feedback: List[str]
    elapsed_ms: int
    # The model that answered ("" if no semantic call was made) and the API tier
    # (v1.4.0-rc), so every result can be traced to the build that produced it.
    model_version: str = ""
    tier: str = ""


class GuidanceResponse(BaseModel):
    ready: bool
    checks: List[CriterionScore]
    feedback: List[str]
    elapsed_ms: int
    # +1 means "raise the brightness", -1 "lower it", 0 no change. Lets the app
    # adjust exposure compensation itself, the step a photographer does by hand.
    exposure_hint: int = 0
    # Auto zoom (v1.1.0): the zoom factor to apply ON TOP of the current zoom so
    # the product reaches its target size (1.0 = leave it). Measured on the frame
    # as the camera sends it, so it is always relative to the current zoom.
    zoom_hint: float = 1.0


class BatchImageResult(BaseModel):
    index: int
    fqs: float
    role: str
    passed: bool
    # Included so the app can explain a verdict rather than only state it. A
    # seller told an image was not used, with no reason, learns nothing.
    tqs: float = 0.0
    sqs: float = 0.0
    reason: str = ""
    weakest: str = ""


class BatchResponse(BaseModel):
    certified: bool
    selected: List[BatchImageResult]
    role_sets: dict
    recapture: dict | None
    elapsed_ms: int
    images: list = []       # every photo: chosen or not, and why (2026-10-06)
    missing: list = []      # shots still to take: [{role, count, message}]
    model_version: str = ""  # from the first semantic result of the request
    tier: str = ""


# ---------------------------------------------------------------------------
# Corrective feedback, driven by which criterion failed
# ---------------------------------------------------------------------------
FEEDBACK = {
    "sharpness":   "Hold the phone steady and tap the product to focus.",
    "exposure":    "Adjust the brightness. Move to better light if the product looks dark.",
    "background":  "Place the product on a plain white or light surface.",
    "brisque":     "Image quality is low overall. Clean the lens and retake.",
    "piqe":        "Part of the image is unclear. Retake with steadier hands.",
    "colorcast":   "Colour looks tinted. Use neutral lighting or adjust white balance.",
    "subject_centering":      "Centre the product in the frame and avoid cutting it off.",
    "feature_visibility":     "Move closer or adjust the angle so the details are visible.",
    "marketing_suitability":  "The shot does not look ready to post. Improve lighting and framing.",
    "angle_value":            "Try a different angle that shows more about the product.",
    "lighting_style_quality": "Improve the lighting. Avoid harsh shadows on the product.",
}


def _read_upload(f: UploadFile) -> bytes:
    """Read and validate an uploaded image.

    Validation is by magic bytes rather than by the declared content type,
    because clients frequently omit the type and the transport substitutes
    application/octet-stream. What matters is whether the bytes are a decodable
    image, not what the client claimed.
    """
    if f.content_type and f.content_type not in ALLOWED_MIME:
        raise HTTPException(
            415, f"Unsupported type {f.content_type}. Send JPEG, PNG or WebP.")

    data = f.file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            413, f"File too large. Limit is {MAX_UPLOAD_BYTES // (1024*1024)} MB.")

    # Magic byte check. JPEG starts FF D8, PNG starts 89 50 4E 47,
    # WebP is RIFF....WEBP.
    head = data[:12]
    is_jpeg = head[:2] == b"\xff\xd8"
    is_png = head[:4] == b"\x89PNG"
    is_webp = head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if not (is_jpeg or is_png or is_webp):
        raise HTTPException(
            415, "That file is not a readable JPEG, PNG or WebP image.")

    return data


def _platform_format(data: bytes) -> bytes:
    """Fit an out of range photo to the nearest platform aspect, losslessly.

    Upright phone photos are 3:4 or 9:16. T0 accepts 4:5 to 1.91:1, the range
    social feeds display, so ordinary upright photos failed T0 and scored zero.
    Platforms centre crop such photos on upload, so the same step runs here,
    BEFORE the framework, and the framework scores the image that would be
    posted. In range images are returned byte for byte, no re-encode. Out of
    range images are centre cropped and encoded as PNG (lossless). The
    framework, including T0, is unchanged. (Added 2026-10-01.)
    """
    import numpy as np
    import cv2
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return data
    lo, hi = config.T0_ASPECT_MIN, config.T0_ASPECT_MAX
    h, w = img.shape[:2]
    if lo <= w / h <= hi:
        return data
    if max(h, w) > 2048:  # keep the PNG well under the model's upload limit
        k = 2048 / max(h, w)
        img = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    if w / h < lo:  # too tall. Crop last, rounding down, so it lands in range
        new_h = int(w / lo)
        top = (h - new_h) // 2
        img = img[top:top + new_h, :]
    else:
        new_w = int(h * hi)
        left = (w - new_w) // 2
        img = img[:, left:left + new_w]
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else data


def _shape(d: ImageDecision) -> tuple[list, list, list]:
    """Turn a decision into per criterion lists plus corrective feedback."""
    tech_raw = getattr(d, "technical_scores", {}) or {}
    # Each technical criterion is judged against its own pass threshold
    # (config.TQS_PASS_THRESHOLDS, v1.4.0), replacing the blanket 0.40 cut. A criterion
    # with weight 0 (T4, excluded) is still returned for reporting; its threshold is 0.0
    # so it never gives feedback.
    technical = [
        CriterionScore(
            name=k,
            score=round(tech_raw.get(k, 0.0), 3),
            weight=w,
            passed=tech_raw.get(k, 0.0) >= config.TQS_PASS_THRESHOLDS[k],
        )
        for k, w in config.TQS_WEIGHTS.items()
    ]
    semantic = [
        CriterionScore(
            name=k,
            score=round(d.semantic_scores.get(k, 0.0), 3),
            weight=w,
            passed=d.semantic_scores.get(k, 0.0) >= config.SQS_PASS_THRESHOLDS.get(k, 0.0),
        )
        for k, w in config.SQS_WEIGHTS.items()
    ] if d.semantic_scores else []

    feedback = []
    for c in technical:
        if c.passed is False and c.name in FEEDBACK:
            feedback.append(FEEDBACK[c.name])
    for c in semantic:
        if c.passed is False and c.name in FEEDBACK:
            feedback.append(FEEDBACK[c.name])
    return technical, semantic, feedback


def _framing_check(img, T, min_area: float = None, max_area: float = None,
                   allow_edges: bool = False, info: dict | None = None) -> tuple[float, str]:
    """Cheap composition check for live guidance.

    Returns a score and, when it fails, the single most useful instruction.

    Four faults are detected, in order of how badly they hurt the shot. The
    product touching an edge, meaning it is cut off. The product occupying too
    little of the frame, meaning the user is too far away. The product filling
    almost everything, leaving no breathing room. The product sitting away from
    centre.

    The product region is computed here directly rather than through the
    framework's product_mask, because that function falls back to a central
    rectangle when it finds very little product, which is sensible for scoring
    but would hide the very case this check exists to catch, a product that is
    too small in the frame.

    This is a guidance proxy, not a framework criterion. Composition is scored
    properly by the semantic evaluator after capture.

    `info`, if given, receives what was measured (area, the product's extent
    from the centre, whether it is cut off), for the auto zoom hint (v1.1.0).
    """
    import numpy as np
    import cv2

    try:
        # Background estimated from the border, as the framework now does, so a
        # light grey lightbox background is not mistaken for product touching
        # every edge (2026-10-05). No central fallback here on purpose: this
        # check exists to catch a product that is too small.
        hh, ww = img.shape[:2]
        bb = max(2, int(min(hh, ww) * config.T3_BORDER_FRACTION))
        border = np.concatenate([img[:bb].reshape(-1, 3), img[-bb:].reshape(-1, 3),
                                 img[:, :bb].reshape(-1, 3), img[:, -bb:].reshape(-1, 3)])
        bg = np.median(border, axis=0)
        spread = np.median(np.abs(border - bg), axis=0).max()
        # A detail close up fills the frame, so its border IS the product, not a
        # plain light background. That is the intended framing for a detail shot.
        if allow_edges and (float(bg.mean()) < GUIDANCE_BG_GREY_MIN
                            or float(spread) > GUIDANCE_BG_UNIFORM_SPREAD / 2):
            return 1.0, ""
        delta = min(config.PRODUCT_BG_DELTA_MAX,
                max(config.PRODUCT_BG_DELTA_MIN, config.PRODUCT_BG_DELTA_K * float(spread)))
        matching = (np.abs(border.astype(np.int16) - bg.astype(np.int16)).max(axis=1)
                <= config.PRODUCT_BG_DELTA_MIN).mean()
        if matching < config.PRODUCT_BG_MIN_MATCH:
            mask = ~np.all(img >= config.T3_WHITE_THRESHOLD, axis=2)   # border is product
        else:
            mask = np.abs(img.astype(np.int16) - bg.astype(np.int16)).max(axis=2) > delta
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(
            mask.astype(np.uint8), cv2.MORPH_OPEN, kernel).astype(bool)
    except Exception:
        return 1.0, ""

    h, w = mask.shape[:2]
    area = float(mask.mean())
    min_area = GUIDANCE_MIN_PRODUCT_AREA if min_area is None else min_area
    max_area = GUIDANCE_MAX_PRODUCT_AREA if max_area is None else max_area

    if area < 0.004:
        return 0.0, "Point the camera at your product."

    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    if not rows.any() or not cols.any():
        return 0.0, "Point the camera at your product."
    top, bottom = np.where(rows)[0][[0, -1]]
    left, right = np.where(cols)[0][[0, -1]]
    if info is not None:
        # how far the product reaches from the centre, as a share of half the
        # frame (1.0 = touching the edge); zooming by k multiplies this by k
        info["area"] = area
        info["reach"] = max(abs(left / w - 0.5), abs((right + 1) / w - 0.5),
                            abs(top / h - 0.5), abs((bottom + 1) / h - 0.5)) * 2.0

    # Cut off. A small margin avoids flagging a product that merely sits close
    # to the edge without crossing it.
    m = max(2, int(min(h, w) * 0.02))
    if not allow_edges and (top <= m or left <= m or bottom >= h - 1 - m or right >= w - 1 - m):
        if info is not None:
            info["cut_off"] = True
        return 0.10, "Part of the product is cut off. Move back a little."

    if area < min_area:
        return 0.15, "Move closer. The product is too small in the frame."

    if area > max_area:
        return 0.25, "Move back slightly. Leave a little space around the product."

    # Off centre, measured from the centroid of the product region as a
    # fraction of half the frame.
    ys, xs = np.nonzero(mask)
    cx, cy = float(xs.mean()) / w, float(ys.mean()) / h
    dx, dy = cx - 0.5, cy - 0.5
    off = max(abs(dx), abs(dy)) * 2.0
    if off > GUIDANCE_CENTRE_TOLERANCE:
        if abs(dy) > abs(dx):
            direction = "up" if dy > 0 else "down"
        else:
            direction = "left" if dx > 0 else "right"
        return 0.30, f"Move the camera {direction} to centre the product."

    return 1.0, ""


def _zoom_hint(info: dict, shot: str, min_area: float, max_area: float) -> float:
    """Zoom factor (relative to the current zoom) for the live auto zoom.

    Acts only when the size is OUTSIDE the shot's allowed range, and then aims at
    the middle of it, so the zoom does not hunt around a limit. Zooming in is
    capped so the product never gets closer to an edge than
    GUIDANCE_ZOOM_EDGE_LIMIT (zoom is about the centre, so an off centre product
    would otherwise be pushed out of the frame). A cut off product asks for a
    small zoom out; the app ignores that when it is already at its widest.
    Never calls the model; computed from the framing check's own measurement.
    """
    if info.get("cut_off"):
        return 0.85
    area, reach = info.get("area"), info.get("reach")
    if not area or not reach or min_area <= area <= max_area:
        return 1.0
    k = (GUIDANCE_ZOOM_TARGET_AREA.get(shot, 0.32) / area) ** 0.5   # area grows with k^2
    if k > 1.0:
        k = min(k, GUIDANCE_ZOOM_EDGE_LIMIT / reach)
    k = max(0.5, min(2.0, k))
    return 1.0 if abs(k - 1.0) < GUIDANCE_ZOOM_MIN_STEP else round(k, 3)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    # Video readiness, so the app and the operator can see at a glance why video
    # is unavailable: ffmpeg missing, or no music installed (added 2026-10-05).
    from pathlib import Path as _Path
    from ..video import audio as _A
    from ..video.builder import ffmpeg_available
    # Per mood, and whether any generated test tone is still offered (v1.1.0).
    _base = _Path(__file__).resolve().parents[2]
    try:
        _music_tracks = _A.tracks_per_mood(_base)
        _test_tones = any(t.is_test_tone for t in _A.recommend(None, _base).tracks)
    except Exception:
        _music_tracks, _test_tones = {m: 0 for m in _A.MOODS}, False
    from ..pqf import RELEASE as _RELEASE
    from ..pqf.semantic import evaluator as _ev
    return {
        "status": "ok",
        "framework_version": getattr(config, "SPEC_VERSION", "1.3"),
        "release": _RELEASE,
        "semantic_model": getattr(config, "GEMINI_MODEL", "unknown"),
        "last_model_version": _ev.LAST_MODEL_VERSION,
        "tier": getattr(config, "GEMINI_TIER", ""),
        "semantic_mode": _semantic_mode(),
        "metrics": __import__("backend.pqf.technical", fromlist=["metric_status"]).metric_status(),
        "fqs_alpha": config.FQS_ALPHA,
        "fqs_beta": config.FQS_BETA,
        "fqs_pass_threshold": config.FQS_PASS_THRESHOLD,
        "video_ready": ffmpeg_available(),
        "music_tracks": _music_tracks,
        "test_tones": _test_tones,
    }


@app.get("/criteria")
def criteria():
    """The criteria in force, so the client never hard codes them."""
    return {
        "technical": [
            {"name": k, "weight": w,
             "pass_threshold": config.TQS_PASS_THRESHOLDS.get(k)}
            for k, w in config.TQS_WEIGHTS.items()
        ],
        "semantic": [
            {"name": k, "weight": w,
             "pass_threshold": config.SQS_PASS_THRESHOLDS.get(k)}
            for k, w in config.SQS_WEIGHTS.items()
        ],
        "combination": {
            "alpha": config.FQS_ALPHA,
            "beta": config.FQS_BETA,
            "pass_threshold": config.FQS_PASS_THRESHOLD,
        },
        "roles": config.ROLE_RULES,
        "role_priority": config.ROLE_PRIORITY,
    }


@app.post("/score", response_model=ScoreResponse)
def score(file: UploadFile = File(...)):
    """Full framework evaluation of one image. Costs one semantic model call."""
    t0 = time.time()
    data = _platform_format(_read_upload(file))
    d = score_image(data, path=file.filename, mime=file.content_type)
    technical, semantic, feedback = _shape(d)
    return ScoreResponse(
        tqs=round(d.tqs, 3), sqs=round(d.sqs, 3), fqs=round(d.fqs, 3),
        role=d.role, passed=d.passed, hard_rejected=d.hard_rejected,
        reason=d.reason, technical=technical, semantic=semantic,
        feedback=feedback, elapsed_ms=int((time.time() - t0) * 1000),
        model_version=getattr(d, "model_version", "") or "",
        tier=config.GEMINI_TIER,
    )


@app.post("/guidance", response_model=GuidanceResponse)
def guidance(file: UploadFile = File(...),
             shot: str = Form("main"),
             rotation: int = Form(0)):
    """Fast pre capture check. Cheap deterministic criteria only.

    Runs sharpness, exposure and background, which are the faults a user can
    correct while still holding the camera. It never calls the semantic model,
    so it is fast and free, and it is the endpoint the live viewfinder uses.

    The frame is analysed at a reduced working size, because live guidance needs
    speed rather than the precision required for a scoring decision. Scores from
    this endpoint are indicative and are never used for certification. The full
    /score endpoint at the standard working resolution makes that decision.
    """
    t0 = time.time()
    data = _read_upload(file)

    import numpy as np
    import cv2
    from ..pqf import technical as T

    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Could not decode the image.")

    # Upright the frame if the client sends it in sensor orientation.
    rot = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
           270: cv2.ROTATE_90_COUNTERCLOCKWISE}.get(int(rotation) % 360)
    if rot is not None:
        img = cv2.rotate(img, rot)

    # Check only the region that will be scored. The captured photo is centre
    # cropped to 4:5 before scoring, so the strips above and below are thrown
    # away; judging them made a well placed product read as cut off and the
    # background as dirty whenever the room showed at the top or bottom.
    img = _crop_to_platform(img)
    shot = shot if shot in GUIDANCE_SHOT_FRAMING else "main"
    min_area, max_area, allow_edges = GUIDANCE_SHOT_FRAMING[shot]

    # Reduced working size for live use. Sharpness is resolution dependent, so
    # the threshold below is deliberately lower than the scoring threshold.
    h, w = img.shape[:2]
    longest = max(h, w)
    if longest > GUIDANCE_LONGEST_SIDE:
        s = GUIDANCE_LONGEST_SIDE / longest
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)

    checks = []
    for name, fn, thr in (("sharpness", T.t1_sharpness, GUIDANCE_SHARPNESS_MIN),
                          ("exposure", T.t2_exposure, GUIDANCE_PASS_MIN),
                          ("background", T.t3_background, GUIDANCE_PASS_MIN)):
        s = float(fn(img))
        # A detail close up has no background to speak of, so background is
        # reported but does not block a detail shot in live guidance.
        ok = True if (shot == "detail" and name == "background") else s >= thr
        checks.append(CriterionScore(name=name, score=round(s, 3),
                                     weight=config.TQS_WEIGHTS[name],
                                     passed=ok))

    # Framing. Without this, a badly composed shot shows three green lights,
    # because the other three criteria say nothing about where the product sits
    # or how much of the frame it fills. Composition is scored properly by the
    # semantic criterion after capture. This is a cheap deterministic proxy for
    # live use only, computed from the same product region the technical
    # criteria already use, so it introduces no new criterion to the framework.
    framing_info = {}
    framing_score, framing_msg = _framing_check(img, T, min_area, max_area, allow_edges,
                                                framing_info)
    zoom_hint = _zoom_hint(framing_info, shot, min_area, max_area)
    checks.append(CriterionScore(name="framing", score=round(framing_score, 3),
                                 weight=0.0,
                                 passed=framing_score >= GUIDANCE_PASS_MIN))

    exposure_hint = 0
    bg_failed = any(c.name == "background" and c.passed is False for c in checks)
    bg_grey = bg_failed and _background_diagnosis(img) == "grey"
    exp = next((c for c in checks if c.name == "exposure"), None)
    if bg_grey and (exp is None or exp.score >= GUIDANCE_PASS_MIN):
        exposure_hint = 1     # brighten, product exposure allows it
    elif exp is not None and exp.passed is False:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        exposure_hint = 1 if float(gray.mean()) < config.T2_IDEAL_LOW else -1

    feedback = []
    for c in checks:
        if c.passed is False:
            if c.name == "framing" and framing_msg:
                feedback.append(framing_msg)
            elif c.name == "background" and bg_grey:
                feedback.append(GREY_BACKGROUND_MSG)
            elif c.name in FEEDBACK:
                feedback.append(FEEDBACK[c.name])
    return GuidanceResponse(
        ready=all(c.passed for c in checks),
        checks=checks, feedback=feedback,
        elapsed_ms=int((time.time() - t0) * 1000),
        exposure_hint=exposure_hint,
        zoom_hint=zoom_hint,
    )


@app.post("/batch", response_model=BatchResponse)
def batch(files: List[UploadFile] = File(..., media_type="multipart/form-data")):
    """Score a capture batch, select the best set, and run the set level gate."""
    t0 = time.time()
    if not files:
        raise HTTPException(400, "No files received.")
    if len(files) > 24:
        raise HTTPException(413, "Too many images. Send 24 or fewer.")

    payload = [(_platform_format(_read_upload(f)), f.filename or f"image_{i}")
               for i, f in enumerate(files)]
    result = process_batch(payload)

    index_of = {id(d): i for i, d in enumerate(result.all_decisions)}

    def _weakest(d) -> str:
        """The single lowest scoring criterion, which is what to fix first.

        A hard-rejected image has no semantic scores, so its weakest criterion
        is the lowest TECHNICAL one. This must never be empty for such an image:
        a rejected photo with no reason is exactly the one the user most needs
        explained, which is why it previously showed only "Retake this one"
        (fixed 2026-10-05).
        """
        from .batch_explain import weakest_technical
        tech = dict(getattr(d, "technical_scores", {}) or {})
        sem = dict(d.semantic_scores or {})
        # For a hard reject use the technical scores alone, by largest shortfall below
        # each criterion's pass threshold (v1.4.0); otherwise the lowest score of the
        # combined set. A weight 0 criterion (T4) is never named: it gives no feedback.
        if getattr(d, "hard_rejected", False) and tech:
            return weakest_technical(tech)
        scores = {**{k: v for k, v in tech.items()
                     if config.TQS_WEIGHTS.get(k, 0.0) > 0.0}, **sem}
        if not scores:
            return weakest_technical(tech)
        return min(scores.items(), key=lambda kv: kv[1])[0]

    # Report every image, not only the selected ones. An image that was left out
    # is exactly the one the user most wants explained.
    selected = [
        BatchImageResult(
            index=i,
            fqs=round(d.fqs, 3),
            tqs=round(d.tqs, 3),
            sqs=round(d.sqs, 3),
            role=d.role,
            passed=d.passed,
            reason=d.reason,
            weakest=_weakest(d),
        )
        for i, d in enumerate(result.all_decisions)
    ]
    role_sets = {
        role: [getattr(d, "path", "") for d in items]
        for role, items in result.role_sets.items()
    }
    from .batch_explain import explain_batch
    _extra = explain_batch(result, FEEDBACK, config.SQS_PASS_THRESHOLDS)
    # From the first image that reached the semantic model (v1.4.0-rc).
    _mv = next((getattr(d, "model_version", "") for d in result.all_decisions
                if getattr(d, "model_version", "")), "")
    return BatchResponse(images=_extra["images"], missing=_extra["missing"],

        certified=result.certified, selected=selected, role_sets=role_sets,
        recapture=result.recapture, elapsed_ms=int((time.time() - t0) * 1000),
        model_version=_mv, tier=config.GEMINI_TIER,
    )

# ---------------------------------------------------------------------------
# Test page
# ---------------------------------------------------------------------------
_TEST_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>PQF test</title>
<style>
 body{font-family:system-ui,Segoe UI,Arial;margin:0;background:#f5f7fa;color:#1f2430}
 .wrap{max-width:860px;margin:0 auto;padding:28px 20px 60px}
 h1{color:#1F3A63;margin:0 0 4px;font-size:24px}
 p.sub{color:#5a6472;margin:0 0 26px}
 .card{background:#fff;border:1px solid #dfe4ec;border-radius:12px;padding:20px;margin-bottom:18px}
 h2{font-size:17px;margin:0 0 6px;color:#2E5090}
 .hint{color:#6b7482;font-size:13.5px;margin:0 0 14px}
 input[type=file]{display:block;margin:10px 0 14px;width:100%}
 button{background:#1F3A63;color:#fff;border:0;border-radius:8px;padding:11px 20px;font-size:15px;cursor:pointer}
 button:disabled{background:#9aa4b3;cursor:default}
 pre{background:#0f1720;color:#d7e2f0;padding:14px;border-radius:8px;overflow:auto;font-size:12.5px;max-height:420px}
 .verdict{padding:12px 14px;border-radius:8px;margin:12px 0;font-weight:600}
 .ok{background:#EAF4EC;color:#1B5E20;border:1px solid #2E7D32}
 .no{background:#FFF6E5;color:#7a5600;border:1px solid #B8860B}
 .roles{display:flex;gap:10px;flex-wrap:wrap;margin-top:10px}
 .role{background:#eef3fa;border:1px solid #cdd9ea;border-radius:8px;padding:8px 12px;font-size:13.5px}
</style></head><body><div class="wrap">
<h1>PQF test page</h1>
<p class="sub">Swagger cannot render a multi file picker for this API, so use this instead.</p>

<div class="card">
  <h2>Single image</h2>
  <p class="hint">Full framework evaluation. Costs one semantic model call.</p>
  <input type="file" id="one" accept="image/*">
  <button onclick="score()">Score this image</button>
  <div id="oneOut"></div>
</div>

<div class="card">
  <h2>Guidance only</h2>
  <p class="hint">The fast pre capture check. No semantic call, so this is free.</p>
  <input type="file" id="g" accept="image/*">
  <button onclick="guide()">Check</button>
  <div id="gOut"></div>
</div>

<div class="card">
  <h2>Batch, the quality gate</h2>
  <p class="hint">Select several images at once, hold Ctrl or Shift in the picker.
  Each image costs one semantic call. Try four varied shots, then four near
  identical close ups to see the gate fail.</p>
  <input type="file" id="many" accept="image/*" multiple>
  <button onclick="batch()">Score the set</button>
  <div id="manyOut"></div>
</div>
</div>
<script>
async function post(url, form, outId, render){
  const el = document.getElementById(outId);
  el.innerHTML = '<p class="hint">Working...</p>';
  try{
    const r = await fetch(url, {method:'POST', body:form});
    const j = await r.json();
    el.innerHTML = (render ? render(j) : '') + '<pre>'+JSON.stringify(j,null,2)+'</pre>';
  }catch(e){ el.innerHTML = '<pre>'+e+'</pre>'; }
}
function score(){
  const f=document.getElementById('one').files[0]; if(!f) return;
  const fd=new FormData(); fd.append('file',f);
  post('/score',fd,'oneOut', j=>{
    const cls = j.passed ? 'ok':'no';
    return `<div class="verdict ${cls}">FQS ${j.fqs} &middot; role ${j.role} &middot; ${j.passed?'passed':'not passed'}</div>`;
  });
}
function guide(){
  const f=document.getElementById('g').files[0]; if(!f) return;
  const fd=new FormData(); fd.append('file',f);
  post('/guidance',fd,'gOut', j=>{
    const cls = j.ready ? 'ok':'no';
    const fb = j.feedback.length ? ' &middot; '+j.feedback[0] : '';
    return `<div class="verdict ${cls}">${j.ready?'Ready':'Not ready'}${fb}</div>`;
  });
}
function batch(){
  const fs=document.getElementById('many').files; if(!fs.length) return;
  const fd=new FormData(); for(const f of fs) fd.append('files',f);
  post('/batch',fd,'manyOut', j=>{
    const cls = j.certified ? 'ok':'no';
    let head = j.certified ? 'Set certified' :
      ('Not certified &middot; ' + (j.recapture?.instruction || ''));
    let roles = '';
    if(j.role_sets){
      const bits = Object.entries(j.role_sets)
        .filter(([k,v])=>v.length)
        .map(([k,v])=>`<div class="role"><b>${k}</b><br>${v.length} image(s)</div>`);
      if(bits.length) roles = '<div class="roles">'+bits.join('')+'</div>';
    }
    return `<div class="verdict ${cls}">${head}</div>`+roles;
  });
}
</script></body></html>"""


@app.get("/test", response_class=HTMLResponse)
def test_page():
    """A small page for exercising the endpoints, including multi file upload.

    Swagger UI renders an OpenAPI 3.1 binary array as a text field rather than a
    file picker, so the batch endpoint cannot be tested from /docs. This page
    provides a working multi file picker and shows the verdict clearly.
    """
    return _TEST_PAGE

# ---------------------------------------------------------------------------
# Video, Layer 3
# ---------------------------------------------------------------------------
@app.get("/music")
def music(category: str | None = None):
    """Recommend an audio mood and list the tracks available.

    The framework recommends and explains. The owner chooses. It never selects
    music automatically, because an automatically decided correct track is a
    subjective judgement with no ground truth to validate against, and because
    attaching arbitrary music to publishable content raises licensing exposure.
    """
    from pathlib import Path
    from ..video import audio as A

    base = Path(__file__).resolve().parents[2]
    rec = A.recommend(category, base)
    return {
        "recommended_mood": rec.mood,
        "reason": rec.reason,
        "mood_descriptions": A.MOODS,
        "tracks": [
            {"id": t.id, "title": t.title, "mood": t.mood,
             "recommended": t.mood == rec.mood, "attribution": t.attribution}
            for t in rec.tracks
        ],
        "note": "Audio is recommended as audience appropriate. No claim is made "
                "that it is optimal or that it will improve sales.",
    }


@app.get("/music/preview/{track_id}")
def music_preview(track_id: str):
    """Stream one track so the owner can HEAR it before choosing (2026-10-05).

    The owner confirms the music, so they must be able to listen first.
    Unknown or missing tracks are a 404, never a silent substitute.
    """
    from pathlib import Path
    from ..video import audio as A
    base = Path(__file__).resolve().parents[2]
    path = A.resolve_track(track_id, base)
    if path is None:
        raise HTTPException(404, "That music track is not available.")
    return FileResponse(path=str(path), media_type="audio/mpeg",
                        filename=path.name)


@app.post("/video")
def video(
    files: List[UploadFile] = File(...),
    roles: str = Form(""),
    format: str = Form("square"),
    track_id: str = Form(""),
    motion: bool = Form(True),
):
    """Assemble certified images into a marketing video.

    Images are ordered by role, meaning the main shot leads, angles follow, and
    the detail shot comes late. That order is decided by the framework's role
    classifier, so the structure of the video follows from the standard rather
    than from upload order.

    No video content is generated. Every frame derives from a photograph the
    framework certified, which is what keeps the quality guarantee meaningful
    through to the final output.
    """
    import tempfile
    from pathlib import Path
    from ..video import audio as A
    from ..video.builder import build_video, ffmpeg_available, ROLE_ORDER

    if not ffmpeg_available():
        raise HTTPException(
            503, "Video assembly is unavailable because ffmpeg is not installed.")
    if not files:
        raise HTTPException(400, "No images received.")
    if len(files) > 8:
        raise HTTPException(413, "Too many images. Send eight or fewer.")

    base = Path(__file__).resolve().parents[2]
    tmp = Path(tempfile.mkdtemp(prefix="pqf_video_"))

    role_list = [r.strip() for r in roles.split(",")] if roles else []
    saved = []
    for i, f in enumerate(files):
        data = _read_upload(f)
        p = tmp / f"img_{i:02d}.jpg"
        p.write_bytes(data)
        role = role_list[i] if i < len(role_list) else "hero_shot"
        saved.append((role, p))

    # Order by role. Anything with an unrecognised role goes last rather than
    # being discarded, since dropping a user's image without saying so would be
    # worse than including it.
    ordered = []
    for role in ROLE_ORDER:
        ordered += [p for r, p in saved if r == role]
    ordered += [p for r, p in saved if r not in ROLE_ORDER]

    if not ordered:
        raise HTTPException(400, "No usable images after ordering.")

    audio_path = A.resolve_track(track_id, base) if track_id else None
    if track_id and audio_path is None:
        # Never return a silent video when music was chosen (2026-10-05).
        raise HTTPException(
            404, "That music track is not available. Choose another track.")
    out = tmp / "marketing_video.mp4"

    try:
        result = build_video(
            ordered, out,
            format_name=format if format in ("square", "vertical") else "square",
            audio_path=audio_path,
            motion=motion,
        )
    except RuntimeError as e:
        raise HTTPException(500, str(e))

    return FileResponse(
        path=str(result.path),
        media_type="video/mp4",
        filename="marketing_video.mp4",
        headers={
            "X-Video-Duration": str(result.duration_seconds),
            "X-Video-Images": str(result.image_count),
            "X-Video-Format": result.format_name,
            "X-Video-Audio": "1" if result.has_audio else "0",
        },
    )

# Automatic marketing video: /video/plan, /video/render (2026-10-06).
from .video_api import router as video_router  # noqa: E402
app.include_router(video_router)

# Study sessions for the evaluation: POST /study/log (v1.1.0).
from .study_api import router as study_router  # noqa: E402
app.include_router(study_router)
