"""
smoke_remote.py  -  check a deployed PQF server end to end, with timings.

Run from the repo root after deploying:
    python scripts/smoke_remote.py https://YOUR-APP.up.railway.app YOUR_TOKEN [photos...]

Steps: GET /health, GET /auth/check (token), POST /batch with the keychain set
(ONE Gemini call per photo), POST /video/plan with the selected set (one more call
only if features are sent; none here), POST /video/render, GET /video/plan (the
measured checklist) and one POST /study/log entry marked product "SMOKE" (the
study export skips it). Default photos: the books keychain set in test-img/.
"""
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = [ROOT / "test-img" / f"WhatsApp Image 2026-10-05 at {n}.jpeg"
           for n in ("1.39.48 PM (2)", "1.39.49 PM (1)", "1.39.49 PM (2)",
                     "1.39.49 PM", "1.39.50 PM")]


def step(name, fn):
    t0 = time.time()
    try:
        out = fn()
        print(f"  OK    {name:28s} {time.time() - t0:6.1f} s")
        return out
    except Exception as e:
        print(f"  FAIL  {name:28s} {time.time() - t0:6.1f} s   {e}")
        sys.exit(1)


def main(url: str, token: str, photos: list) -> None:
    url = url.rstrip("/")
    H = {"X-PQF-Token": token}

    def ok(r):
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        return r

    print(f"SERVER {url}")
    h = step("GET /health", lambda: ok(requests.get(f"{url}/health", timeout=60)).json())
    print(f"        semantic_mode={h.get('semantic_mode')}  abstaining="
          f"{(h.get('metrics') or {}).get('abstaining')}  video_ready={h.get('video_ready')}  "
          f"music={h.get('music_tracks')}  test_tones={h.get('test_tones')}")
    step("GET /auth/check", lambda: ok(requests.get(f"{url}/auth/check", headers=H, timeout=30)))

    files = [("files", (p.name, p.read_bytes(), "image/jpeg")) for p in photos]
    b = step(f"POST /batch ({len(photos)} photos)", lambda: ok(requests.post(
        f"{url}/batch", files=files, headers=H, timeout=300)).json())
    sel = sorted([i for i in b["images"] if i["selected"]],
                 key=lambda i: {"hero_shot": 0, "angle_shot": 1, "detail_shot": 2}.get(i["role"], 3))
    print(f"        certified={b['certified']}  set={[(i['index'] + 1, i['role']) for i in sel]}  "
          f"missing={[m['role'] for m in b['missing']]}")
    if not sel:
        print("  STOP  nothing selected, cannot test the video")
        sys.exit(1)

    plan = step("POST /video/plan", lambda: ok(requests.post(
        f"{url}/video/plan", headers=H, timeout=120,
        files=[("files", (photos[i["index"]].name, photos[i["index"]].read_bytes(), "image/jpeg"))
               for i in sel],
        data={"roles": ",".join(i["role"] for i in sel), "product_name": "Smoke test keychain",
              "price": "Rs. 450", "shop": "Smoke Shop", "contact": "000"})).json())
    v = step("POST /video/render", lambda: ok(requests.post(
        f"{url}/video/render", headers=H, data={"plan_id": plan["plan_id"]}, timeout=300)))
    print(f"        {len(v.content) / 1e6:.1f} MB, {v.headers.get('x-video-duration')} s, "
          f"audio={v.headers.get('x-video-audio')}, checklist {v.headers.get('x-video-checklist')}")
    saved = step("GET /video/plan (measured)", lambda: ok(requests.get(
        f"{url}/video/plan/{plan['plan_id']}", headers=H, timeout=30)).json())
    for c in saved.get("checklist", []):
        print(f"        {'MET' if c['met'] else 'NOT'}  {c['rule']}: {c.get('measured')}")

    entry = {"event": "session_start", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
             "participant": "P99", "condition": "GUIDED", "product": "SMOKE", "session": 1}
    step("POST /study/log", lambda: ok(requests.post(
        f"{url}/study/log", headers={**H, "Content-Type": "application/json"},
        data=json.dumps(entry), timeout=30)))
    print("DONE")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    paths = [Path(p) for p in sys.argv[3:]] or [p for p in DEFAULT if p.exists()]
    main(sys.argv[1], sys.argv[2], paths)
