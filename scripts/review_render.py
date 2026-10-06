"""
review_render.py  -  render sample videos from the real keychain photos and save a
contact sheet (one frame per second) for each, so video changes are LOOKED AT,
not only tested.

Run from the repo root:
    python scripts/review_render.py <tag>
Writes test-img/review/<sample>_<tag>.jpg (contact sheet), <sample>_<tag>.mp4 and
<sample>_<tag>.json (the plan, with whatever the renderer recorded).

No model call: the callout points for the books keychain are the ones the live
check measured on 2026-10-06 (check_callouts.py on the same photo).
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.video.plan import build_plan, ProductInfo  # noqa: E402
from backend.video.promo import render_plan  # noqa: E402
from backend.api.video_api import _guard_callouts  # noqa: E402
from backend.video.measure import checklist as measured_checklist, measure_video  # noqa: E402

IMG = ROOT / "test-img"
OUT = IMG / "review"
W = "WhatsApp Image 2026-10-05 at "

SAMPLES = {
    # books keychain, vertical, three located features on the main shot
    "books_vertical": dict(
        files=[("hero_shot", "1.39.48 PM (2)"), ("angle_shot", "1.39.49 PM (1)"),
               ("angle_shot", "1.39.49 PM (2)")],
        info=ProductInfo(name="Teacher keychain", price="Rs. 450", category="Accessories",
                         features=["Silver clasp", "Red apple", "Painted letters"]),
        fmt="vertical", mood="calm",
        located={"points": [(0.48, 0.25), (0.48, 0.41), (0.52, 0.54)],
                 "source": "model", "error": ""}),
    # the J6+ failure: all three points on one spot -> the guard must use captions
    "books_converged": dict(
        files=[("hero_shot", "1.39.48 PM (2)"), ("angle_shot", "1.39.49 PM (1)"),
               ("angle_shot", "1.39.49 PM (2)")],
        info=ProductInfo(name="Teacher keychain", price="Rs. 450", category="Accessories",
                         features=["Silver clasp", "Red apple", "Painted letters"]),
        fmt="vertical", mood="upbeat",
        located={"points": [(0.50, 0.55), (0.51, 0.55), (0.50, 0.56)],
                 "source": "model", "error": ""}),
    # thank-you keychain, square, no features
    "thankyou_square": dict(
        files=[("hero_shot", "2.11.27 PM (1)"), ("angle_shot", "2.11.28 PM"),
               ("angle_shot", "2.11.29 PM"), ("detail_shot", "2.11.28 PM (1)")],
        info=ProductInfo(name="Thank you keychain", price="Rs. 400", category="Handmade"),
        fmt="square", mood="upbeat", located=None),
    # apple keychain, vertical, no features
    "apple_vertical": dict(
        files=[("hero_shot", "11.54.46 AM (1)"), ("angle_shot", "11.54.45 AM (1)"),
               ("angle_shot", "11.54.47 AM (1)"), ("detail_shot", "11.54.48 AM")],
        info=ProductInfo(name="Teacher's Day apple keychain", price="Rs. 350",
                         category="Accessories"),
        fmt="vertical", mood="elegant", located=None),
}


def contact_sheet(mp4: Path, out: Path, tile_w: int = 270):
    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    tiles = []
    for sec in range(0, int(n / fps) + 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, min(n - 1, int(sec * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        t = cv2.resize(fr, (tile_w, int(h * tile_w / w)), interpolation=cv2.INTER_AREA)
        cv2.rectangle(t, (0, 0), (52, 24), (0, 0, 0), -1)
        cv2.putText(t, f"{sec}s", (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(t)
    cap.release()
    per_row = 6
    blank = np.full_like(tiles[0], 255)
    while len(tiles) % per_row:
        tiles.append(blank)
    rows = [np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)]
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])


def main(tag: str):
    OUT.mkdir(parents=True, exist_ok=True)
    for name, s in SAMPLES.items():
        paths = [IMG / f"{W}{f}.jpeg" for _, f in s["files"]]
        images = [(role, i) for i, (role, _) in enumerate(s["files"])]
        info = s["info"]
        info.mood = s["mood"]
        located, guard = _guard_callouts(paths[0].read_bytes(), info.features,
                                         s["located"], s["fmt"])
        plan = build_plan(images, info, s["fmt"], located,
                          {"mood": s["mood"], "track_id": None})
        plan["callout_guard"] = guard
        mp4 = OUT / f"{name}_{tag}.mp4"
        r = render_plan(plan, paths, mp4)
        record = getattr(r, "record", None)
        if record:
            plan["render"] = record
            m = measure_video(mp4, record)
            record["measurement"] = m
            plan["checklist"] = measured_checklist(plan, record, m)
            for c in plan["checklist"]:
                print(f"   {'MET ' if c['met'] else 'NOT '} {c['rule']}: {c['measured']} "
                      f"(threshold {c['threshold']})")
            for s in m["shots"]:
                print(f"     shot {s['shot']} {s['kind']:6} fill {s['fill']:.2f} "
                      f"cx {s['cx']:.3f} cy {s['cy']:.3f} bgL {s['bg_l']}")
        (OUT / f"{name}_{tag}.json").write_text(json.dumps(plan, indent=1, default=str),
                                                encoding="utf-8")
        contact_sheet(mp4, OUT / f"{name}_{tag}.jpg")
        print(f"{name}: {r.duration_seconds}s -> {OUT / (name + '_' + tag + '.jpg')}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample")
