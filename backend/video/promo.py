"""
promo.py  -  render the marketing video from an automatic plan (2026-10-06).

Still ASSEMBLY, never generation: every frame is a certified photograph, moved and
captioned, so the quality guarantee survives into the video (decided 2026-09-25).
The plan (plan.py) decides WHAT appears; this module decides HOW it looks.

  * The product is FRAMED, not fitted: views.product_box finds it and each shot is
    cropped around it, so it fills a large part of the frame.
  * Short form structure: hook (main shot, product name, shop), angles (pans), a
    FEATURE SCENE (the detail shot with the owner's key features pointed out by
    animated lines and labels), end card (price, call to action, contact, shop).
  * Owner text only, inside the 9:16 safe zones (top 14 percent, bottom 35 percent
    free of text) and never over the product.
  * Pace matches the music mood (Yang et al., 2025, JTAER): calm slower with fades,
    upbeat faster with slides. Each shot moves differently for visual variation.

No claim is made that the video increases sales. It follows documented guidance.
Text is English only; Sinhala needs complex script shaping and is future work.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FPS = 30
FORMATS = {"vertical": (1080, 1920), "square": (1080, 1080)}

# Safe zones as fractions of height - top and bottom kept free of text; side margin.
SAFE = {"vertical": (0.14, 0.35, 0.06), "square": (0.07, 0.07, 0.07)}

MOOD_STYLE = {
    "calm":    {"pace": 1.25, "transition": "fade",  "trans_s": 0.55},
    "elegant": {"pace": 1.10, "transition": "fade",  "trans_s": 0.50},
    "upbeat":  {"pace": 0.80, "transition": "slide", "trans_s": 0.30},
}
BASE_SECONDS = {"hook": 1.8, "angle": 2.1, "detail": 2.3, "end": 3.0}
FEATURE_BASE, FEATURE_EACH = 1.6, 0.8     # feature scene: time to read each label

# LAYOUT. Text and product never share space. Per format: where the text band
# starts, and per shot kind the product's (centre_y, height fraction).
LAYOUT = {
    "vertical": {"text_top": 0.150, "end_text": 0.440, "text_bottom": 0.645,
                 "label_band": (0.215, 0.645),
                 "hook": (0.54, 0.46), "angle": (0.54, 0.44), "detail": (0.55, 0.56),
                 "feature": (0.43, 0.34), "end": (0.28, 0.26)},
    # text_top was 0.065 and text_bottom 0.935, both outside SAFE's 7 % margins;
    # found by the measured checklist (v1.1.0) and moved inside them
    "square":   {"text_top": 0.075, "end_text": 0.615, "text_bottom": 0.925,
                 "label_band": (0.17, 0.93),
                 "hook": (0.575, 0.62), "angle": (0.575, 0.60), "detail": (0.58, 0.70),
                 "feature": (0.55, 0.60), "end": (0.315, 0.44)},
}
MAX_WIDTH_FILL = 0.86      # product never wider than this share of the frame
FEATURE_WIDTH_FILL = 0.40  # feature scene: room for label columns on both sides
LABEL_COLUMN = 0.235       # width share of each label column
MAX_UPSCALE = 2.4          # never enlarge a photo more than this

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"


@dataclass
class PromoResult:
    path: Path
    duration_seconds: float
    image_count: int
    format_name: str
    has_audio: bool
    mood: str
    # What the renderer did and measured (v1.1.0): brightness matching per image,
    # the timeline of shots, and per shot framing. Saved into the plan.
    record: dict | None = None


# --------------------------------------------------------------------------- framing
def product_box_xywh(img: np.ndarray) -> tuple:
    """(cx, cy, w, h) of the product in full resolution pixels."""
    try:
        from ..pqf.pipeline.views import product_box
        h, w = img.shape[:2]
        k = 1024 / max(h, w)
        small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = (v / k for v in product_box(small))
        return ((x0 + x1) / 2, (y0 + y1) / 2, max(20, x1 - x0), max(20, y1 - y0))
    except Exception:
        h, w = img.shape[:2]
        return (w / 2, h / 2, w * 0.5, h * 0.5)


def _plate(img: np.ndarray, out_w: int, out_h: int, fill_h: float, centre_y: float,
           max_w_fill: float = MAX_WIDTH_FILL, oversample: float = 1.3):
    """Crop around the product so it fills `fill_h` of the frame height (and at most
    `max_w_fill` of its width). Areas outside the photo continue the photo's own
    edges, blurred, with the photo feathered in, so no band or box is visible.
    Returns (plate, to_plate) where to_plate maps photo (x, y) to plate pixels."""
    cx, cy, pw, ph = product_box_xywh(img)
    aspect = out_w / out_h
    crop_h = max(ph / fill_h, (pw / max_w_fill) / aspect)
    crop_h = max(crop_h, out_h / MAX_UPSCALE)
    crop_w = crop_h * aspect
    top = cy - crop_h * centre_y
    left = cx - crop_w / 2
    pad = int(max(crop_w, crop_h)) + 4
    h0, w0 = img.shape[:2]
    ext = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    k = 8
    small = cv2.resize(ext, (ext.shape[1] // k, ext.shape[0] // k), interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (0, 0), sigmaX=max(3, min(small.shape[:2]) / 25))
    big = cv2.resize(small, (ext.shape[1], ext.shape[0]), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    feather = max(8, int(min(h0, w0) * 0.08))
    a = np.ones((h0, w0), np.float32)
    ramp = np.linspace(0.0, 1.0, feather, dtype=np.float32)
    a[:feather] *= ramp[:, None]; a[-feather:] *= ramp[::-1][:, None]
    a[:, :feather] *= ramp[None, :]; a[:, -feather:] *= ramp[::-1][None, :]
    region = big[pad:pad + h0, pad:pad + w0]
    region[:] = img.astype(np.float32) * a[..., None] + region * (1 - a[..., None])
    big = big.astype(np.uint8)
    x0, y0 = int(round(left + pad)), int(round(top + pad))
    ch, cw = int(round(crop_h)), int(round(crop_w))
    crop = big[y0:y0 + ch, x0:x0 + cw]
    W, H = int(out_w * oversample), int(out_h * oversample)
    interp = cv2.INTER_AREA if crop.shape[0] > H else cv2.INTER_LANCZOS4
    plate = cv2.resize(crop, (W, H), interpolation=interp)
    sx, sy = W / cw, H / ch
    to_plate = lambda x, y: ((x + pad - x0) * sx, (y + pad - y0) * sy)
    return plate, to_plate


def _ease(t: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, t)))


def _matrix(plate_wh, out_w, out_h, t, motion, direction, anchor_y) -> np.ndarray:
    W, H = plate_wh
    e = _ease(t)
    base = out_w / W
    if motion == "push":                   # hook: quick push in
        z, dx = 1.0 + 0.08 * e, 0.0
    elif motion == "deep":                 # detail: deeper push in
        z, dx = 1.0 + 0.14 * e, 0.0
    elif motion == "pan":                  # angle: lateral pan with slight zoom
        z, dx = 1.05, (e - 0.5) * 0.05 * direction
    elif motion == "hold":                 # feature scene: almost still, labels readable
        z, dx = 1.0 + 0.03 * e, 0.0
    else:                                  # end card: settle
        z, dx = 1.04 - 0.04 * e, 0.0
    s = base * z
    ax, ay = W / 2, anchor_y * H
    tx = out_w / 2 - s * ax + dx * out_w
    ty = anchor_y * out_h - s * ay
    return np.float32([[s, 0, tx], [0, s, ty]])


def _frame(plate, out_w, out_h, M) -> np.ndarray:
    return cv2.warpAffine(plate, M, (out_w, out_h), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)


# --------------------------------------------------------------------------- text
def _font(weight: str, size: int):
    for name in (f"Poppins-{weight}.ttf", "Poppins-Bold.ttf"):
        p = FONT_DIR / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


def _hex(c: str, default=(31, 58, 99)) -> tuple:
    try:
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _wrap(draw, text, f, max_w):
    """Greedy wrap. Hyphenated words may break after the hyphen."""
    import re
    words, lines, cur = re.findall(r"[^\s-]+-|[^\s]+", text), [], ""
    for w in words:
        trial = (cur + ("" if cur.endswith("-") else " ") + w).strip()
        if draw.textlength(trial, font=f) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _fit_lines(draw, text, font_weight, size, max_w, max_lines=2, min_size=22):
    """Wrap text into at most max_lines, shrinking the font until it fits. If it
    still does not fit at the smallest size, the last line ends with an ellipsis
    (the text is never drawn smaller than min_size)."""
    while size >= min_size:
        f = _font(font_weight, size)
        lines = _wrap(draw, text, f, max_w)
        if len(lines) <= max_lines and all(draw.textlength(l, font=f) <= max_w for l in lines):
            return f, lines
        size -= 2
    f = _font(font_weight, min_size)
    lines = _wrap(draw, text, f, max_w)[:max_lines]
    while lines and draw.textlength(lines[-1] + "...", font=f) > max_w and len(lines[-1]) > 1:
        lines[-1] = lines[-1][:-1]
    lines[-1] = lines[-1].rstrip() + "..."
    return f, lines


def _pill(layer: Image.Image, text: str, cx: int, top: int, max_w: int, size: int,
          weight: str, fg, bg, max_lines=2, min_size=22) -> int:
    """Draw a rounded label centred on cx; returns its bottom y."""
    d = ImageDraw.Draw(layer)
    f, lines = _fit_lines(d, text, weight, size, max_w - 2 * int(size * 0.7), max_lines, min_size)
    lh = int(f.size * 1.25)
    tw = max(d.textlength(l, font=f) for l in lines)
    padx, pady = int(f.size * 0.7), int(f.size * 0.45)
    w, h = int(tw + 2 * padx), int(lh * len(lines) + 2 * pady - (lh - f.size) * 0.6)
    x0 = int(cx - w / 2)
    d.rounded_rectangle([x0, top, x0 + w, top + h],
                        radius=int(h * 0.35 if len(lines) > 1 else h / 2), fill=bg)
    y = top + pady - int(f.size * 0.12)
    for l in lines:
        lw = d.textlength(l, font=f)
        d.text((cx - lw / 2, y), l, font=f, fill=fg)
        y += lh
    return top + h


def _text_layer(shot: dict, fmt: str, size_wh, brand) -> Image.Image | None:
    """The owner's text for one shot, as a transparent layer."""
    W, H = size_wh
    _, _, side = SAFE[fmt]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    max_w = int(W * (1 - 2 * side) * 0.92)
    white, navy = (255, 255, 255, 255), tuple(brand) + (235,)
    y = int(H * LAYOUT[fmt]["text_top"])
    unit = W / 1080
    kind = shot["kind"]
    drew = False
    if kind in ("hook", "angle", "detail"):
        # The text must end above the product zone; if it would not, the block is
        # drawn smaller until it does (a kicker plus a two line name can be tall).
        cy, fill = LAYOUT[fmt][kind]
        limit = int((cy - fill / 2) * H) - int(10 * unit)
        for scale in (1.0, 0.9, 0.8, 0.7, 0.6):
            trial = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            u, y = unit * scale, int(H * LAYOUT[fmt]["text_top"])
            if kind == "hook" and shot.get("kicker"):
                y = _pill(trial, shot["kicker"].upper(), W // 2, y, int(max_w * 0.8),
                          int(30 * u), "Medium", navy[:3] + (255,),
                          (255, 255, 255, 225), 1, 18) + int(10 * u)
                drew = True
            if shot.get("caption"):
                big = kind == "hook"
                y = _pill(trial, shot["caption"], W // 2, y, max_w,
                          int((64 if big else 50) * u), "Bold" if big else "Medium",
                          white, navy, 2, 18)
                drew = True
            layer = trial
            if y <= limit:
                break
    elif kind == "feature" and fmt == "vertical":
        _pill(layer, "Key features", W // 2, y, max_w, int(44 * unit), "Bold", white, navy, 1)
        drew = True
    elif kind == "end":
        limit = int(H * LAYOUT[fmt]["text_bottom"])
        cta = (shot.get("cta") or "") + (" " + shot["contact"] if shot.get("contact") else "")
        for scale in (1.0, 0.9, 0.8, 0.7, 0.6):
            trial = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            y = int(H * LAYOUT[fmt]["end_text"])
            u = unit * scale
            if shot.get("price"):
                y = _pill(trial, shot["price"], W // 2, y, max_w, int(84 * u), "Bold", white, navy, 1)
                y += int(18 * u)
            if cta.strip():
                y = _pill(trial, cta.strip(), W // 2, y, max_w, int(42 * u), "Medium",
                          navy[:3] + (255,), (255, 255, 255, 235), 2)
                y += int(12 * u)
            if shot.get("shop"):
                y = _pill(trial, shot["shop"], W // 2, y, max_w, int(34 * u), "Medium",
                          (70, 70, 70, 255), (255, 255, 255, 215), 1)
            layer = trial
            if y <= limit:
                break
        drew = True
    return layer if drew else None


def _composite(frame_bgr: np.ndarray, layer, alpha: float, lift: float = 0.0,
               at=(0, 0)) -> np.ndarray:
    """Blend an RGBA layer (PIL image) onto the frame at `at` (x, y)."""
    if layer is None or alpha <= 0:
        return frame_bgr
    arr = np.asarray(layer).astype(np.float32)
    if lift:
        arr = np.roll(arr, int(lift), axis=0)
    x, y = at
    h, w = arr.shape[:2]
    H, W = frame_bgr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1:
        return frame_bgr
    sub = arr[y0 - y:y1 - y, x0 - x:x1 - x]
    a = (sub[..., 3:4] / 255.0) * alpha
    out = frame_bgr if frame_bgr.flags.writeable else frame_bgr.copy()
    region = out[y0:y1, x0:x1].astype(np.float32)
    out[y0:y1, x0:x1] = (region * (1 - a) + sub[..., :3][..., ::-1] * a).astype(np.uint8)
    return out


# --------------------------------------------------------------------------- callouts
def _label_image(text: str, max_w: int, size: int, brand) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    f, lines = _fit_lines(probe, text, "Medium", size, max_w - int(size * 1.2), 3, 28)
    lh = int(f.size * 1.22)
    tw = max(probe.textlength(l, font=f) for l in lines)
    padx, pady = int(f.size * 0.6), int(f.size * 0.4)
    w, h = int(tw + 2 * padx), int(lh * len(lines) + 2 * pady - (lh - f.size) * 0.6)
    im = Image.new("RGBA", (w + 4, h + 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([2, 2, w + 1, h + 1], radius=int(min(h / 2, f.size * 0.8)),
                        fill=(255, 255, 255, 240), outline=tuple(brand) + (255,), width=3)
    y = 2 + pady - int(f.size * 0.12)
    for l in lines:
        d.text((2 + padx + (tw - probe.textlength(l, font=f)) / 2, y), l, font=f,
               fill=tuple(brand) + (255,))
        y += lh
    return im


def layout_callouts(callouts: list, points_xy: list, fmt: str, size_wh, brand,
                    product_x=None) -> list:
    """Place each label in the left or right column, at the height of its feature,
    without overlapping and inside the text safe band. Returns a list of dicts
    with the label image, its (x, y), the anchor where the line starts and the
    index of the feature point."""
    W, H = size_wh
    margin = int(W * SAFE[fmt][2] * 0.5)
    col_w = int(W * LABEL_COLUMN)
    if product_x is not None:            # use the space the product leaves free
        free = min(product_x[0], W - product_x[1]) - margin - int(W * 0.03)
        col_w = int(max(W * LABEL_COLUMN, min(W * 0.36, free)))
    band_top, band_bot = (int(H * v) for v in LAYOUT[fmt]["label_band"])
    size = int(40 * W / 1080)
    items = []
    for i, (c, (px, py)) in enumerate(zip(callouts, points_xy)):
        img = _label_image(c["label"], col_w - margin, size, brand)
        items.append({"i": i, "img": img, "side": "left" if px < W / 2 else "right", "py": py})
    # balance: never more than two labels in one column when three exist
    for side, other in (("left", "right"), ("right", "left")):
        same = [it for it in items if it["side"] == side]
        if len(same) > 2:
            far = max(same, key=lambda it: abs(it["py"] - H / 2))
            far["side"] = other
    gap = int(16 * W / 1080)
    for side in ("left", "right"):
        col = sorted([it for it in items if it["side"] == side], key=lambda it: it["py"])
        y = band_top
        for it in col:
            h = it["img"].height
            it["y"] = int(min(max(it["py"] - h / 2, y), band_bot - h))
            y = it["y"] + h + gap
        # push up if the last ones were clamped at the bottom
        y = band_bot
        for it in reversed(col):
            h = it["img"].height
            it["y"] = min(it["y"], y - h)
            y = it["y"] - gap
        for it in col:
            w = it["img"].width
            it["x"] = margin if side == "left" else W - margin - w
            it["anchor"] = (it["x"] + w if side == "left" else it["x"],
                            it["y"] + it["img"].height / 2)
    return items


def _draw_callouts(frame: np.ndarray, items: list, pts: list, local: float, brand) -> np.ndarray:
    bgr = tuple(int(v) for v in brand[::-1])
    for k, it in enumerate(items):
        p = _ease((local - 0.35 - 0.40 * k) / 0.40)
        if p <= 0:
            continue
        ax, ay = it["anchor"]
        px, py = pts[it["i"]]
        ex, ey = ax + (px - ax) * p, ay + (py - ay) * p
        a, b = (int(ax), int(ay)), (int(ex), int(ey))
        cv2.line(frame, a, b, (255, 255, 255), 7, cv2.LINE_AA)
        cv2.line(frame, a, b, bgr, 3, cv2.LINE_AA)
        if p >= 0.98:
            cv2.circle(frame, (int(px), int(py)), 13, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.circle(frame, (int(px), int(py)), 13, bgr, 4, cv2.LINE_AA)
        frame = _composite(frame, it["img"], min(1.0, p * 1.4), 0, (it["x"], int(it["y"])))
    return frame


def feature_geometry(img: np.ndarray, callouts: list, fmt: str, brand=(31, 58, 99)) -> dict:
    """Where the feature scene puts the product, the feature points and the labels.
    Shared by the renderer and by callout_guard, so the guard judges exactly the
    layout that would be drawn. Points are taken at the middle of the scene."""
    W, H = FORMATS[fmt]
    centre_y, fill_h = LAYOUT[fmt]["feature"]
    plate, to_plate = _plate(img, W, H, fill_h, centre_y, FEATURE_WIDTH_FILL)
    ih, iw = img.shape[:2]
    pp = [to_plate(c["x"] * iw, c["y"] * ih) for c in callouts]
    M = _matrix(plate.shape[1::-1], W, H, 0.5, "hold", 1, centre_y)
    mid = [tuple(M @ np.float32([x, y, 1])) for x, y in pp]
    cx, cy, pw, ph = product_box_xywh(img)
    x0, y0 = M @ np.float32([*to_plate(cx - pw / 2, cy - ph / 2), 1])
    x1, y1 = M @ np.float32([*to_plate(cx + pw / 2, cy + ph / 2), 1])
    items = layout_callouts(callouts, mid, fmt, (W, H), brand, product_x=(x0, x1))
    return {"plate": plate, "to_plate": to_plate, "pp": pp, "mid": mid, "items": items,
            "product_box": (float(x0), float(y0), float(x1), float(y1)),
            "photo_box": (cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2)}


def _segments_cross(p1, p2, q1, q2) -> bool:
    """True if segment p1-p2 properly crosses q1-q2."""
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(q1, q2, p1), orient(q1, q2, p2)
    d3, d4 = orient(p1, p2, q1), orient(p1, p2, q2)
    return d1 * d2 < 0 and d3 * d4 < 0


def callout_guard(img: np.ndarray, callouts: list, fmt: str) -> dict:
    """Decide whether the feature scene may use callouts (v1.1.0, Step 3).

    Rejected, so every feature becomes a caption, if ANY of:
      a  two feature points are closer than CALLOUT_MIN_SEPARATION of the photo's
         diagonal (lines converging on one spot, seen on the J6+);
      b  a leader line crosses another leader line in the rendered layout;
      c  a feature point lies outside the product box.
    Returns {"ok", "rule" ("" | "a" | "b" | "c"), "detail"}.
    """
    from .settings import CALLOUT_MIN_SEPARATION
    if not callouts:
        return {"ok": True, "rule": "", "detail": "no callouts"}
    ih, iw = img.shape[:2]
    diag = math.hypot(iw, ih)
    pts = [(c["x"] * iw, c["y"] * ih) for c in callouts]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) / diag
            if d < CALLOUT_MIN_SEPARATION:
                return {"ok": False, "rule": "a",
                        "detail": f"'{callouts[i]['label']}' and '{callouts[j]['label']}' "
                                  f"are {d:.3f} of the photo diagonal apart "
                                  f"(minimum {CALLOUT_MIN_SEPARATION})."}
    g = feature_geometry(img, callouts, fmt)
    bx0, by0, bx1, by1 = g["photo_box"]
    for c, (x, y) in zip(callouts, pts):
        if not (bx0 <= x <= bx1 and by0 <= y <= by1):
            return {"ok": False, "rule": "c",
                    "detail": f"'{c['label']}' is outside the product box."}
    lines = [(it["anchor"], g["mid"][it["i"]], it["i"]) for it in g["items"]]
    for a in range(len(lines)):
        for b in range(a + 1, len(lines)):
            if _segments_cross(lines[a][0], lines[a][1], lines[b][0], lines[b][1]):
                la, lb = callouts[lines[a][2]]["label"], callouts[lines[b][2]]["label"]
                return {"ok": False, "rule": "b",
                        "detail": f"The lines to '{la}' and '{lb}' cross."}
    return {"ok": True, "rule": "", "detail": "callouts are apart, inside the product "
                                              "and their lines do not cross."}


# --------------------------------------------------------------------------- build
MOTION = {"hook": "push", "detail": "deep", "angle": "pan", "feature": "hold", "end": "settle"}


def render_plan(plan: dict, image_paths: list, out_path: Path,
                audio_path: Path | None = None, brand_colour: str = "#1F3A63",
                ffmpeg_bin: str = "ffmpeg") -> PromoResult:
    """Render a plan from plan.build_plan. image_paths[i] is the photo for index i."""
    fmt = plan.get("format", "vertical")
    fmt = fmt if fmt in FORMATS else "vertical"
    W, H = FORMATS[fmt]
    mood = plan.get("mood", "upbeat")
    style = MOOD_STYLE.get(mood, MOOD_STYLE["upbeat"])
    brand = _hex(brand_colour)

    # Read every photo the plan uses, then bring their backgrounds to one
    # lightness (normalize.py). These are in-memory COPIES; the certified files
    # are only read, never written.
    used = sorted({s["image"] for s in plan["shots"]})
    loaded = {i: cv2.imread(str(image_paths[i]), cv2.IMREAD_COLOR) for i in used}
    ok_idx = [i for i in used if loaded[i] is not None]
    if not ok_idx:
        raise RuntimeError("None of the images could be read.")
    hero = next((s["image"] for s in plan["shots"] if s["kind"] == "hook"), ok_idx[0])
    from .normalize import match_set
    fixed, norm_records, norm_target = match_set(
        [loaded[i] for i in ok_idx],
        main_index=ok_idx.index(hero) if hero in ok_idx else 0)
    cache = dict(zip(ok_idx, fixed))
    record = {"normalisation": {"target_bg_l": norm_target,
                                "images": {str(i): r for i, r in zip(ok_idx, norm_records)}}}

    segs, direction = [], 1
    for shot in plan["shots"]:
        kind = shot["kind"]
        idx = shot["image"]
        img = cache.get(idx)
        if img is None:
            continue
        centre_y, fill_h = LAYOUT[fmt][kind]
        if kind == "feature" and shot.get("callouts"):
            g = feature_geometry(img, shot["callouts"], fmt, brand)
            plate = g["plate"]
        else:
            wfill = FEATURE_WIDTH_FILL if kind == "feature" else MAX_WIDTH_FILL
            plate, _ = _plate(img, W, H, fill_h, centre_y, wfill)
            g = None
        seg = dict(kind=kind, plate=plate, layer=_text_layer(shot, fmt, (W, H), brand),
                   dur=float(shot["seconds"]), motion=MOTION[kind], direction=direction,
                   anchor_y=centre_y, image=idx, zone=(centre_y, fill_h),
                   caption=shot.get("caption", ""))
        if g is not None:
            seg["pp"], seg["items"] = g["pp"], g["items"]
        segs.append(seg)
        if kind == "angle":
            direction = -direction
    if not segs:
        raise RuntimeError("None of the images could be read.")

    tr = style["trans_s"]
    starts, t = [], 0.0
    for i, s in enumerate(segs):
        starts.append(t)
        t += s["dur"] - (tr if i < len(segs) - 1 else 0)
    total = t
    n_frames = int(round(total * FPS))

    def _text_rows(layer):
        if layer is None:
            return None
        a = np.asarray(layer)[..., 3]
        rows = np.flatnonzero(a.max(axis=1) > 0)
        return (int(rows.min()), int(rows.max())) if rows.size else None

    # The timeline, so the finished video can be measured (measure.py). Text
    # fades in from 0.15 s and is fully visible 0.5 s into its shot.
    record["timeline"] = [
        {"kind": s["kind"], "image": s["image"], "start": round(starts[i], 3),
         "end": round(starts[i] + s["dur"], 3), "zone": list(s["zone"]),
         "caption": s["caption"], "text_rows": _text_rows(s["layer"]),
         "text_visible_at": round(starts[i] + 0.5, 3) if s["layer"] is not None else None}
        for i, s in enumerate(segs)]
    record["size"] = [W, H]
    record["transition_s"] = tr

    cmd = [ffmpeg_bin, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if audio_path is not None:
        cmd += ["-i", str(audio_path)]
    cmd += ["-map", "0:v"]
    if audio_path is not None:
        fade_out = max(0.0, total - 1.2)
        cmd += ["-map", "1:a", "-af",
                f"afade=t=in:st=0:d=0.6,afade=t=out:st={fade_out:.2f}:d=1.2",
                "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart", str(out_path)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    err = ""
    try:
        for f in range(n_frames):
            now = f / FPS
            active = [i for i, st in enumerate(starts) if st <= now < st + segs[i]["dur"]]
            if not active:
                active = [len(segs) - 1]
            frames = []
            for i in active:
                s = segs[i]
                local = now - starts[i]
                M = _matrix(s["plate"].shape[1::-1], W, H, local / s["dur"], s["motion"],
                            s["direction"], s["anchor_y"])
                fr = _frame(s["plate"], W, H, M)
                a_in = min(1.0, max(0.0, (local - 0.15) / 0.35))
                fr = _composite(fr, s["layer"], a_in, (1 - _ease(a_in)) * 24)
                if s.get("items"):
                    pts = [tuple(M @ np.float32([x, y, 1])) for x, y in s["pp"]]
                    fr = _draw_callouts(fr, s["items"], pts, local, brand)
                frames.append((i, local, fr))
            if len(frames) == 1:
                out = frames[0][2]
            else:
                (_, _, a), (_, lb, b) = frames[0], frames[-1]
                p = _ease(min(1.0, lb / tr))
                if style["transition"] == "slide":
                    shift = int(W * p)
                    out = np.empty_like(a)
                    out[:, :W - shift] = a[:, shift:]
                    out[:, W - shift:] = b[:, :shift]
                else:
                    out = cv2.addWeighted(a, 1 - p, b, p, 0)
            proc.stdin.write(np.ascontiguousarray(out).tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="ignore")
        proc.wait(timeout=300)
    except Exception:
        proc.kill()
        raise
    if proc.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError(f"Video assembly failed. {err[-800:]}")
    return PromoResult(Path(out_path), round(total, 1), len(cache), fmt,
                       audio_path is not None, mood, record)
