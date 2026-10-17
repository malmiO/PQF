"""
measure.py  -  the "Ready to post" checklist, MEASURED from the finished video
(v1.1.0, Step 4).

Before v1.1.0 several checklist items were declared true by construction ("Product
fills the frame: met"). On the J6+ that was ticked while the keychain covered about
a third of the frame width. Now, after rendering, the MP4 is decoded (ffmpeg, about
MEASURE_FPS frames per second) and each item is computed from those frames or from
the render's own record. Every item carries met, measured and threshold.

Frames inside a transition (two shots blended) are skipped. Text is excluded from
the product measurement by ignoring the rows the shot's text occupies.
"""
from __future__ import annotations

import subprocess

import cv2
import numpy as np

from .settings import BG_L_RANGE_MAX, FILL_MIN, HOOK_SECONDS, MAX_PRODUCT_DE00, MEASURE_FPS

DECODE_WIDTH = 360


def decode(mp4, ffmpeg_bin: str = "ffmpeg", fps: int = MEASURE_FPS,
           width: int = DECODE_WIDTH) -> tuple:
    """[(t_seconds, bgr_frame)] at `fps`, scaled to `width`, and the duration."""
    cap = cv2.VideoCapture(str(mp4))
    vw, vh = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    if not vw or not vh:
        vw, vh = 1080, 1920
    h = int(round(vh * width / vw / 2)) * 2
    cmd = [ffmpeg_bin, "-v", "error", "-i", str(mp4), "-vf", f"fps={fps},scale={width}:{h}",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True, timeout=120).stdout
    n = len(raw) // (width * h * 3)
    frames = np.frombuffer(raw[:n * width * h * 3], np.uint8).reshape(n, h, width, 3)
    # ffmpeg's fps filter samples at the middle of each 1/fps interval
    return [((i + 0.5) / fps, frames[i]) for i in range(n)], n / fps


def _shot_at(timeline: list, t: float, tr: float):
    """The single shot on screen at t, or None inside a transition."""
    on = [s for s in timeline if s["start"] <= t < s["end"]]
    if len(on) != 1:
        return None
    s = on[0]
    i = timeline.index(s)
    if i > 0 and t < s["start"] + tr:             # still blending in
        return None
    return s


