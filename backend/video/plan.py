"""
plan.py  -  the automatic storyboard for the marketing video (2026-10-06).

No approval step. The owner gives the facts ONCE, in the product form at the
start (name, price, up to three key features, optionally a mood). Everything
after that is decided by rules, so the result is complete, repeatable and
explainable:

  shot order   hook (main shot, product name) -> angles -> feature scene (the
               detail shot with labelled callouts) -> end card (price, call to
               action, shop and contact when the profile provides them)
  text         ONLY the owner's own words. Nothing is generated, so nothing can be
               invented about the product. The model is used for one thing: to
               find WHERE each named feature is (features.py).
  music        the owner's mood, or the category's recommended mood; the first
               installed track of that mood. The owner confirmed the mood in the
               form, which keeps the recommendation-with-confirmation design.
  post kit     a ready to paste caption and hashtags built from the same facts.
  checklist    the short form content rules this video is built to meet, each
               checked and reported (met / not met and why).

Checklist sources: Google's ABCD framework for YouTube (Attention, Branding,
Connection, Direction) and the platforms' 9:16 safe zone guidance; Yang et al.
(2025, JTAER) on matching visual pace to audio. The checklist states what the
video follows; it makes NO claim about views or sales.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict

from .promo import BASE_SECONDS, MOOD_STYLE, FEATURE_BASE, FEATURE_EACH

DEFAULT_CTA = "Message us to order"
MAX_FEATURES = 3
FEATURE_CHARS = 30
MIN_SECONDS, MAX_SECONDS = 8.0, 15.0
MAX_STRETCH = 1.35          # longest a short plan's shots are held, as a factor


@dataclass
class ProductInfo:
    name: str = ""
    price: str = ""
    features: list = field(default_factory=list)
    category: str = ""
    mood: str = ""
    shop: str = ""          # from the business profile (next step); optional now
    contact: str = ""       # from the business profile (next step); optional now

    def clean(self) -> "ProductInfo":
        cut = lambda s, n: " ".join(str(s or "").split())[:n]
        feats = [cut(f, FEATURE_CHARS) for f in (self.features or []) if str(f).strip()]
        mood = cut(self.mood, 12).lower()
        return ProductInfo(cut(self.name, 40), cut(self.price, 24), feats[:MAX_FEATURES],
                           cut(self.category, 30), mood if mood in MOOD_STYLE else "",
                           cut(self.shop, 32), cut(self.contact, 40))


def _tags(info: ProductInfo) -> list:
    words = [w for w in re.findall(r"[A-Za-z0-9]+", info.name) if len(w) > 2]
    tags = []
    if words:
        tags.append("#" + "".join(w.capitalize() for w in words[:3]))
    if info.category:
        tags.append("#" + "".join(w.capitalize() for w in info.category.split()))
    if info.shop:
        tags.append("#" + "".join(w.capitalize() for w in re.findall(r"[A-Za-z0-9]+", info.shop)))
    tags += ["#ShopSmall", "#SriLanka"]
    seen, out = set(), []
    for t in tags:
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:5]


def post_kit(info: ProductInfo, music: dict | None = None) -> dict:
    lines = [info.name + (f" - {info.price}" if info.price else "")] if info.name else []
    lines += [f"- {f}" for f in info.features]
    cta = DEFAULT_CTA + (f": {info.contact}" if info.contact else ".")
    lines += ["", cta]
    tags = _tags(info)
    caption = "\n".join(lines).strip() + "\n\n" + " ".join(tags)
    # CC BY music must be credited where the video is posted (v1.1.0). CC0 and
    # Pixabay tracks need no credit, so none is added.
    credit = ""
    if music and music.get("track_id") and str(music.get("licence", "")).upper().startswith("CC-BY"):
        from ..audio.catalog import attribution_line
        credit = attribution_line({"title": music.get("title", ""),
                                   "artist": music.get("artist", ""),
                                   "source_url": music.get("source_url", "")})
        caption += "\n\n" + credit
    return {"caption": caption, "hashtags": tags, "music_credit": credit}


def shot_seconds(kind: str, mood: str, n_callouts: int = 0) -> float:
    pace = MOOD_STYLE.get(mood, MOOD_STYLE["upbeat"])["pace"]
    if kind == "feature":
        return round((FEATURE_BASE + FEATURE_EACH * n_callouts) * pace, 3)
    return round(BASE_SECONDS[kind] * pace, 3)


def plan_duration(shots: list, mood: str) -> float:
    tr = MOOD_STYLE.get(mood, MOOD_STYLE["upbeat"])["trans_s"]
    total = sum(s["seconds"] for s in shots) - tr * max(0, len(shots) - 1)
    return round(total, 1)


def build_plan(images: list, info: ProductInfo, fmt: str = "vertical",
               located: dict | None = None, music: dict | None = None) -> dict:
    """images: [(role, index)] of the CERTIFIED set, in any order.
    located: result of features.locate_features on the feature image, or None.
    music: {"mood", "track_id", "title", "attribution", "reason"} or None."""
    info = info.clean()
    by = {"hero_shot": [], "angle_shot": [], "detail_shot": []}
    for role, idx in images:
        by.get(role, by["angle_shot"]).append(idx)
    hero = (by["hero_shot"] or by["angle_shot"] or by["detail_shot"])[0]
    feature_img = by["detail_shot"][0] if by["detail_shot"] else hero
    mood = (music or {}).get("mood") or info.mood or "upbeat"

    points = (located or {}).get("points") or []
    callouts = [{"label": f, "x": p[0], "y": p[1]}
                for f, p in zip(info.features, points) if p]
    captions = [f for i, f in enumerate(info.features)
                if i >= len(points) or not points[i]]

    shots = [{"kind": "hook", "image": hero, "caption": info.name, "kicker": info.shop}]
    for idx in by["angle_shot"][:3]:
        shots.append({"kind": "angle", "image": idx,
                      "caption": captions.pop(0) if captions else ""})
    details = list(by["detail_shot"])
    if callouts:
        shots.append({"kind": "feature", "image": feature_img, "callouts": callouts})
        if feature_img in details:
            details.remove(feature_img)
    for idx in details[:2]:
        shots.append({"kind": "detail", "image": idx,
                      "caption": captions.pop(0) if captions else ""})
    # Features with no slot yet (callouts rejected by the guard, or too few angle
    # and detail photos): each gets its own close shot with the feature as its
    # caption, so no feature the owner typed is lost (v1.1.0). Photos are taken in
    # turn from the feature photo, the angles and the main shot, never the same
    # photo twice in a row.
    pool = [feature_img] + by["angle_shot"] + [hero]
    k = 0
    while captions:
        idx = pool[k % len(pool)]
        k += 1
        if idx == shots[-1]["image"] and len(set(pool)) > 1:
            continue
        shots.append({"kind": "detail", "image": idx, "caption": captions.pop(0)})
    end_lines = {"price": info.price,
                 "cta": DEFAULT_CTA + (":" if info.contact else ""),
                 "contact": info.contact, "shop": info.shop}
    shots.append({"kind": "end", "image": hero, **end_lines})
    leftover = captions                       # features with no slot (very rare)
    for s in shots:
        s["seconds"] = shot_seconds(s["kind"], mood, len(s.get("callouts", [])))

    # Keep it short form. First drop the optional extra shots (a third angle, a
    # second detail) whose caption is empty; then tighten every shot a little
    # (never below 85 percent of its paced length).
    while plan_duration(shots, mood) > MAX_SECONDS:
        extra = [s for s in shots[1:-1] if not s.get("caption") and s["kind"] != "feature"]
        n_angles = sum(1 for s in shots if s["kind"] == "angle")
        drop = next((s for s in reversed(extra)
                     if s["kind"] == "detail" or n_angles > 2), None)
        if drop is None:
            break
        shots.remove(drop)
    if plan_duration(shots, mood) > MAX_SECONDS:
        k = max(0.85, MAX_SECONDS / plan_duration(shots, mood) - 0.005)
        for s in shots:
            s["seconds"] = round(s["seconds"] * k, 3)
    # A small set (three or four photos, fast mood) can come out under the short
    # form minimum; hold every shot a little longer, by at most MAX_STRETCH.
    if plan_duration(shots, mood) < MIN_SECONDS:
        tr = MOOD_STYLE.get(mood, MOOD_STYLE["upbeat"])["trans_s"]
        total = sum(s["seconds"] for s in shots)
        k = min(MAX_STRETCH, (MIN_SECONDS + 0.06 + tr * (len(shots) - 1)) / total)
        for s in shots:
            s["seconds"] = round(s["seconds"] * k, 3)

    duration = plan_duration(shots, mood)
    shown = len(callouts) + sum(1 for s in shots if s.get("caption") and s["kind"] != "hook")
    checklist = [
        {"rule": "Hook in the first 2 seconds",
         "met": bool(info.name),
         "detail": "Main shot with the product name from 0.2 s." if info.name
                   else "No product name was given."},
        {"rule": "Product fills the frame",
         "met": True, "detail": "Every shot is framed on the product, not fitted."},
        {"rule": "Brand early and at the end",
         "met": bool(info.shop),
         "detail": "Shop name on the first shot and the end card." if info.shop
                   else "Add your shop name in the business profile."},
        {"rule": "Key features shown",
         "met": shown >= len(info.features) and not leftover,
         "detail": f"{len(callouts)} pointed out on the photo, "
                   f"{shown - len(callouts)} as captions, of {len(info.features)} given."},
        {"rule": "Clear call to action",
         "met": True,
         "detail": "End card: " + end_lines["cta"] + (f" {info.contact}" if info.contact
                                                    else " (add contact in your profile)")},
        {"rule": "Text inside platform safe zones",
         "met": True, "detail": "No text in the top 14 % or bottom 35 % of a 9:16 video."
                                if fmt == "vertical" else "Text kept inside the frame margins."},
        {"rule": "Short form length (8 to 15 s)",
         "met": MIN_SECONDS <= duration <= MAX_SECONDS, "detail": f"{duration} s."},
        {"rule": "Pace matches the music",
         "met": True, "detail": f"{mood.capitalize()} mood: shot lengths and transitions "
                                f"follow the music's pace."},
        {"rule": "Only certified photos",
         "met": True, "detail": "Every frame is one of the photos that passed the standard."},
    ]
    for c in checklist:              # filled with measured values after rendering
        c.setdefault("measured", None)
        c.setdefault("threshold", None)
    return {
        "version": "pqf-video-plan-1",
        "checklist_source": "declared",
        "format": fmt if fmt in ("vertical", "square") else "vertical",
        "mood": mood,
        "music": music or {"mood": mood, "track_id": None},
        "shots": shots,
        "duration_seconds": duration,
        "callout_source": (located or {}).get("source", "none"),
        "callout_error": (located or {}).get("error", ""),
        "post": post_kit(info, music),
        "checklist": checklist,
        "product": asdict(info),
    }
