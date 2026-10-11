"""
batch_explain.py  -  tell the owner, for EVERY photo, whether it was used and why,
and say exactly which shots are still missing (2026-10-06).

The app uses this for the one-pass flow: check all photos, show which were chosen
and which were not, and if the set is not certified, open the camera ONLY for the
missing shots. Nothing here scores anything; it explains decisions already made by
the framework (pipeline._select_best_set and the gate).
"""
from __future__ import annotations

from ..pqf import config

ROLE_WORD = {"hero_shot": "main shot", "angle_shot": "angle", "detail_shot": "detail"}


def weakest_technical(tech: dict) -> str:
    """The technical criterion to explain a hard-rejected photo by (v1.4.0).

    The one with the LARGEST SHORTFALL below its own pass threshold
    (config.TQS_PASS_THRESHOLDS); if none is below its threshold, the lowest score.
    A criterion with weight 0 (T4, excluded) is never chosen: it is reported but gives
    no feedback, and BRISQUE reads low on most photographs, so it would otherwise be
    named for nearly every rejected photo. Returns "" if there are no scores.
    """
    usable = {k: v for k, v in (tech or {}).items()
              if config.TQS_WEIGHTS.get(k, 0.0) > 0.0}
    pool = usable or dict(tech or {})
    if not pool:
        return ""
    short = {k: config.TQS_PASS_THRESHOLDS.get(k, 0.0) - v for k, v in pool.items()}
    k, gap = max(short.items(), key=lambda kv: kv[1])
    return k if gap > 0 else min(pool, key=pool.get)

CHOSEN = {
    "hero_shot": "Chosen as the main shot.",
    "angle_shot": "Chosen: shows the product from another side.",
    "detail_shot": "Chosen: the close-up of the details.",
}

MISSING = {
    "hero_shot": "Take the main shot: the product straight on, centred, filling most "
                 "of the frame.",
    "angle_shot": "Take {n} more photo{s} from a different side or tilt.",
    "detail_shot": "Take a close-up of the most important detail, such as the texture, "
                   "label or clasp.",
}


def _weakest(d, feedback: dict, thresholds: dict) -> str:
    """Plain message for why an image did not pass."""
    reason = getattr(d, "reason", "") or ""
    if reason == "decode_failed":
        return "Not used: this file could not be opened as a photo."
    if reason.startswith("t0_platform"):
        return "Not used: the photo is too small or the wrong shape for posting."
    if reason.startswith("semantic_failed"):
        return "Could not be checked this time. Try again."
    tech = getattr(d, "technical_scores", {}) or {}
    sem = d.semantic_scores or {}
    if d.hard_rejected or not sem:
        if tech:
            k = weakest_technical(tech)
            return "Not used: " + feedback.get(k, "the photo quality is too low.")
        return "Not used: the photo quality is too low. Retake it."
    gaps = {k: v - thresholds.get(k, 0.0) for k, v in sem.items()}
    k = min(gaps, key=gaps.get)
    return "Not used: " + feedback.get(k, "it is not good enough to post yet.")


def explain_batch(result, feedback: dict, thresholds: dict) -> dict:
    """result: pipeline.BatchResult. Returns {"images": [...], "missing": [...]}."""
    index_of = {id(d): i for i, d in enumerate(result.all_decisions)}
    selected = {id(d) for d in result.selected}
    images = []
    for i, d in enumerate(result.all_decisions):
        entry = {"index": i, "name": getattr(d, "path", ""), "role": d.role,
                 "fqs": round(d.fqs, 3), "passed": d.passed,
                 "selected": id(d) in selected}
        note = getattr(d, "selection_note", "")
        if id(d) in selected:
            entry["status"] = "selected"
            entry["message"] = CHOSEN.get(d.role, "Chosen.")
        elif note == "same_view":
            j = index_of.get(id(getattr(d, "duplicate_of", None)), -1)
            entry["status"] = "same_view"
            entry["message"] = ("Not used: it shows the same view as photo "
                                f"{j + 1}, which is already in your set." if j >= 0 else
                                "Not used: it shows a view already in your set.")
        elif d.passed:
            entry["status"] = "not_needed"
            entry["message"] = "Good photo. Not needed: your set already has the views it needs."
        else:
            entry["status"] = "not_good_enough"
            entry["message"] = _weakest(d, feedback, thresholds)
        images.append(entry)
    return {"images": images, "missing": missing_shots(result)}


def missing_shots(result) -> list:
    """Which shots to take next, as [{"role", "count", "message"}]. Empty if certified."""
    rc = result.recapture
    if not rc:
        return []
    fails, counts = rc.get("fail_reasons", []), rc.get("counts", {})
    out = []
    if "no_hero_shot" in fails:
        out.append({"role": "hero_shot", "count": 1, "message": MISSING["hero_shot"]})
    if "insufficient_angles" in fails:
        have = counts.get("distinct_angles", counts.get("angle", 0))
        n = max(1, 2 - have)
        msg = MISSING["angle_shot"].format(n=n, s="s" if n > 1 else "")
        if counts.get("angle", 0) > have:
            msg += " Some of your angle photos show the same view."
        out.append({"role": "angle_shot", "count": n, "message": msg})
    if "no_detail_shot" in fails:
        out.append({"role": "detail_shot", "count": 1, "message": MISSING["detail_shot"]})
    if not out and "insufficient_coverage" in fails:
        n = max(1, 4 - counts.get("total", 0))
        out.append({"role": "angle_shot", "count": n,
                    "message": MISSING["angle_shot"].format(n=n, s="s" if n > 1 else "")})
    return out