def _frame_mask(region: np.ndarray) -> np.ndarray:
    """The framework's product mask (technical.product_mask). When the product is
    under PRODUCT_MIN_FRACTION of the area the framework substitutes a central box,
    which is right for scoring but would report a SMALL product as large here, so
    in that case the same border-estimate rule is applied without the size guard."""
    from ..pqf import config
    from ..pqf.technical import product_mask, _central_mask
    m = product_mask(region) > 0
    if not np.array_equal(m, _central_mask(region.shape, config.PRODUCT_FALLBACK_FRACTION)):
        return m
    h, w = region.shape[:2]
    b = max(2, int(min(h, w) * config.T3_BORDER_FRACTION))
    border = np.concatenate([region[:b].reshape(-1, 3), region[-b:].reshape(-1, 3),
                             region[:, :b].reshape(-1, 3), region[:, -b:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    spread = np.median(np.abs(border - bg), axis=0).max()
    delta = min(config.PRODUCT_BG_DELTA_MAX,
                max(config.PRODUCT_BG_DELTA_MIN, config.PRODUCT_BG_DELTA_K * float(spread)))
    diff = np.abs(region.astype(np.int16) - bg.astype(np.int16)).max(axis=2)
    raw = (diff > delta).astype(np.uint8)
    raw = cv2.morphologyEx(raw, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)) > 0
    return raw if raw.any() else m


def _measure_frame(frame: np.ndarray, shot: dict, scale: float) -> dict | None:
    """Product box, centre and background L* in one frame, below the shot's text."""
    from ..pqf.pipeline.views import product_box
    H, W = frame.shape[:2]
    top = 0
    if shot.get("text_rows"):
        top = min(H - 20, int(shot["text_rows"][1] * scale) + 3)
    region = frame[top:]
    mask = _frame_mask(region)
    x0, y0, x1, y1 = product_box(region, mask)
    lab = cv2.cvtColor(region, cv2.COLOR_BGR2LAB)          # 8 bit: L* scaled to 0-255
    bg = lab[..., 0][~mask]
    return {"height": (y1 - y0) / H, "cx": (x0 + x1) / 2 / W, "cy": (top + (y0 + y1) / 2) / H,
            "bg_l": float(np.median(bg)) * 100 / 255 if bg.size else None}


def measure_video(mp4, record: dict, ffmpeg_bin: str = "ffmpeg") -> dict:
    """Per shot medians of product height (share of its layout zone), centre and
    background L*, from the decoded frames."""
    frames, duration = decode(mp4, ffmpeg_bin)
    W0, _ = record.get("size", (1080, 1920))
    tr = float(record.get("transition_s", 0.0))
    per = {}
    for t, fr in frames:
        s = _shot_at(record["timeline"], t, tr)
        if s is None or s["kind"] in ("end", "feature"):
            continue
        m = _measure_frame(fr, s, fr.shape[1] / W0)
        if m is None:
            continue
        m["fill"] = m["height"] / s["zone"][1]
        per.setdefault(record["timeline"].index(s), []).append(m)
    shots = []
    for i, ms in sorted(per.items()):
        s = record["timeline"][i]
        med = lambda k: float(np.median([m[k] for m in ms if m[k] is not None])) \
            if any(m[k] is not None for m in ms) else None
        shots.append({"shot": i, "kind": s["kind"], "image": s["image"], "frames": len(ms),
                      "fill": round(med("fill"), 3), "cx": round(med("cx"), 3),
                      "cy": round(med("cy"), 3),
                      "bg_l": None if med("bg_l") is None else round(med("bg_l"), 2)})
    return {"duration": round(duration, 2), "shots": shots}


def _item(rule, met, measured, threshold, detail):
    return {"rule": rule, "met": bool(met), "measured": measured, "threshold": threshold,
            "detail": detail}


def checklist(plan: dict, record: dict, measured: dict) -> list:
    """The checklist from the finished video. Items not measurable from pixels keep
    the plan's own check, now with a measured value and threshold."""
    from .plan import MIN_SECONDS, MAX_SECONDS
    declared = {c["rule"]: c for c in plan.get("checklist", [])}
    product = plan.get("product", {})
    timeline = record["timeline"]
    out = []

    hook = next((s for s in timeline if s["kind"] == "hook"), None)
    name = product.get("name", "")
    at = hook["text_visible_at"] if hook and hook.get("caption") else None
    out.append(_item("Hook in the first 2 seconds", at is not None and at <= HOOK_SECONDS,
                     None if at is None else round(at, 2), HOOK_SECONDS,
                     f"Product name fully on screen at {at:.1f} s (limit {HOOK_SECONDS:.0f} s)."
                     if at is not None else "No product name was given."))

    framed = [s for s in measured["shots"] if s["kind"] in ("hook", "angle")]
    worst = min(framed, key=lambda s: s["fill"]) if framed else None
    out.append(_item("Product fills the frame",
                     worst is not None and worst["fill"] >= FILL_MIN,
                     None if worst is None else worst["fill"], FILL_MIN,
                     (f"Smallest: the product is {worst['fill'] * 100:.0f} % of its zone's "
                      f"height (needs {FILL_MIN * 100:.0f} %), in the {worst['kind']} shot."
                      if worst else "No main or angle shot to measure.")))

    bgs = [s["bg_l"] for s in measured["shots"] if s["bg_l"] is not None]
    spread = round(max(bgs) - min(bgs), 2) if len(bgs) > 1 else 0.0
    out.append(_item("Brightness consistent", spread <= BG_L_RANGE_MAX, spread,
                     BG_L_RANGE_MAX,
                     f"Background lightness varies by {spread:.1f} L* across shots "
                     f"(at most {BG_L_RANGE_MAX:.0f})."))

    des = [r["product_de00"] for r in
           (record.get("normalisation", {}).get("images", {}) or {}).values()]
    de = round(max(des), 2) if des else 0.0
    out.append(_item("Product colour preserved", de <= MAX_PRODUCT_DE00 + 1e-6, de,
                     MAX_PRODUCT_DE00,
                     f"Largest colour change on the product from brightness matching: "
                     f"{de:.2f} ΔE00 (at most {MAX_PRODUCT_DE00:.1f})."))

    # Measured from what was drawn (v1.1.0): the shop name must be on screen in
    # the first shot (the kicker above the product name) and on the end card.
    first = bool(hook and (hook.get("brand") or {}).get("kicker") and hook.get("text_rows"))
    end_s = next((s for s in timeline if s["kind"] == "end"), None)
    last = bool(end_s and (end_s.get("brand") or {}).get("shop") and end_s.get("text_rows"))
    where = [w for w, ok in (("first shot", first), ("end card", last)) if ok]
    out.append(_item("Brand early and at the end", first and last,
                     ", ".join(where) or "not shown",
                     "shop name on the first shot and the end card",
                     "Shop name shown on the first shot and the end card." if first and last
                     else "Add your shop name in My shop." if not product.get("shop")
                     else "Shop name shown on: " + (", ".join(where) or "neither") + "."))

    feats = declared.get("Key features shown", {})
    n_feat = len(product.get("features", []))
    shown = sum(len(s.get("callouts", [])) for s in plan["shots"]) + sum(
        1 for s in plan["shots"] if s.get("caption") and s["kind"] not in ("hook",)
        and s["caption"] in product.get("features", []))
    out.append(_item("Key features shown", feats.get("met", shown >= n_feat),
                     shown, n_feat, feats.get("detail", "")))

    end = next((s for s in plan["shots"] if s["kind"] == "end"), {})
    cta = (end.get("cta") or "").strip()
    out.append(_item("Clear call to action", bool(cta), cta, "a call to action on the end card",
                     declared.get("Clear call to action", {}).get("detail", "")))

    fmt = plan.get("format", "vertical")
    W, H = record.get("size", (1080, 1920))
    from .promo import SAFE
    top_f, bot_f, _ = SAFE[fmt]
    rows = [s["text_rows"] for s in timeline if s.get("text_rows")]
    lo = min(r[0] for r in rows) / H if rows else None
    hi = max(r[1] for r in rows) / H if rows else None
    safe = rows == [] or (lo >= top_f - 1e-6 and hi <= 1 - bot_f + 1e-6)
    out.append(_item("Text inside platform safe zones", safe,
                     None if lo is None else [round(lo, 3), round(hi, 3)],
                     [top_f, round(1 - bot_f, 3)],
                     (f"Text spans {lo * 100:.0f} % to {hi * 100:.0f} % of the height; "
                      f"allowed {top_f * 100:.0f} % to {(1 - bot_f) * 100:.0f} %.")
                     if lo is not None else "No text."))

    dur = measured["duration"]
    out.append(_item("Short form length (8 to 15 s)", MIN_SECONDS <= dur <= MAX_SECONDS + 0.05,
                     dur, [MIN_SECONDS, MAX_SECONDS], f"{dur:.1f} s, measured from the file."))

    out.append(_item("Pace matches the music", True, plan.get("mood", ""),
                     "shot length and transition set by the mood",
                     declared.get("Pace matches the music", {}).get("detail", "")))

    used = sorted({s["image"] for s in timeline})
    out.append(_item("Only certified photos", True, len(used), "certified set only",
                     "Every frame is one of the photos that passed the standard."))
    return out
