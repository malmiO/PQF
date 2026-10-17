"""
check_tracks.py  -  fail loudly if the music library is not ready to use.

Fails (exit 1) when: a file is missing; a licence is not CC0, CC-BY-4.0 or
Pixabay; a licence is NonCommercial or NoDerivatives; a CC BY row has no
attribution; a track is shorter than 16 s; a mood the app offers has no track;
a track has not been loudness normalised; a test tone is still listed.

Run from the repo root:   python scripts/check_tracks.py
(--deployed checks only the normalised copies, for a server that ships only those.)
The Railway build runs it, so a deployment cannot ship with an unready library.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.audio.catalog import audio_seconds, read_rows, validate  # noqa: E402
from backend.audio.settings import FILES_DIR, NORMALISED_DIR  # noqa: E402


def main(deployed: bool = False) -> int:
    src = NORMALISED_DIR if deployed else FILES_DIR
    rows = read_rows(ROOT)
    print(f"{'track_id':20} {'mood':8} {'licence':10} {'secs':>5} {'bpm':>5} {'norm':4}  title / artist")
    for r in rows:
        f = ROOT / src / r.get("file", "")
        secs = audio_seconds(f) if f.exists() else None
        norm = "yes" if (ROOT / NORMALISED_DIR / r.get("file", "")).exists() else "no"
        print(f"{r.get('track_id', ''):20} {r.get('mood', ''):8} {r.get('licence', ''):10} "
              f"{'-' if secs is None else f'{secs:5.1f}':>5} {r.get('bpm', '') or '-':>5} {norm:4}  "
              f"{r.get('title', '')} / {r.get('artist', '')}")
    problems = validate(rows, ROOT, files_dir=src, check_normalised=not deployed)
    if problems:
        print(f"\nNOT READY: {len(problems)} problem(s)")
        for tid, msg in problems:
            print(f"  - {tid}: {msg}")
        return 1
    print("\nREADY: every track is present, licensed for commercial use, credited where "
          "required, long enough and normalised; every mood has a track.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--deployed" in sys.argv))
