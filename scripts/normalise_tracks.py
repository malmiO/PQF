"""
normalise_tracks.py  -  bring every track in backend/audio/tracks.csv to the same
loudness, ONCE, with ffmpeg's two-pass loudnorm (EBU R128), into
backend/assets/music/normalised/. The renderer and the preview use only these.

Run from the repo root after adding or replacing tracks:
    python scripts/normalise_tracks.py           (skips files already done)
    python scripts/normalise_tracks.py --force   (redo all)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.audio.catalog import read_rows  # noqa: E402
from backend.audio.settings import (FILES_DIR, LOUDNESS_RANGE, NORMALISED_DIR,  # noqa: E402
                                    TARGET_LUFS, TRUE_PEAK_DB)
from backend.video.builder import ffmpeg_binary  # noqa: E402

FILTER = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK_DB}:LRA={LOUDNESS_RANGE}"


def _measure(ff: str, src: Path) -> dict:
    """Pass 1: measure. loudnorm prints a JSON block on stderr."""
    err = subprocess.run([ff, "-hide_banner", "-nostats", "-i", str(src), "-af",
                          FILTER + ":print_format=json", "-f", "null", "-"],
                         capture_output=True, text=True, timeout=300).stderr
    return json.loads(re.findall(r"\{[^{}]*\}", err, re.S)[-1])


def normalise(ff: str, src: Path, dst: Path) -> dict:
    m = _measure(ff, src)
    second = (f"{FILTER}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
              f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
              f":offset={m['target_offset']}:linear=true:print_format=json")
    dst.parent.mkdir(parents=True, exist_ok=True)
    err = subprocess.run([ff, "-hide_banner", "-nostats", "-y", "-i", str(src), "-af", second,
                          "-ar", "44100", "-c:a", "libmp3lame", "-b:a", "192k", str(dst)],
                         capture_output=True, text=True, timeout=300).stderr
    out = json.loads(re.findall(r"\{[^{}]*\}", err, re.S)[-1])
    return {"before_lufs": float(m["input_i"]), "after_lufs": float(out["output_i"])}


def main(force: bool = False) -> int:
    ff = ffmpeg_binary()
    if not ff:
        print("ffmpeg not found")
        return 1
    rows = read_rows(ROOT)
    if not rows:
        print("No tracks in backend/audio/tracks.csv")
        return 1
    bad = 0
    print(f"{'track_id':22} {'before':>8} {'after':>8}  file")
    for r in rows:
        src = ROOT / FILES_DIR / r["file"]
        dst = ROOT / NORMALISED_DIR / r["file"]
        if not src.exists():
            print(f"{r['track_id']:22} {'':>8} {'':>8}  MISSING {src.relative_to(ROOT)}")
            bad += 1
            continue
        if dst.exists() and not force:
            print(f"{r['track_id']:22} {'':>8} {'':>8}  already done")
            continue
        res = normalise(ff, src, dst)
        print(f"{r['track_id']:22} {res['before_lufs']:8.1f} {res['after_lufs']:8.1f}  "
              f"{dst.relative_to(ROOT)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main("--force" in sys.argv))
