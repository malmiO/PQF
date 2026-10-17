"""
crosscheck_contact_sheets.py  -  one PDF page per CANDIDATE set (kept and dropped) so the product
groupings of crosscheck_sets.py can be checked by eye (2026-10-16).

  python research/evaluation/crosscheck_contact_sheets.py
  -> research/results/crosscheck/set_contact_sheets.pdf   (git-ignored; participants' own photos)

Each page: the set label, how many photos, how many distinct views, KEPT / DROPPED, and every
photo as a thumbnail captioned with its file name. Reads candidate_sets.csv and
candidate_photos.csv written by `crosscheck_sets.py --list`. Nothing is scored.
"""
from __future__ import annotations

import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                         # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages    # noqa: E402
from PIL import Image, ImageOps                         # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "research" / "results" / "crosscheck"
COLS = 3


def thumb(path: Path, side: int = 700):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((side, side))
    return im


def main() -> int:
    sets = list(csv.DictReader(open(OUT / "candidate_sets.csv", newline="", encoding="utf-8")))
    photos = list(csv.DictReader(open(OUT / "candidate_photos.csv", newline="", encoding="utf-8")))
    out = OUT / "set_contact_sheets.pdf"
    with PdfPages(out, metadata={"Title": "Cross-check candidate sets (private)"}) as pdf:
        for s in sets:
            mem = [p for p in photos if p["set_id"] == s["set_id"]]
            kept = s["kept"] in ("True", "true", "1")
            rows = max(1, -(-len(mem) // COLS))
            fig = plt.figure(figsize=(8.27, 11.69))
            fig.suptitle(f"{s['set_id']}   -   {'KEPT' if kept else 'DROPPED'}", fontsize=16,
                         weight="bold", color="#1a7f37" if kept else "#b3261e", y=0.975)
            fig.text(0.5, 0.945, f"{s['photos']} photos, {s['distinct_views']} distinct views, "
                     f"{s['group']}   (rule: >= 6 photos and >= 2 views)", ha="center", fontsize=10)
            top, bottom = 0.92, 0.04
            cell_h = (top - bottom) / max(rows, 4)
            for i, p in enumerate(mem):
                col, row = i % COLS, i // COLS
                ax = fig.add_axes([0.03 + col * 0.325, top - (row + 1) * cell_h + 0.025,
                                   0.30, cell_h - 0.045])
                ax.imshow(thumb(REPO / p["path"]))
                ax.axis("off")
                ax.set_title(f"#{i + 1}  {Path(p['path']).name}", fontsize=7, loc="left")
            pdf.savefig(fig)
            plt.close(fig)
    print(f"{len(sets)} pages -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
