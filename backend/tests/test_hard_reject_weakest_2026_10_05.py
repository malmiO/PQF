"""A hard-rejected image must report its weakest TECHNICAL criterion, never an
empty string, so the app can explain the rejection instead of only saying
"Retake this one" (2026-10-05, Part A step 4)."""
import os
import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.pqf import config

client = TestClient(app)


def test_hard_rejected_image_reports_weakest_technical_criterion():
    # A black 1080x1080 frame passes T0 (size and aspect) but hard-rejects on a
    # low TQS, so it has technical scores but no semantic scores.
    black = np.zeros((1080, 1080, 3), np.uint8)
    b = cv2.imencode(".jpg", black)[1].tobytes()
    img = client.post(
        "/batch", files=[("files", ("black.jpg", b, "image/jpeg"))]
    ).json()["selected"][0]

    assert img["passed"] is False
    assert img["reason"].startswith("hard_reject")
    # Never empty, and it must be a TECHNICAL criterion (not a semantic one).
    assert img["weakest"] != ""
    assert img["weakest"] in config.TQS_WEIGHTS
