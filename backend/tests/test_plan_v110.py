"""v1.1.0 plan fixes found while looking at real renders: no feature is lost when
callouts fall back to captions, and a small set still reaches the 8 s minimum."""
import pytest

from backend.video.plan import build_plan, ProductInfo, MIN_SECONDS, MAX_SECONDS

FEATS = ["Silver clasp", "Red apple", "Painted letters"]
NOT_FOUND = {"points": [None, None, None], "source": "model", "error": ""}


@pytest.mark.parametrize("roles", [
    [("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2)],          # no detail
    [("hero_shot", 0), ("detail_shot", 1)],                            # one slot only
])
def test_every_feature_gets_a_caption_when_callouts_fall_back(roles):
    plan = build_plan(roles, ProductInfo(name="Keychain", features=FEATS), "vertical",
                      NOT_FOUND, None)
    captions = [s.get("caption") for s in plan["shots"] if s["kind"] != "hook"]
    assert all(f in captions for f in FEATS)
    shots = plan["shots"]
    assert all(a["image"] != b["image"] or a["kind"] == "end" or b["kind"] == "end"
               for a, b in zip(shots, shots[1:]) if a["kind"] == b["kind"] == "detail")
    item = next(c for c in plan["checklist"] if c["rule"] == "Key features shown")
    assert item["met"] is True


@pytest.mark.parametrize("fmt", ["vertical", "square"])
def test_small_upbeat_set_is_held_to_the_short_form_minimum(fmt):
    roles = [("hero_shot", 0), ("angle_shot", 1), ("angle_shot", 2), ("detail_shot", 3)]
    plan = build_plan(roles, ProductInfo(name="Keychain", mood="upbeat"), fmt, None,
                      {"mood": "upbeat", "track_id": None})
    assert MIN_SECONDS <= plan["duration_seconds"] <= MAX_SECONDS
