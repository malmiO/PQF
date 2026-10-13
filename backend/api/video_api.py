"""
video_api.py  -  the automatic marketing video, two calls, no approval step (2026-10-06).

  POST /video/plan     certified photos + the product form  ->  the plan (JSON):
                       shot order, the owner's text, feature callouts, music,
                       post caption, content checklist, and a plan_id.
  POST /video/render   plan_id  ->  the MP4, rendered from that plan.
  GET  /video/plan/{plan_id}  the saved plan, for the results the app keeps.

Photos are uploaded once (with /video/plan) and kept on the server under the plan
id for a few hours, so /video/render does not upload them again.
Mounted in main.py with: app.include_router(video_router)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

router = APIRouter()

SESSIONS = Path(tempfile.gettempdir()) / "pqf_video_sessions"
KEEP_HOURS = 3
MAX_IMAGES = 6
_ID = re.compile(r"^[0-9a-f]{32}$")
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
DEFAULT_BRAND = "#1F3A63"


def _base() -> Path:
    return Path(__file__).resolve().parents[2]


def _ffmpeg():
    try:
        from ..video.builder import ffmpeg_binary
        return ffmpeg_binary()
    except Exception:
        return shutil.which("ffmpeg")


def _cleanup():
    if not SESSIONS.exists():
        return
    cutoff = time.time() - KEEP_HOURS * 3600
    for d in SESSIONS.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


# How often the background sweep runs. The 3-hour retention (KEEP_HOURS) is the
# promise; this sweep makes it real even when no new /video request ever arrives
# to trigger the lazy _cleanup() inside /video/plan and /video/render.
SWEEP_INTERVAL_SECONDS = 600  # 10 minutes


async def _sweep_loop():
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        try:
            _cleanup()
        except Exception:  # never let the sweep die on a transient FS error
            logging.getLogger("pqf.video").exception("video session sweep failed")


def start_session_sweeper() -> asyncio.Task:
    """Delete stale video sessions on a timer, independent of request traffic.

    Runs _cleanup() ONCE immediately, then every SWEEP_INTERVAL_SECONDS, so a
    session older than KEEP_HOURS is removed within ~10 minutes of expiry even
    if the server receives no further /video calls. Returns the background task
    so the caller (app startup) can keep a reference / cancel it on shutdown.
    """
    _cleanup()  # once at startup
    return asyncio.create_task(_sweep_loop())


def _session(plan_id: str) -> Path:
    if not _ID.match(plan_id or ""):
        raise HTTPException(400, "Invalid plan id.")
    d = SESSIONS / plan_id
    if not (d / "plan.json").exists():
        raise HTTPException(404, "That video plan has expired. Make the video again.")
    return d


def _music(mood: str, category: str) -> dict:
    """The owner's mood (or the category's recommended one) and the INSTALLED
    track of that mood whose bpm is closest to the mood's pace (v1.1.0; was the
    first listed). No track of that mood: no music, never a mismatched mood (the
    pace follows the mood, so the two must agree)."""
    from ..video import audio as A
    rec = A.recommend(category, _base())
    mood = mood or rec.mood
    track = next((t for t in rec.tracks if t.mood == mood), None)
    return {"mood": mood,
            "recommended_mood": rec.mood,
            "reason": rec.reason if mood == rec.mood else "Chosen by you in the product form.",
            "track_id": track.id if track else None,
            "title": track.title if track else "",
            "artist": track.artist if track else "",
            "licence": track.licence if track else "",
            "source_url": track.source_url if track else "",
            "bpm": track.bpm if track else None,
            "attribution": track.attribution if track else ""}


def _guard_callouts(data: bytes, features: list, located: dict | None, fmt: str):
    """Step 3 (v1.1.0): if the located points would make a bad callout layout,
    drop them all, so every feature is shown as a caption. Returns (located, guard)."""
    import logging
    import cv2
    import numpy as np
    from ..video.promo import callout_guard, FORMATS
    pts = (located or {}).get("points") or []
    callouts = [{"label": f, "x": p[0], "y": p[1]} for f, p in zip(features, pts) if p]
    if not callouts:
        return located, {"ok": True, "rule": "", "detail": "no callouts"}
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return located, {"ok": True, "rule": "", "detail": "image not decoded"}
    guard = callout_guard(img, callouts, fmt if fmt in FORMATS else "vertical")
    if not guard["ok"]:
        logging.getLogger("pqf.video").warning("callout guard rule %s: %s",
                                               guard["rule"], guard["detail"])
        located = {**located, "points": [None] * len(pts)}
    return located, guard


@router.post("/video/plan")
def video_plan(
    files: List[UploadFile] = File(...),
    roles: str = Form(...),               # comma separated, one per file
    product_name: str = Form(""),
    price: str = Form(""),
    features: str = Form(""),             # up to three, one per line
    category: str = Form(""),
    mood: str = Form(""),                 # calm | elegant | upbeat; empty = recommended
    format: str = Form("vertical"),
    shop: str = Form(""),                 # from the business profile, when it exists
    contact: str = Form(""),
    brand_colour: str = Form(""),         # business profile colour, "#RRGGBB" (v1.1.0)
):
    """Plan the video from the CERTIFIED set and the owner's product form."""
    from .main import _platform_format, _read_upload
    from ..video.plan import build_plan, ProductInfo
    from ..video.features import locate_features

    if not files:
        raise HTTPException(400, "No images received.")
    if len(files) > MAX_IMAGES:
        raise HTTPException(413, f"Send at most {MAX_IMAGES} images, the certified set.")
    role_list = [r.strip() for r in roles.split(",")]
    if len(role_list) != len(files):
        raise HTTPException(400, "Send one role per image.")

    _cleanup()
    plan_id = uuid.uuid4().hex
    d = SESSIONS / plan_id
    d.mkdir(parents=True, exist_ok=True)
    datas = []
    for i, f in enumerate(files):
        # The same 4:5 region /batch scored (v1.1.0). The raw upload is taller,
        # and its strips outside the scored region (the light box's edges) showed
        # up in the video as a dark smear below a small product (J6+, 2026-10-06).
        data = _platform_format(_read_upload(f))
        (d / f"img_{i:02d}.img").write_bytes(data)
        datas.append(data)

    info = ProductInfo(name=product_name, price=price,
                       features=[x for x in features.splitlines() if x.strip()],
                       category=category, mood=mood, shop=shop, contact=contact).clean()
    images = list(zip(role_list, range(len(files))))
    feat_idx = next((i for r, i in images if r == "detail_shot"),
                    next((i for r, i in images if r == "hero_shot"), 0))
    data = datas[feat_idx]
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    located = locate_features(data, info.features, mime) if info.features else None
    located, guard = _guard_callouts(data, info.features, located, format)

    plan = build_plan(images, info, format, located, _music(info.mood, info.category))
    plan["callout_guard"] = guard
    plan["brand_colour"] = brand_colour if HEX.match(brand_colour or "") else DEFAULT_BRAND
    plan["plan_id"] = plan_id
    (d / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    return plan


@router.get("/video/plan/{plan_id}")
def get_plan(plan_id: str):
    return json.loads((_session(plan_id) / "plan.json").read_text(encoding="utf-8"))


@router.post("/video/render")
def video_render(plan_id: str = Form(...), brand_colour: str = Form("")):
    """Render the MP4 from a saved plan. No input from the owner is needed."""
    from ..video import audio as A
    from ..video.promo import render_plan

    d = _session(plan_id)
    ff = _ffmpeg()
    if not ff:
        raise HTTPException(
            503, "Video assembly is unavailable because ffmpeg is not installed.")
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    paths = sorted(d.glob("img_*.img"))
    if any(not (0 <= s["image"] < len(paths)) for s in plan["shots"]):
        raise HTTPException(400, "The plan refers to a photo that was not uploaded.")

    track_id = (plan.get("music") or {}).get("track_id")
    audio_path = A.resolve_track(track_id, _base()) if track_id else None
    if track_id and audio_path is None:
        raise HTTPException(404, "The planned music track is no longer installed.")

    out = d / "promo_video.mp4"
    try:
        r = render_plan(plan, paths, out, audio_path=audio_path,
                        brand_colour=brand_colour if HEX.match(brand_colour or "")
                        else plan.get("brand_colour", DEFAULT_BRAND), ffmpeg_bin=ff)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    # Step 4 (v1.1.0): the checklist is MEASURED from the finished file and saved
    # with the plan; the app reads it with GET /video/plan/{plan_id}.
    if r.record:
        from ..video.measure import checklist as measured_checklist, measure_video
        plan["render"] = r.record
        try:
            m = measure_video(r.path, r.record, ff)
            plan["render"]["measurement"] = m
            plan["checklist"] = measured_checklist(plan, r.record, m)
            plan["checklist_source"] = "measured"
        except Exception as e:                  # never lose the video over a measurement
            plan["checklist_source"] = f"declared (measurement failed: {str(e)[:120]})"
        (d / "plan.json").write_text(json.dumps(plan, indent=1), encoding="utf-8")
    met = sum(1 for c in plan.get("checklist", []) if c.get("met"))
    return FileResponse(
        path=str(r.path), media_type="video/mp4", filename="promo_video.mp4",
        headers={"X-Video-Duration": str(r.duration_seconds),
                 "X-Video-Images": str(r.image_count),
                 "X-Video-Format": r.format_name,
                 "X-Video-Audio": "1" if r.has_audio else "0",
                 "X-Video-Mood": r.mood,
                 "X-Video-Checklist": f"{met}/{len(plan.get('checklist', []))}",
                 "X-Video-Checklist-Source": plan.get("checklist_source", "declared")[:40],
                 "X-Plan-Id": plan_id})
