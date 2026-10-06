"""
features.py  -  find WHERE the owner's key features are in a certified photo (2026-10-06).

The owner types up to three key features in the product form ("gold plated clasp",
"hand painted letters"). The video's feature scene points at each one with a line
and a label, like a product diagram. This module asks the multimodal model only
one narrow question: where in this photo is each named feature, if it is visible
at all. It writes no text and invents nothing; the labels are the owner's words.

Coordinates follow the Gemini API object detection convention:
box_2d = [ymin, xmin, ymax, xmax], normalised to 0-1000.
(ai.google.dev/gemini-api/docs/image-understanding, accessed 2026-10-06.)

Safety rules, so a wrong answer cannot put a label in the wrong place:
  * a feature the model cannot see clearly is returned as None and is shown as a
    caption instead of a callout;
  * a box must be well formed and smaller than 60 percent of the photo (a box
    around the whole product is not a feature location);
  * its centre must fall on the product, inside the framework's product box
    (views.product_box), expanded by 8 percent.
Any failure (no key, quota, network, bad JSON) returns None for every feature, so
the video is still made, with captions only. The failure is reported in the plan.
"""
from __future__ import annotations

import json
import os
import re

DETECT_MODEL_ENV = "PQF_DETECT_MODEL"      # optional override, e.g. gemini-flash-latest
MAX_FEATURE_AREA = 0.60

PROMPT = """You are looking at a product photograph.
For each feature in the list below, find where it is VISIBLE in this photo.
Return ONLY JSON: a list with one object per feature, in the same order:
[{{"label": "<feature exactly as given>", "box_2d": [ymin, xmin, ymax, xmax]}}]
The box_2d is normalised to 0-1000. If a feature is not clearly visible in this
photo, return "box_2d": null for it. Do not guess. Do not add features.
Features:
{features}"""


def _model_name() -> str:
    from ..pqf import config
    return os.environ.get(DETECT_MODEL_ENV) or config.GEMINI_MODEL


def _call_model(image_bytes: bytes, mime: str, prompt: str) -> str:
    """One model call; returns the raw text. Raises on any failure."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    try:                                         # current SDK (google-genai)
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(
            model=_model_name(),
            contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime), prompt],
            config=types.GenerateContentConfig(temperature=0,
                                               response_mime_type="application/json"))
        return resp.text
    except ImportError:                          # older SDK, kept for safety
        import google.generativeai as old
        old.configure(api_key=key)
        m = old.GenerativeModel(_model_name())
        resp = m.generate_content([prompt, {"mime_type": mime, "data": image_bytes}],
                                  generation_config={"temperature": 0})
        return resp.text


def _parse(text: str, n: int) -> list:
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    data = json.loads(t)
    if isinstance(data, dict):
        data = data.get("features") or data.get("boxes") or list(data.values())[0]
    out = []
    for i in range(n):
        item = data[i] if i < len(data) else None
        box = item.get("box_2d") if isinstance(item, dict) else None
        out.append(box)
    return out


def validate_box(box, product_box_norm=None):
    """Return the feature's centre (x, y) in 0-1 image coordinates, or None."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        y0, x0, y1, x1 = (float(v) / 1000.0 for v in box)
    except (TypeError, ValueError):
        return None
    if not (0 <= x0 < x1 <= 1.0001 and 0 <= y0 < y1 <= 1.0001):
        return None
    if (x1 - x0) * (y1 - y0) > MAX_FEATURE_AREA:
        return None
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if product_box_norm is not None:
        px0, py0, px1, py1 = product_box_norm
        m = 0.08
        if not (px0 - m <= cx <= px1 + m and py0 - m <= cy <= py1 + m):
            return None
    return (round(cx, 4), round(cy, 4))


def locate_features(image_bytes: bytes, features: list, mime: str = "image/jpeg",
                    call=None) -> dict:
    """Locate each feature. Returns {"points": [(x, y) or None per feature],
    "source": "model" | "unavailable", "error": str}. `call` is injectable for tests."""
    feats = [f for f in features if f]
    if not feats:
        return {"points": [], "source": "none", "error": ""}
    import cv2
    import numpy as np
    from ..pqf.pipeline.views import product_box
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    pbox = None
    if img is not None:
        h, w = img.shape[:2]
        k = 1024 / max(h, w)
        small = cv2.resize(img, (int(w * k), int(h * k)), interpolation=cv2.INTER_AREA)
        x0, y0, x1, y1 = product_box(small)
        sh, sw = small.shape[:2]
        pbox = (x0 / sw, y0 / sh, x1 / sw, y1 / sh)
    prompt = PROMPT.format(features="\n".join(f"- {f}" for f in feats))
    try:
        raw = (call or _call_model)(image_bytes, mime, prompt)
        boxes = _parse(raw, len(feats))
    except Exception as e:                        # no key, quota, network, bad JSON
        return {"points": [None] * len(feats), "source": "unavailable",
                "error": str(e)[:200]}
    return {"points": [validate_box(b, pbox) for b in boxes], "source": "model",
            "error": ""}
