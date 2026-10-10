"""
check_server.py  -  is the API fit to produce research data RIGHT NOW? Run it before every
evaluation session (participant, device qualification, holdout run). 2026-10-08.

Checks, each PASS / FAIL:
  1 /health answers "ok"
  2 semantic_mode is LIVE (not MOCK, not missing key)
  3 video_ready (ffmpeg present)
  4 the token protection is on (no token -> 401) and the app's token is accepted (200)
  5 /guidance round trip, median of 5 calls <= 1000 ms (DQ6 includes the network)
  6 one /score call (ONE Gemini call, about $0.001) returns all five semantic scores,
    i.e. the model really answers (skip with --no-score)
  7 after that call, no technical metric is abstaining (BRISQUE/PIQE work, i.e. the
    pinned environment is the one running)
Also records framework_version, semantic_model and any release / model_version fields
the server reports, so every session log says which build produced its data.

The token is read from the PQF_API_TOKEN environment variable or mobile/assets/config.env.
It is never printed or written to the log.

Usage (repo root):
  python research/evaluation/check_server.py --url https://<your-app>.up.railway.app
  python research/evaluation/check_server.py --url ... --image data/abo/.../x.jpg
Exit code 0 only if every check passed. A log is written to research/results/server_checks/.
"""
from __future__ import annotations

import argparse
import datetime
import io
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def token() -> str:
    t = os.environ.get("PQF_API_TOKEN", "")
    cfg = REPO / "mobile" / "assets" / "config.env"
    if not t and cfg.exists():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("PQF_API_TOKEN="):
                t = line.split("=", 1)[1].strip().strip('"').strip("'")
    return t


def request(url, method="GET", headers=None, files=None, fields=None, timeout=60):
    body, h = None, dict(headers or {})
    if files or fields:
        b = uuid.uuid4().hex
        buf = io.BytesIO()
        for k, v in (fields or {}).items():
            buf.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, (name, data, mime) in (files or {}).items():
            buf.write(f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{name}\"\r\n"
                      f"Content-Type: {mime}\r\n\r\n".encode() + data + b"\r\n")
        buf.write(f"--{b}--\r\n".encode())
        body, h["Content-Type"] = buf.getvalue(), f"multipart/form-data; boundary={b}"
        method = "POST"
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code, text = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, text = e.code, e.read()
    return code, text, 1000 * (time.perf_counter() - t)


def test_image() -> bytes:
    """A small product-like JPEG (grey box on white), or the --image file."""
    try:
        import cv2
        import numpy as np
        img = np.full((1350, 1080, 3), 245, np.uint8)
        cv2.rectangle(img, (390, 480), (690, 870), (60, 80, 170), -1)
        return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()
    except ImportError:
        sys.exit("Install opencv-python or pass --image <a .jpg>.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--image", type=Path, help="JPEG used for /guidance and /score")
    ap.add_argument("--no-score", action="store_true",
                    help="skip the /score call (then BRISQUE/PIQE are not exercised)")
    a = ap.parse_args()
    base = a.url.rstrip("/")
    tok = token()
    auth = {"X-PQF-Token": tok} if tok else {}
    img = a.image.read_bytes() if a.image else test_image()
    checks, info = [], {}

    def check(name, ok, detail=""):
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail else ""))

    try:
        code, text, ms = request(base + "/health", timeout=90)   # allows a cold start
        h = json.loads(text) if code == 200 else {}
    except Exception as e:
        code, h, ms = 0, {}, 0
        print(f"Cannot reach {base}: {type(e).__name__}: {e}")
    check("1 /health ok", h.get("status") == "ok", f"HTTP {code}, {ms:.0f} ms")
    check("2 semantic model LIVE", h.get("semantic_mode") == "LIVE", h.get("semantic_mode", "-"))
    check("3 video ready", h.get("video_ready") is True, "")
    for k in ("framework_version", "semantic_model", "release", "model_version",
              "prompt_version", "fqs_pass_threshold"):
        if k in h:
            info[k] = h[k]

    c0, _, _ = request(base + "/auth/check")
    c1, _, _ = request(base + "/auth/check", headers=auth)
    check("4 token protection on and app token accepted", c0 == 401 and c1 == 200,
          f"without token HTTP {c0}, with token HTTP {c1}"
          + ("" if tok else "; NO TOKEN FOUND (env PQF_API_TOKEN or mobile/assets/config.env)"))

    times, gcode = [], None
    for _ in range(6):
        gcode, _, ms = request(base + "/guidance", headers=auth,
                               files={"file": ("g.jpg", img, "image/jpeg")},
                               fields={"shot": "main", "rotation": "0"})
        times.append(ms)
    med = statistics.median(times[1:]) if gcode == 200 else float("nan")   # first = warm-up
    check("5 /guidance median <= 1000 ms (5 calls after 1 warm-up)", gcode == 200 and med <= 1000,
          f"HTTP {gcode}, median {med:.0f} ms, all {[round(t) for t in times[1:]]}")
    info["guidance_ms"] = [round(t) for t in times[1:]]

    if not a.no_score:
        code, text, ms = request(base + "/score", headers=auth, timeout=120,
                                 files={"file": ("s.jpg", img, "image/jpeg")})
        r = json.loads(text) if code == 200 else {}
        sem = r.get("semantic") or []
        check("6 /score returns all 5 semantic scores (one model call)",
              code == 200 and len(sem) == 5,
              f"HTTP {code}, {ms:.0f} ms, {len(sem)} semantic, reason={r.get('reason', '')[:80]}")

        # BRISQUE/PIQE only run inside /score, so read the abstain list AFTER it.
        _, text, _ = request(base + "/health", timeout=60)
        ab = (json.loads(text).get("metrics") or {}).get("abstaining", None)
        check("7 no technical metric abstaining after scoring (BRISQUE, PIQE work)",
              ab == [], f"abstaining={ab}")

    ok = all(c["pass"] for c in checks)
    print(f"\n{'READY: the server can produce research data.' if ok else 'NOT READY: fix the FAIL lines before collecting any data.'}")
    if info:
        print("Build:", json.dumps({k: v for k, v in info.items() if k != "guidance_ms"}))
    out = REPO / "research" / "results" / "server_checks"
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    (out / f"check_{stamp}.json").write_text(json.dumps(
        {"time": stamp, "url": base, "ready": ok, "checks": checks, "build": info},
        indent=1), encoding="utf-8")
    sys.exit(0 if ok else 1)
