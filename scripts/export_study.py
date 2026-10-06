"""
export_study.py  -  study_log.jsonl -> one CSV row per participant x condition.

Run from the repo root:
    python scripts/export_study.py [research/results/study_log.jsonl] [out.csv]
Default output: research/results/study_export.csv

Per session (participant, condition), from the FIRST /batch result after capture
(the photos as the participant took them, before any retake):
  mean_tqs, mean_sqs, mean_fqs   over every photo in that batch
  certified_first                 whether that first set passed the gate
  overlap_n / overlap_ratio       how many of the participant's own four picks the
                                  framework also selected (ratio of own picks)
  role_agreement                  share of own picks whose role matches the role
                                  the framework gave that photo
and from the session as a whole: number of /batch calls, final certification,
seconds from session start to capture end and to video ready.
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.api.study_api import abba_order  # noqa: E402

COLUMNS = ["participant", "condition", "order", "product", "n_photos", "mean_tqs",
           "mean_sqs", "mean_fqs", "certified_first", "certified_final", "n_batches",
           "own_picks_n", "framework_n", "overlap_n", "overlap_ratio", "role_agreement",
           "capture_seconds", "video_seconds"]
SLOT_ROLE = {"main": "hero_shot", "angle1": "angle_shot", "angle2": "angle_shot",
             "detail": "detail_shot"}


def _t(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def _secs(a, b):
    ta, tb = _t(a), _t(b)
    return round((tb - ta).total_seconds(), 1) if ta and tb else ""


def rows_from(lines: list) -> list:
    sessions = {}
    for e in lines:
        key = (e["participant"], e["condition"])
        sessions.setdefault(key, []).append(e)
    out = []
    for (pid, cond), events in sorted(sessions.items()):
        events.sort(key=lambda e: e.get("timestamp", ""))
        batches = [e for e in events if e["event"] == "batch_result"]
        first = batches[0] if batches else {}
        photos = first.get("photos", [])
        picks = next((e.get("own_picks", {}) for e in events if e["event"] == "own_picks"), {})
        selected = {s["hash"]: s["role"] for s in first.get("framework_selection", [])}
        roles = {p["hash"]: p.get("role", "") for p in photos}
        own = set(picks.values())
        overlap = len(own & set(selected))
        agree = sum(1 for slot, h in picks.items() if roles.get(h) == SLOT_ROLE.get(slot))
        times = {}
        for e in events:
            times.update({k: v for k, v in (e.get("times") or {}).items() if v})
        start = times.get("session_start") or events[0].get("timestamp")
        mean = lambda k: round(sum(p[k] for p in photos) / len(photos), 4) if photos else ""
        order = abba_order(pid)
        out.append({
            "participant": pid, "condition": cond,
            "order": order.index(cond) + 1 if cond in order else "",
            "product": events[0].get("product", ""), "n_photos": len(photos),
            "mean_tqs": mean("tqs"), "mean_sqs": mean("sqs"), "mean_fqs": mean("fqs"),
            "certified_first": (first.get("gate") or {}).get("certified", ""),
            "certified_final": (batches[-1].get("gate") or {}).get("certified", "") if batches else "",
            "n_batches": len(batches), "own_picks_n": len(own), "framework_n": len(selected),
            "overlap_n": overlap, "overlap_ratio": round(overlap / len(own), 3) if own else "",
            "role_agreement": round(agree / len(picks), 3) if picks else "",
            "capture_seconds": _secs(start, times.get("capture_end")),
            "video_seconds": _secs(start, times.get("video_ready")),
        })
    return out


def main(src: Path, dst: Path) -> int:
    lines = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = rows_from(lines)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(dst, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} session(s) -> {dst}")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    src = Path(a[0]) if a else ROOT / "research" / "results" / "study_log.jsonl"
    dst = Path(a[1]) if len(a) > 1 else ROOT / "research" / "results" / "study_export.csv"
    sys.exit(main(src, dst))
