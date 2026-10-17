"""
blind_pack_pdf.py  -  printable blind packs for the photographers (2026-10-15).

One PDF per photographer. A page shows ONLY photos, a neutral title and tick boxes: no scores,
no condition names, no file names, no hashes. Everything that could identify a condition stays
in the private key CSVs written by make_blind_packs.py.

Pages
  1. instructions (identical for every photographer)
  2. one page per PAIR: photo A (left) and photo B (right), boxes for "A is better / B is
     better / no difference" and a 1-5 strength (1 = barely, 5 = clearly better)
  3. per PRODUCT: contact sheets of EVERY photo of that product, each numbered, then a pick
     page: the number of the best MAIN, ANGLE 1, ANGLE 2 and DETAIL photo

Built with matplotlib (already in .venv-eval), so nothing new is installed. EXIF orientation
is applied, so a photo is drawn the way the phone showed it.
"""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt                      # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from PIL import Image, ImageOps                       # noqa: E402

PAGE = (8.27, 11.69)          # A4 portrait, inches
MAX_SIDE = 1100               # px, keeps the PDF small


def load(path: Path):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    return im


def _page():
    fig = plt.figure(figsize=PAGE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, PAGE[0])
    ax.set_ylim(0, PAGE[1])
    ax.axis("off")
    return fig, ax


def _fit(ax, im, x, y, w, h):
    """Draw im inside the box (x, y, w, h) inches, aspect kept, centred."""
    iw, ih = im.size
    k = min(w / iw, h / ih)
    dw, dh = iw * k, ih * k
    ax.imshow(im, extent=(x + (w - dw) / 2, x + (w + dw) / 2, y + (h - dh) / 2, y + (h + dh) / 2),
              aspect="auto", zorder=1)
    ax.set_xlim(0, PAGE[0])
    ax.set_ylim(0, PAGE[1])


def _box(ax, x, y, label):
    ax.add_patch(plt.Rectangle((x, y), 0.28, 0.28, fill=False, lw=1.4, zorder=2))
    ax.text(x + 0.38, y + 0.04, label, fontsize=12, va="bottom")


def instructions_page(pdf, photographer: str, title: str):
    fig, ax = _page()
    ax.text(0.8, 10.7, title, fontsize=20, weight="bold")
    ax.text(0.8, 10.2, f"Photographer: {photographer}", fontsize=13)
    lines = [
        "You will see photographs of products taken with a phone.",
        "",
        "Part 1 - pairs. For each pair, tick which photo you would rather use to sell the",
        "product online (A, B, or no difference), then tick how clearly better it is:",
        "1 = barely better ... 5 = clearly better. Judge only the photographs.",
        "",
        "Part 2 - products. Every photo of a product is shown and numbered. Write the number",
        "of the photo you would use as the MAIN picture, as ANGLE 1, as ANGLE 2 and as the",
        "DETAIL picture. Use each photo at most once.",
        "",
        "Work alone. Do not discuss the photos until both of you have finished.",
    ]
    for i, t in enumerate(lines):
        ax.text(0.8, 9.3 - 0.42 * i, t, fontsize=12)
    pdf.savefig(fig)
    plt.close(fig)


def pair_page(pdf, n: int, total: int, ref: str, a: Path, b: Path):
    fig, ax = _page()
    ax.text(0.5, 11.2, f"Pair {n} of {total}", fontsize=16, weight="bold")
    ax.text(7.7, 11.2, f"ref {ref}", fontsize=9, ha="right", color="0.45")
    for lab, p, x in (("A", a, 0.4), ("B", b, 4.25)):
        ax.text(x + 1.7, 10.65, lab, fontsize=22, weight="bold", ha="center")
        _fit(ax, load(p), x, 3.1, 3.6, 7.3)
    ax.text(0.5, 2.55, "Which photo would you rather use?", fontsize=12, weight="bold")
    _box(ax, 0.5, 1.95, "A")
    _box(ax, 2.0, 1.95, "B")
    _box(ax, 3.5, 1.95, "No difference")
    ax.text(0.5, 1.45, "How clearly better?  (1 = barely, 5 = clearly)", fontsize=12, weight="bold")
    for i in range(1, 6):
        _box(ax, 0.5 + (i - 1) * 1.1, 0.85, str(i))
    pdf.savefig(fig)
    plt.close(fig)


def contact_pages(pdf, product: str, items: list):
    """items: [(number, Path)]; 6 per page (2 columns x 3 rows)."""
    per = 6
    for start in range(0, len(items), per):
        fig, ax = _page()
        ax.text(0.5, 11.2, f"Product {product}: all photos", fontsize=15, weight="bold")
        for i, (num, path) in enumerate(items[start:start + per]):
            col, row = i % 2, i // 2
            x, y = 0.5 + col * 3.85, 7.45 - row * 3.6
            _fit(ax, load(path), x, y, 3.6, 3.4)
            ax.text(x + 0.05, y + 3.05, f"{num}", fontsize=22, weight="bold", color="white",
                    bbox=dict(facecolor="black", alpha=0.75, pad=3), zorder=3)
        pdf.savefig(fig)
        plt.close(fig)


def pick_page(pdf, product: str, n_photos: int):
    fig, ax = _page()
    ax.text(0.5, 11.2, f"Product {product}: your picks", fontsize=16, weight="bold")
    ax.text(0.5, 10.6, f"Write the NUMBER of the photo (1-{n_photos}). Use each photo once.",
            fontsize=12)
    for i, role in enumerate(("MAIN picture", "ANGLE 1", "ANGLE 2", "DETAIL picture")):
        y = 9.4 - i * 1.0
        ax.text(0.5, y, role, fontsize=14)
        ax.plot([3.5, 5.5], [y - 0.05, y - 0.05], color="black", lw=1.2)
    pdf.savefig(fig)
    plt.close(fig)


def build_pdf(out_pdf: Path, photographer: str, pairs: list, products: dict,
              title: str = "Product photo review") -> int:
    """pairs: [(ref, a_path, b_path)] in the order to print.
    products: {product: [(number, path)]}. Returns the page count."""
    with PdfPages(out_pdf, metadata={"Title": title, "Author": "", "Subject": ""}) as pdf:
        instructions_page(pdf, photographer, title)
        for n, (ref, a, b) in enumerate(pairs, 1):
            pair_page(pdf, n, len(pairs), ref, a, b)
        for product, items in products.items():
            contact_pages(pdf, product, items)
            pick_page(pdf, product, len(items))
        return pdf.get_pagecount()
