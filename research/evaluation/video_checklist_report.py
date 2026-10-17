"""
video_checklist_report.py  -  run the EXISTING measured "Ready to post" checklist
(backend/video/measure.py) on finished MP4s and summarise met / not met per item, with a
Wilson 95 % CI across videos (2026-10-15). Changes no video code.

Each MP4 needs its plan sidecar <name>.json with the render record under "render", which is
what the server's /video flow and scripts/review_render.py both write.

  python research/evaluation/video_checklist_report.py --dir <folder of mp4+json> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evalcommon import wilson, write_csv                      # noqa: E402
from backend.video.builder import ffmpeg_binary              # noqa: E402
from backend.video.measure import checklist, measure_video   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--glob", default="*.mp4")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    ff = ffmpeg_binary() or "ffmpeg"
    per_video, per_item, skipped = [], defaultdict(list), []
    for mp4 in sorted(a.dir.glob(a.glob)):
        side = mp4.with_suffix(".json")
        if not side.exists():
            skipped.append((mp4.name, "no sidecar json"))
            continue
        plan = json.loads(side.read_text(encoding="utf-8"))
        record = plan.get("render")
        if not record or not record.get("timeline"):
            skipped.append((mp4.name, "sidecar has no render timeline (older renderer)"))
            continue
        items = checklist(plan, record, measure_video(mp4, record, ff))
        for it in items:
            per_video.append({"video": mp4.name, "rule": it["rule"], "met": it["met"],
                              "measured": it["measured"], "threshold": it["threshold"]})
            per_item[it["rule"]].append(it["met"])
    summary = []
    for rule, v in per_item.items():
        k, n = sum(v), len(v)
        lo, hi = wilson(k, n)
        summary.append({"item": rule, "videos": n, "met": k, "not_met": n - k,
                        "met_rate": round(k / n, 3), "wilson_95ci_low": round(lo, 3),
                        "wilson_95ci_high": round(hi, 3)})
    a.out.mkdir(parents=True, exist_ok=True)
    pre = f"{a.label}_" if a.label else ""
    write_csv(a.out / f"{pre}video_checklist_per_video.csv", per_video)
    write_csv(a.out / f"{pre}video_checklist_summary.csv", summary)
    md = [(f"> **{a.label}**: videos are review renders from test-img/review, not participant "
           "videos.\n" if a.label else ""), "# Video checklist (measured from the MP4)\n",
          f"Videos checked: {len({r['video'] for r in per_video})}; skipped: {len(skipped)}.\n",
          "| item | videos | met | not met | met rate | Wilson 95% CI |", "|---|---|---|---|---|---|"]
    md += [f"| {s['item']} | {s['videos']} | {s['met']} | {s['not_met']} | {s['met_rate']} | "
           f"{s['wilson_95ci_low']}-{s['wilson_95ci_high']} |" for s in summary]
    md += ["", "## Per video", "", "| video | item | met | measured | threshold |", "|---|---|---|---|---|"]
    md += [f"| {r['video']} | {r['rule']} | {'met' if r['met'] else 'NOT MET'} | {r['measured']} "
           f"| {r['threshold']} |" for r in per_video]
    if skipped:
        md += ["", "Skipped: " + "; ".join(f"{n} ({why})" for n, why in skipped)]
    (a.out / f"{pre}video_checklist.md").write_text("\n".join(md), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(md[:14]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
