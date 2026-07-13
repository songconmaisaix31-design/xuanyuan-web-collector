import sys
from pathlib import Path
from PIL import Image


def is_dark_title(pixel):
    r, g, b = pixel[:3]
    return r < 70 and g < 85 and b < 105


def is_non_white(pixel):
    r, g, b = pixel[:3]
    return not (r > 246 and g > 246 and b > 246)


def crop_report(path):
    image = Image.open(path).convert("RGB")
    width, height = image.size
    pixels = image.load()

    candidate_rows = []
    for y in range(height):
        count = sum(1 for x in range(width) if is_dark_title(pixels[x, y]))
        if count > width * 0.45:
            candidate_rows.append(y)
    if not candidate_rows:
        return

    top = min(candidate_rows)
    dark_xs = [x for x in range(width) if is_dark_title(pixels[x, top])]
    left = min(dark_xs)
    title_right = max(dark_xs)
    right = left
    bottom = top

    for y in range(top, height):
        for x in range(left, title_right + 1):
            if is_non_white(pixels[x, y]):
                right = max(right, x)
                bottom = max(bottom, y)

    pad = 12
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(width, right + 1 + pad),
        min(height, bottom + 1 + pad),
    )
    image.crop(box).save(path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: crop_report_png.py <png>")
    crop_report(Path(sys.argv[1]))
