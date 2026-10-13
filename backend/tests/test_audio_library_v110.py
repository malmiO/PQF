"""Step 5 (v1.1.0): music library manifest, licence validation, loudness
normalised files only, bpm based choice, and the CC BY credit in the caption."""
import os
from pathlib import Path

import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from backend.audio import catalog as C
from backend.audio.settings import FILES_DIR, NORMALISED_DIR
from backend.video import audio as A
from backend.video.plan import ProductInfo, build_plan, post_kit

GOOD = {"track_id": "calm_1", "mood": "calm", "title": "Morning", "artist": "Ann",
        "source_url": "https://example.org/t/1", "licence": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "downloaded_on": "2026-10-06", "attribution": "Morning by Ann (CC BY 4.0)",
        "file": "calm_1.mp3", "duration_s": "60", "bpm": "72"}


def _lib(tmp_path, rows):
    (tmp_path / FILES_DIR).mkdir(parents=True)
    (tmp_path / NORMALISED_DIR).mkdir(parents=True)
    for r in rows:
        (tmp_path / FILES_DIR / r["file"]).write_bytes(b"x")
        (tmp_path / NORMALISED_DIR / r["file"]).write_bytes(b"x")
    return tmp_path


def _rows_all_moods(**over):
    rows = []
    for mood, bpm in (("calm", "72"), ("elegant", "90"), ("upbeat", "122")):
        rows.append({**GOOD, "track_id": f"{mood}_1", "mood": mood, "file": f"{mood}_1.mp3",
                     "bpm": bpm, **over})
    return rows


def test_a_complete_library_passes(tmp_path):
    rows = _rows_all_moods()
    assert C.validate(rows, _lib(tmp_path, rows), duration_of=lambda p: 60.0) == []


def test_validator_rejects_noncommercial_licence(tmp_path):
    rows = _rows_all_moods()
    rows[0]["licence"] = "CC-BY-NC-4.0"
    msgs = [m for _, m in C.validate(rows, _lib(tmp_path, rows), duration_of=lambda p: 60.0)]
    assert any("NonCommercial or NoDerivatives" in m for m in msgs)
    assert any("not one of" in m for m in msgs)


def test_validator_rejects_cc_by_without_attribution(tmp_path):
    rows = _rows_all_moods()
    rows[1]["attribution"] = ""
    msgs = [m for _, m in C.validate(rows, _lib(tmp_path, rows), duration_of=lambda p: 60.0)]
    assert any("empty attribution" in m for m in msgs)


def test_validator_rejects_short_missing_untreated_and_uncovered(tmp_path):
    rows = _rows_all_moods()[:2]                      # no upbeat track
    base = _lib(tmp_path, rows)
    (base / NORMALISED_DIR / rows[0]["file"]).unlink()
    rows.append({**GOOD, "track_id": "ghost", "file": "ghost.mp3"})
    msgs = [m for _, m in C.validate(rows, base, duration_of=lambda p: 10.0)]
    assert any("file missing" in m for m in msgs)
    assert any("only 10.0 s" in m for m in msgs)
    assert any("not normalised" in m for m in msgs)
    assert any("'upbeat' mood" in m for m in msgs)


def test_test_tones_are_reported(tmp_path):
    rows = _rows_all_moods() + [{**GOOD, "track_id": "tone", "licence": "TEST",
                                 "file": "tone.mp3", "attribution": ""}]
    msgs = [m for _, m in C.validate(rows, _lib(tmp_path, rows), duration_of=lambda p: 60.0)]
    assert any("test tone" in m for m in msgs)


def test_caption_credits_cc_by_music_and_not_cc0():
    info = ProductInfo(name="Keychain", price="Rs. 450")
    by = post_kit(info, {"track_id": "calm_1", "licence": "CC-BY-4.0", "title": "Morning",
                         "artist": "Kevin MacLeod", "source_url": "https://incompetech.com"})
    # CC BY 4.0: names the work and author, links the licence, and indicates the
    # changes made (trimmed, faded, loudness-normalised).
    assert ("Morning by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0 "
            "(https://creativecommons.org/licenses/by/4.0/). "
            "Edited: trimmed, faded, loudness-normalised.") in by["caption"]
    assert by["music_credit"]
    cc0 = post_kit(info, {"track_id": "x", "licence": "CC0", "title": "T", "artist": "B",
                          "source_url": "u"})
    assert "licensed under CC BY 4.0" not in cc0["caption"] and cc0["music_credit"] == ""
    plan = build_plan([("hero_shot", 0)], info, "vertical", None,
                      {"mood": "calm", "track_id": "calm_1", "licence": "CC-BY-4.0",
                       "title": "Morning", "artist": "Kevin MacLeod",
                       "source_url": "https://incompetech.com"})
    assert ("Morning by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0"
            in plan["post"]["caption"])
    assert "Edited: trimmed, faded, loudness-normalised." in plan["post"]["caption"]


def test_track_with_bpm_closest_to_the_mood_is_chosen(tmp_path, monkeypatch):
    rows = [{**GOOD, "track_id": "fast_calm", "bpm": "110", "file": "a.mp3"},
            {**GOOD, "track_id": "slow_calm", "bpm": "76", "file": "b.mp3"},
            {**GOOD, "track_id": "no_bpm", "bpm": "", "file": "c.mp3"}]
    base = _lib(tmp_path, rows)
    monkeypatch.setattr(C, "read_rows", lambda b, m=None: rows)
    assert A.first_track("calm", base).id == "slow_calm"


def test_only_normalised_files_are_played(tmp_path, monkeypatch):
    rows = [{**GOOD}]
    base = _lib(tmp_path, rows)
    monkeypatch.setattr(C, "read_rows", lambda b, m=None: rows)
    assert A.resolve_track("calm_1", base) == base / NORMALISED_DIR / "calm_1.mp3"
    (base / NORMALISED_DIR / "calm_1.mp3").unlink()
    assert A.resolve_track("calm_1", base) is None          # original alone is not used
    assert A.recommend("cosmetics", base).tracks == []
