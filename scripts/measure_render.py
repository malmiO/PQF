"""
measure_render.py  -  time and peak memory of one video render, plus a contact
sheet, so renderer changes are judged on numbers AND on the picture.

Run from the repo root:
    python scripts/measure_render.py <tag> main.jpg angle1.jpg angle2.jpg detail.jpg
Writes test-img/review/render_<tag>.mp4 and render_<tag>.jpg (one frame per second).
Peak memory includes ffmpeg. Needs psutil (development only).
"""
import sys
import threading
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.video.builder import ffmpeg_binary  # noqa: E402
from backend.video.plan import ProductInfo, build_plan  # noqa: E402
from backend.video.promo import render_plan  # noqa: E402
from review_render import contact_sheet  # noqa: E402


def main(tag: str, photos: list) -> None:
    proc = psutil.Process()
    peak, stop = [proc.memory_info().rss], [False]

    def watch():
        while not stop[0]:
            rss = proc.memory_info().rss
            for c in proc.children(recursive=True):
                try:
                    rss += c.memory_info().rss
                except psutil.Error:
                    pass
            peak[0] = max(peak[0], rss)
            time.sleep(0.02)

    roles = ["hero_shot", "angle_shot", "angle_shot", "detail_shot"][:len(photos)]
    plan = build_plan(list(zip(roles, range(len(photos)))),
                      ProductInfo(name="Teacher keychain", price="Rs. 450",
                                  shop="Malmi Crafts", contact="077 123 4567"),
                      "vertical", None, {"mood": "calm", "track_id": None})
    out = ROOT / "test-img" / "review" / f"render_{tag}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    base = proc.memory_info().rss
    threading.Thread(target=watch, daemon=True).start()
    c0, t0 = time.process_time(), time.time()
    r = render_plan(plan, [Path(p) for p in photos], out, ffmpeg_bin=ffmpeg_binary())
    wall, cpu = time.time() - t0, time.process_time() - c0
    stop[0] = True
    contact_sheet(out, out.with_suffix(".jpg"), tile_w=230)
    print(f"{tag}: render {wall:.1f} s wall, {cpu:.1f} s python CPU, video {r.duration_seconds} s")
    print(f"{tag}: memory before {base / 2**20:.0f} MB, peak incl. ffmpeg {peak[0] / 2**20:.0f} MB")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
