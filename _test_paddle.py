"""Test PaddleOCR with the existing web screenshot."""
import json
import os
import sys

ROOT = r"D:/AI-Workspace/Projects/xuanyuan-web-collector"

os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

from paddleocr import PaddleOCR

# Test init with PP-OCRv5 (models already cached)
print("Initializing PaddleOCR...")
ocr = PaddleOCR(lang='ch', ocr_version='PP-OCRv5')
print("PaddleOCR initialized OK")

# Find test image
img = os.path.join(ROOT, "output", "web_big_board.png")
if not os.path.exists(img):
    print(f"Image not found: {img}")
    sys.exit(1)

print(f"Running OCR on: {img}")
result = ocr.ocr(img, cls=True)

print(f"Result type: {type(result).__name__}")
if isinstance(result, list):
    print(f"Result length: {len(result)}")
    if result and isinstance(result[0], list) and len(result[0]) > 0:
        # Flatten texts
        texts = []
        for page in result:
            for item in page:
                if isinstance(item, (list, tuple)) and len(item) > 1:
                    texts.append(item[1][0])
        print(f"Total texts: {len(texts)}")
        for i, t in enumerate(texts[:30]):
            print(f"  [{i}] {t}")

        # Check for keywords
        compact = "".join(texts)
        keywords = ["大网", "妥投", "准时"]
        for kw in keywords:
            found = kw in compact
            print(f"  Keyword '{kw}': {'FOUND' if found else 'MISSING'}")
    else:
        print("Empty result")
else:
    print(f"Unexpected result shape")
