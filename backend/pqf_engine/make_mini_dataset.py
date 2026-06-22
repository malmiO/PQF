"""
Generates a small mini-dataset (2 products x 6 images) in the exact folder
structure described in the dataset collection plan, so that
dataset_runner.py and validate_pqf.py can be tested end-to-end before the
real 200-image shoot.

This is NOT the real dataset — it is a structural test only, using the same
synthetic "product" scene as make_test_images.py with more variations.
"""
import os
import cv2
import numpy as np

W, H = 800, 800


def make_scene(seed=0):
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 250, dtype=np.uint8)
    color = tuple(int(c) for c in rng.integers(40, 180, 3))
    cv2.rectangle(img, (300, 220), (500, 620), color, -1)
    cv2.rectangle(img, (300, 220), (500, 620), (30, 30, 30), 4)
    cv2.rectangle(img, (330, 350), (470, 480), (235, 235, 235), -1)
    cv2.putText(img, "PRODUCT", (345, 425), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, (20, 20, 20), 2)
    return img


def apply_variation(img, shot_no):
    """Shots 1-3 = good variations (different angle simulated by minor
    transforms), shots 4-6 = flawed (blur, dark, bad background)."""
    out = img.copy()

    if shot_no == 1:
        pass  # hero, untouched
    elif shot_no == 2:
        out = cv2.flip(out, 1)  # "45 left" simulated by mirroring
    elif shot_no == 3:
        out = np.roll(out, 30, axis=1)  # "45 right" simulated by shift
    elif shot_no == 4:
        out = cv2.GaussianBlur(out, (35, 35), 15)  # heavy blur
    elif shot_no == 5:
        out = (out.astype(np.float32) * 0.15).astype(np.uint8)  # very dark
    elif shot_no == 6:
        # coloured/cluttered background
        rng = np.random.default_rng(99)
        noise = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
        bg_mask = np.all(img > 200, axis=2)
        out[bg_mask] = noise[bg_mask]

    return out


def main():
    root = "pqf_dataset_mini"
    products = [("food", "f01_chips", 1), ("fashion", "a01_tshirt", 2)]

    for category, product_id, seed in products:
        d = os.path.join(root, category, product_id)
        os.makedirs(d, exist_ok=True)
        base = make_scene(seed)
        for shot_no in range(1, 7):
            img = apply_variation(base, shot_no)
            fname = f"{product_id}_{shot_no:02d}.jpg"
            cv2.imwrite(os.path.join(d, fname), img)

    print(f"Created mini dataset under {root}/  (2 products x 6 images = 12 total)")


if __name__ == "__main__":
    main()
