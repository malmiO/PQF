"""rescore_study.py - re-score exported study photos OFFLINE.

If live scoring failed during a session (e.g. the free Gemini tier was slow or
returned 503), the photos are still saved on the phone and in the export
(study/photos/<participant>_<condition>/<sha256>.jpg). This tool re-scores each
one with the SAME pipeline the server uses, so no session's photos are wasted.

It reads GEMINI_API_KEY exactly as the server does (repo-root .env + environ),
uses the pinned model, and never prints the key. Set PQF_SEMANTIC_MOCK=1 to do a
keyless dry run. It changes no criterion, weight, threshold, prompt or model.

Usage (pinned venv, from the repo root):
    .venv/Scripts/python.exe research/tools/rescore_study.py \
        --photos-dir path/to/export/study --out rescored.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
load_dotenv(os.path.join(_REPO_ROOT, ".env"))
load_dotenv()

from backend.pqf.pipeline import score_image  # noqa: E402


def _iter_photos(root: Path):
    """Yield (participant, condition, hash, path) for every study photo."""
    photos_dir = root / "photos" if (root / "photos").is_dir() else root
    for p in sorted(photos_dir.rglob("*.jpg")):
        parent = p.parent.name           # "<participant>_<condition>"
        participant, _, condition = parent.partition("_")
        yield participant, condition, p.stem, p


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-score exported study photos offline.")
    ap.add_argument("--photos-dir", required=True,
                    help="The exported 'study' folder (or its 'photos' subfolder).")
    ap.add_argument("--out", default="rescored.json", help="Output JSON path.")
    args = ap.parse_args()

    root = Path(args.photos_dir)
    if not root.exists():
        print(f"not found: {root}")
        return 2

    mock = os.environ.get("PQF_SEMANTIC_MOCK") == "1"
    key = bool(os.environ.get("GEMINI_API_KEY"))
    print(f"mode: {'MOCK' if mock else 'LIVE'}  (GEMINI_API_KEY present: {key})")

    rows, ok, fail = [], 0, 0
    t0 = time.time()
    for participant, condition, stem, path in _iter_photos(root):
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != stem:
            print(f"WARNING: {path.name} hash mismatch (file renamed?)")
        d = score_image(data, str(path))
        passed = bool(getattr(d, "passed", False))
        ok += passed
        fail += (not passed)
        rows.append({
            "participant": participant, "condition": condition,
            "hash": digest,
            "tqs": round(getattr(d, "tqs", 0.0), 4),
            "sqs": round(getattr(d, "sqs", 0.0), 4),
            "fqs": round(getattr(d, "fqs", 0.0), 4),
            "role": getattr(d, "role", "reject"),
            "passed": passed,
            "reason": getattr(d, "reason", ""),
            "model_version": getattr(d, "model_version", ""),
        })
        print(f"  {participant}/{condition} {digest[:10]}… "
              f"fqs={rows[-1]['fqs']} role={rows[-1]['role']} passed={passed}")

    Path(args.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"\nscored {len(rows)} photos in {round(time.time() - t0)}s "
          f"(passed={ok}, not-passed={fail}) -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
