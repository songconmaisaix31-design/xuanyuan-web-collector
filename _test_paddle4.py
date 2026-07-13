"""Test PaddleOCR 3.x with MKLDNN disabled."""
import os
# Disable oneDNN/MKLDNN to work around the bug
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

import json
import sys

ROOT = r"D:/AI-Workspace/Projects/xuanyuan-web-collector"

from paddleocr import PaddleOCR

print("Initializing PaddleOCR (3.x, MKLDNN disabled)...")
ocr = PaddleOCR(lang='ch', ocr_version='PP-OCRv5')
print("PaddleOCR initialized OK")

img = os.path.join(ROOT, "output", "web_big_board.png")
if not os.path.exists(img):
    print(f"Image not found: {img}")
    sys.exit(1)

print(f"Running OCR on: {img}")
result = ocr.predict(img)

print(f"Result type: {type(result).__name__}")
if isinstance(result, list):
    print(f"Result length: {len(result)}")
    if len(result) > 0:
        item = result[0]
        print(f"First item type: {type(item).__name__}")
        print(f"First item: {str(item)[:300]}")
        if isinstance(item, dict):
            print(f"Keys: {list(item.keys())}")
elif isinstance(result, dict):
    print(f"Keys: {list(result.keys())}")
