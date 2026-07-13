"""Test PaddleOCR predict API."""
import json
import os
import sys

ROOT = r"D:/AI-Workspace/Projects/xuanyuan-web-collector"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

from paddleocr import PaddleOCR

print("Initializing PaddleOCR...")
ocr = PaddleOCR(lang='ch', ocr_version='PP-OCRv5')
print("PaddleOCR initialized OK")

img = os.path.join(ROOT, "output", "web_big_board.png")
if not os.path.exists(img):
    print(f"Image not found: {img}")
    sys.exit(1)

print(f"Running OCR on: {img}")
result = ocr.predict(img)

print(f"Result type: {type(result).__name__}")

# Try dict access
if isinstance(result, dict):
    print(f"Keys: {list(result.keys())}")
    # Check for any array/list values
    for k, v in result.items():
        if isinstance(v, (list, tuple)):
            print(f"  {k}: list of {len(v)} items")
            if len(v) > 0:
                item = v[0]
                print(f"    First item type: {type(item).__name__}")
                print(f"    First item: {str(item)[:200]}")
        elif hasattr(v, '__iter__'):
            print(f"  {k}: {type(v).__name__}")
        else:
            print(f"  {k}: {v}")

# Try simple iteration
if hasattr(result, '__iter__'):
    try:
        items = list(result)
        print(f"\nIterable, {len(items)} items")
        for i, item in enumerate(items[:5]):
            print(f"  [{i}] {type(item).__name__}: {str(item)[:150]}")
    except Exception as e:
        print(f"Iteration failed: {e}")
