"""
catalog.py  -  read and validate the music manifest (backend/audio/tracks.csv).

Licences are accepted by a person when the track is downloaded; this module only
checks that what was recorded is complete and allowed, and fails loudly if not.
"""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path

from .settings import (ALLOWED_LICENCES, APP_MOODS, FILES_DIR, FORBIDDEN_LICENCE_PARTS,
                       MANIFEST, MIN_TRACK_SECONDS, NORMALISED_DIR, TEST_LICENCE)

COLUMNS = ["track_id", "mood", "title", "artist", "source_url", "licence", "licence_url",
           "downloaded_on", "attribution", "file", "duration_s", "bpm"]


def read_rows(base: Path, manifest: Path | None = None) -> list:
    p = manifest or (base / MANIFEST)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def is_cc_by(licence: str) -> bool:
    return licence.upper().startswith("CC-BY")


def attribution_line(row: dict) -> str:
    """The credit appended to the post caption for CC BY tracks."""
    return (f"Music: {row.get('title', '')} by {row.get('artist', '')}, CC BY 4.0, "
            f"{row.get('source_url', '')}").strip().rstrip(",")


def ffprobe_binary() -> str:
    """ffprobe next to the ffmpeg the video layer resolves, else from PATH."""
    try:
        from ..video.builder import ffmpeg_binary
        ff = ffmpeg_binary()
        if ff:
            cand = Path(ff).with_name(Path(ff).name.replace("ffmpeg", "ffprobe"))
            if cand.exists():
                return str(cand)
    except Exception:
        pass
    return "ffprobe"


def audio_seconds(path: Path, ffprobe: str | None = None) -> float | None:
    ffprobe = ffprobe or ffprobe_binary()
    try:
        out = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True,
                             timeout=30).stdout.strip()
        return float(out)
    except Exception:
        return None


def validate(rows: list, base: Path, duration_of=None, check_normalised: bool = True) -> list:
    """Problems, as (track_id, message). Empty means the library is ready.
    `duration_of(path)` is injectable for tests."""
    duration_of = duration_of or audio_seconds
    problems = []
    for r in rows:
        tid = r.get("track_id") or "(no id)"
        lic = r.get("licence", "")
        f = base / FILES_DIR / r.get("file", "")
        if not r.get("file") or not f.exists():
            problems.append((tid, f"file missing: {FILES_DIR}/{r.get('file', '')}"))
        if lic == TEST_LICENCE:
            problems.append((tid, "test tone, not music: remove before the evaluation"))
        elif lic not in ALLOWED_LICENCES:
            problems.append((tid, f"licence '{lic}' is not one of {', '.join(ALLOWED_LICENCES)}"))
        parts = lic.upper().replace("_", "-").replace(" ", "-").split("-")
        if any(p in parts for p in FORBIDDEN_LICENCE_PARTS):
            problems.append((tid, f"licence '{lic}' is NonCommercial or NoDerivatives"))
        if is_cc_by(lic) and not r.get("attribution"):
            problems.append((tid, "CC BY track with an empty attribution"))
        if is_cc_by(lic) and not (r.get("artist") and r.get("source_url")):
            problems.append((tid, "CC BY track needs artist and source_url for the credit"))
        if f.exists():
            secs = duration_of(f)
            if secs is None:
                problems.append((tid, "duration could not be read"))
            elif secs < MIN_TRACK_SECONDS:
                problems.append((tid, f"only {secs:.1f} s long (needs {MIN_TRACK_SECONDS:.0f} s)"))
            if check_normalised and not (base / NORMALISED_DIR / r["file"]).exists():
                problems.append((tid, "not normalised yet: run python scripts/normalise_tracks.py"))
    for mood in APP_MOODS:
        if not any(r.get("mood") == mood and r.get("licence") in ALLOWED_LICENCES
                   for r in rows):
            problems.append((f"mood:{mood}", f"no licensed track for the '{mood}' mood"))
    return problems
