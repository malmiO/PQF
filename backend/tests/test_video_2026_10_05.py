"""Video assembly: no silent audio failure, background coloured padding (2026-10-05)."""
import os
import cv2
import numpy as np
import pytest

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.video.builder import background_colour, ffmpeg_available

client = TestClient(app)
# Gate on the robust resolver (PQF_FFMPEG / PATH / known install locations),
# not PATH alone, so the test reflects whether video can actually be made.
needs_ffmpeg = pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")


def _img(bg=(205, 203, 202)):
    f = np.full((1350, 1080, 3), bg, np.uint8)
    cv2.rectangle(f, (440, 400), (640, 950), (40, 200, 230), -1)
    return cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


def test_background_colour_is_estimated_not_white(tmp_path):
    p = tmp_path / "a.jpg"
    p.write_bytes(_img())
    c = background_colour(p)
    r, g, b = int(c[2:4], 16), int(c[4:6], 16), int(c[6:8], 16)
    assert 195 <= r <= 212 and 195 <= g <= 212 and 195 <= b <= 212


def test_music_lists_only_tracks_that_exist():
    from pathlib import Path
    import backend.api.main as M
    from backend.video import audio as A
    base = Path(M.__file__).resolve().parents[2]
    files = {t.id: t.filename for t in A.load_library(base)}
    for t in client.get("/music", params={"category": "cosmetics"}).json()["tracks"]:
        assert (A.library_dir(base) / files[t["id"]]).exists(), t["id"]


@needs_ffmpeg
def test_missing_track_is_an_error_not_a_silent_video():
    files = [("files", ("a.jpg", _img(), "image/jpeg"))]
    r = client.post("/video", files=files, data={"roles": "hero_shot", "track_id": "does_not_exist"})
    assert r.status_code == 404


def test_music_preview_streams_a_listed_track_and_404s_otherwise():
    tracks = client.get("/music").json()["tracks"]
    if tracks:
        r = client.get(f"/music/preview/{tracks[0]['id']}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("audio/")
    assert client.get("/music/preview/does_not_exist").status_code == 404


def test_health_reports_video_readiness():
    h = client.get("/health").json()
    assert isinstance(h.get("video_ready"), bool)
    assert h["video_ready"] == ffmpeg_available()
    # v1.1.0: per mood, plus whether test tones are still installed
    assert isinstance(h.get("music_tracks"), dict)
    assert set(h["music_tracks"]) == {"calm", "elegant", "upbeat"}
    assert all(isinstance(v, int) and v >= 0 for v in h["music_tracks"].values())
    assert isinstance(h.get("test_tones"), bool)
