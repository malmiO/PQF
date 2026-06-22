"""
Generates 4 synthetic test images representing different PQF outcomes:

  1. good.jpg    - sharp product on white background, well exposed
  2. blurry.jpg  - same scene, heavily blurred (fails T1 sharpness)
  3. dark.jpg    - same scene, very underexposed (fails T2 exposure)
  4. busy_bg.jpg - sharp product but cluttered colourful background (fails T3)

These are deliberately simple synthetic images (not real product photos) —
their purpose is to prove that each PQF criterion responds in the expected
direction (good > blurry on sharpness, good > dark on exposure, etc.)
before the engine is run on the real 200-image dataset.
"""
import cv2
import numpy as np

W, H = 800, 800

def make_base_scene():
    """A 'product' (dark rounded rectangle = e.g. a bottle) centred on a
    white background, with simple shading for sharp edges."""
    img = np.full((H, W, 3), 250, dtype=np.uint8)  # near-white background
    # product body
    cv2.rectangle(img, (300, 220), (500, 620), (60, 90, 160), -1)
    cv2.rectangle(img, (300, 220), (500, 620), (30, 50, 110), 4)
    # label
    cv2.rectangle(img, (330, 350), (470, 480), (230, 230, 230), -1)
    cv2.putText(img, "PRODUCT", (345, 425), cv2.FONT_HERSHEY_SIMPLEX,
                0.9, (20, 20, 20), 2)
    # cap
    cv2.rectangle(img, (350, 160), (450, 220), (40, 60, 120), -1)
    return img


def main():
    base = make_base_scene()

    # 1. GOOD — sharp, well-exposed, white background
    cv2.imwrite("good.jpg", base)

    # 2. BLURRY — heavy Gaussian blur destroys edge sharpness
    blurry = cv2.GaussianBlur(base, (35, 35), 15)
    cv2.imwrite("blurry.jpg", blurry)

    # 3. DARK — multiply pixel values down -> underexposed
    dark = (base.astype(np.float32) * 0.18).astype(np.uint8)
    cv2.imwrite("dark.jpg", dark)

    # 4. BUSY BACKGROUND — replace white background with noisy colour pattern
    busy = base.copy()
    rng = np.random.default_rng(42)
    noise = rng.integers(0, 255, (H, W, 3), dtype=np.uint8)
    # build mask of "background" = near-white pixels in base
    bg_mask = np.all(base > 200, axis=2)
    busy[bg_mask] = noise[bg_mask]
    cv2.imwrite("busy_bg.jpg", busy)

    print("Created: good.jpg, blurry.jpg, dark.jpg, busy_bg.jpg")


if __name__ == "__main__":
    main()
