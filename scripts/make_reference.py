"""
make_reference.py  -  the "good shot" examples the app shows, made from the
owner's OWN photos, and only if the framework certifies them (v1.1.0, Step 6).

Run from the repo root (reads GEMINI_API_KEY from .env, never prints it). Uses
one model call per photo:
    python scripts/make_reference.py photo1.jpg photo2.jpg ...

Scores the photos exactly as POST /batch does. If the set is certified, the
selected main shot, the first selected angle and the detail shot are resized and
written to mobile/assets/reference/{main,angle,detail}.jpg. If it is not
certified, nothing is written and the reason is printed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

import cv2  # noqa: E402

OUT = ROOT / "mobile" / "assets" / "reference"
WIDTH = 720


def main(paths: list) -> int:
    from backend.api.main import _platform_format
    from backend.pqf.pipeline.pipeline import process_batch
    photos = [Path(p) for p in paths]
    result = process_batch([(_platform_format(p.read_bytes()), str(p)) for p in photos])
    for d in result.all_decisions:
        print(f"  {Path(d.path).name}: role={d.role} fqs={d.fqs:.3f} passed={d.passed}")
    from backend.pqf.technical import metric_status
    abstaining = metric_status().get("abstaining") or []
    if abstaining:
        print(f"NOT TRUSTED, nothing written: {abstaining} abstained (scored 1.0), so these "
              "scores are inflated. Use the pinned environment (requirements-deploy.txt).")
        return 1
    if not result.certified:
        print("NOT CERTIFIED, nothing written:", (result.recapture or {}).get("instruction", ""))
        return 1
    chosen = {}
    for role, name in (("hero_shot", "main"), ("angle_shot", "angle"), ("detail_shot", "detail")):
        items = result.role_sets.get(role) or []
        if items:
            chosen[name] = Path(items[0].path)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, src in chosen.items():
        img = cv2.imread(str(src))
        h, w = img.shape[:2]
        img = cv2.resize(img, (WIDTH, int(h * WIDTH / w)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(OUT / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        print(f"  {name}.jpg <- {src.name}")
    print("CERTIFIED: reference images written to", OUT)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1:]))
