"""Live guidance checks the scored 4:5 region and uses per shot framing (2026-10-03)."""
import os
import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app

client = TestClient(app)


def _frame(W=288, H=512, band=0.12, frac=0.30, shift=0.0):
    f = np.full((H, W, 3), 245, np.uint8)
    b = int(H * band)
    if b:
        f[:b] = (70, 90, 110)
        f[H - b:] = (60, 70, 80)
    s = int(W * frac ** 0.5 * 1.1)
    cx, cy = int(W / 2 + shift * W), H // 2
    cv2.rectangle(f, (cx - s // 2, cy - int(s * .8)), (cx + s // 2, cy + int(s * .8)), (30, 110, 200), -1)
    for y in range(max(0, cy - int(s * .8)), min(H, cy + int(s * .8)), 9):
        cv2.putText(f, "VITAMIN C SERUM", (cx - s // 2 + 4, y), cv2.FONT_HERSHEY_SIMPLEX, .32, (255, 255, 255), 1)
    return cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def _guide(b, **form):
    return client.post("/guidance", files={"file": ("f.jpg", b, "image/jpeg")}, data=form).json()


def test_room_above_and_below_the_sheet_does_not_fail_a_good_shot():
    r = _guide(_frame())
    assert r["ready"], r


def test_too_small_still_detected():
    r = _guide(_frame(frac=0.03))
    assert not r["ready"]
    assert "closer" in r["feedback"][0].lower()


def test_detail_close_up_is_allowed_to_fill_the_frame():
    assert _guide(_frame(band=0.0, frac=0.9), shot="detail")["ready"]
    assert not _guide(_frame(band=0.0, frac=0.9))["ready"]   # main rules still apply


def test_sensor_orientation_frame_is_uprighted():
    land = cv2.rotate(cv2.imdecode(np.frombuffer(_frame(), np.uint8), 1), cv2.ROTATE_90_COUNTERCLOCKWISE)
    b = cv2.imencode(".jpg", land)[1].tobytes()
    assert _guide(b, rotation="90")["ready"]
