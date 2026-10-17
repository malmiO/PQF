"""Renderer memory (v1.1.0, Part E): the plate is built without the full size
padded copy, and looks the same as before. Measured on the J6+ set: peak 1146 MB
-> 575 MB including ffmpeg (scripts/measure_render.py)."""
import cv2
import numpy as np
import pytest

from backend.video import promo as P


def _old_plate(img, out_w, out_h, fill_h, centre_y, max_w_fill=P.MAX_WIDTH_FILL,
               oversample=1.3):
    """The pre v1.1.0 algorithm, kept here as the reference."""
    cx, cy, pw, ph = P.product_box_xywh(img)
    aspect = out_w / out_h
    crop_h = max(ph / fill_h, (pw / max_w_fill) / aspect)
    crop_h = max(crop_h, out_h / P.MAX_UPSCALE)
    crop_w = crop_h * aspect
    top, left = cy - crop_h * centre_y, cx - crop_w / 2
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
    return cv2.resize(crop, (W, H), interpolation=interp)


def _photo():
    rng = np.random.default_rng(3)
    img = np.full((1350, 1080, 3), 210, np.uint8)
    img[:, :, 0] = np.linspace(190, 225, 1080, dtype=np.uint8)[None, :]   # uneven light box
    cv2.rectangle(img, (440, 520), (640, 860), (40, 60, 200), -1)
    cv2.circle(img, (540, 470), 55, (30, 160, 60), -1)
    return np.clip(img.astype(int) + rng.integers(-3, 4, img.shape), 0, 255).astype(np.uint8)


@pytest.mark.parametrize("kind", ["hook", "angle", "detail", "end"])
def test_new_plate_matches_the_old_one(kind):
    img = _photo()
    W, H = P.FORMATS["vertical"]
    cy, fill = P.LAYOUT["vertical"][kind]
    new, to_plate = P._plate(img, W, H, fill, cy)
    old = _old_plate(img, W, H, fill, cy)
    assert new.shape == old.shape
    diff = np.abs(new.astype(int) - old.astype(int))
    assert diff.mean() < 2.0                       # indistinguishable on average
    # the product sits in the same place: its centre maps to the same pixel
    cx, pcy, _, _ = P.product_box_xywh(img)
    px, py = to_plate(cx, pcy)
    assert 0 <= px < new.shape[1] and 0 <= py < new.shape[0]
    assert np.abs(new[int(py), int(px)].astype(int) - old[int(py), int(px)].astype(int)).max() < 12


def test_encoder_threads_are_capped(monkeypatch, tmp_path):
    """x264 uses a fixed small number of threads, so its memory is predictable."""
    seen = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            seen["cmd"] = cmd
            raise RuntimeError("stop after building the command")
    monkeypatch.setattr(P.subprocess, "Popen", FakePopen)
    p = tmp_path / "img_00.img"
    p.write_bytes(cv2.imencode(".jpg", _photo())[1].tobytes())
    plan = {"format": "vertical", "mood": "calm",
            "shots": [{"kind": "hook", "image": 0, "seconds": 1.5, "caption": "K"}]}
    with pytest.raises(RuntimeError):
        P.render_plan(plan, [p], tmp_path / "o.mp4")
    cmd = seen["cmd"]
    assert cmd[cmd.index("-threads") + 1] == "2"
