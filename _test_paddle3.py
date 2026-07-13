"""Test PaddleOCR 2.x API."""
import json
import os
import sys

ROOT = r"D:/AI-Workspace/Projects/xuanyuan-web-collector"

from paddleocr import PaddleOCR

print("Initializing PaddleOCR (2.x API)...")
ocr = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
print("PaddleOCR initialized OK")

img = os.path.join(ROOT, "output", "web_big_board.png")
if not os.path.exists(img):
    print(f"Image not found: {img}")
    sys.exit(1)

print(f"Running OCR on: {img}")
result = ocr.ocr(img, cls=True)

print(f"Result type: {type(result).__name__}")
if isinstance(result, list):
    print(f"Result length: {len(result)}")
    if result and isinstance(result[0], list):
        texts = []
        for page in result:
            for item in page:
                if isinstance(item, (list, tuple)) and len(item) > 1:
                    texts.append(item[1][0])
        print(f"Total texts: {len(texts)}")
        for i, t in enumerate(texts[:30]):
            print(f"  [{i}] {t}")

        compact = "".join(texts)
        for kw in ["大网", "妥投", "准时"]:
            print(f"  Keyword '{kw}': {'FOUND' if kw in compact else 'MISSING'}")
    else:
        print("Empty result")
