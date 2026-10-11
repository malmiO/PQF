"""v1.4.0: per-criterion breakdown on each /batch image entry (display only).

The scores are read from the decision objects the framework already produced. This
changes no criterion, weight, threshold or decision: the selection and certification
output of /batch must be exactly what process_batch decides."""
import os

import cv2
import numpy as np

os.environ["PQF_SEMANTIC_MOCK"] = "1"
from fastapi.testclient import TestClient
from backend.api.main import _platform_format, app
from backend.pqf import config
from backend.pqf.pipeline import process_batch

client = TestClient(app)


def _photo(offset=0, tilt=0):
    img = np.full((1350, 1080, 3), 230, np.uint8)
    cv2.rectangle(img, (400 + offset, 420), (700 + offset, 940), (40, 60, 190), -1)
    cv2.circle(img, (540 + offset, 380), 55, (30, 150, 60), -1)
    if tilt:
        M = cv2.getRotationMatrix2D((540, 675), tilt, 1.0)
        img = cv2.warpAffine(img, M, (1080, 1350), borderValue=(230, 230, 230))
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])[1].tobytes()


def _batch():
    files = [("files", (f"{i}.jpg", _photo(o, t), "image/jpeg"))
             for i, (o, t) in enumerate([(0, 0), (60, 12), (-60, -12), (0, 25)])]
    return files


def test_every_image_entry_carries_technical_and_semantic_dicts():
    r = client.post("/batch", files=_batch())
    assert r.status_code == 200, r.text[:300]
    imgs = r.json()["images"]
    assert len(imgs) == 4
    for e in imgs:
        assert isinstance(e["technical"], dict) and isinstance(e["semantic"], dict)
        # a photo that reached the semantic stage carries all 6 + 5 criteria
        if e["semantic"]:
            assert set(e["technical"]) == set(config.TQS_WEIGHTS)
            assert set(e["semantic"]) == set(config.SQS_WEIGHTS)
        for v in list(e["technical"].values()) + list(e["semantic"].values()):
            assert 0.0 <= v <= 1.0
            assert round(v, 3) == v


def test_the_values_are_the_decision_scores_not_recomputed():
    files = _batch()
    payload = [(_platform_format(f[1][1]), f[1][0]) for f in files]
    direct = process_batch(payload)
    body = client.post("/batch", files=files).json()
    for i, d in enumerate(direct.all_decisions):
        want_t = {k: round(v, 3) for k, v in (getattr(d, "technical_scores", {}) or {}).items()}
        want_s = {k: round(v, 3) for k, v in (d.semantic_scores or {}).items()}
        assert body["images"][i]["technical"] == want_t
        assert body["images"][i]["semantic"] == want_s


def test_selection_and_certification_are_exactly_what_the_framework_decides():
    files = _batch()
    payload = [(_platform_format(f[1][1]), f[1][0]) for f in files]
    direct = process_batch(payload)
    body = client.post("/batch", files=files).json()
    assert body["certified"] == direct.certified
    assert [(s["index"], s["role"], s["passed"]) for s in body["selected"]] == \
        [(i, d.role, d.passed) for i, d in enumerate(direct.all_decisions)]
    assert [e["selected"] for e in body["images"]] == \
        [any(d is s for s in direct.selected) for d in direct.all_decisions]
    # the entries keep every field they had before, with the same meaning
    for e in body["images"]:
        assert {"index", "name", "role", "fqs", "passed", "selected", "status",
                "message"} <= set(e)


def test_thresholds_are_not_duplicated_in_the_batch_response():
    body = client.post("/batch", files=_batch()).json()
    e = body["images"][0]
    assert "pass_threshold" not in e and "thresholds" not in e
    crit = client.get("/criteria").json()
    assert all("pass_threshold" in t for t in crit["technical"])
    assert all("pass_threshold" in t for t in crit["semantic"])
    assert crit["combination"]["pass_threshold"] == config.FQS_PASS_THRESHOLD
