"""Test bl vision as PaddleOCR replacement."""
import json
import os
import re
import subprocess
import sys

ROOT = r"D:/AI-Workspace/Projects/xuanyuan-web-collector"

def run_bl_vision(image_path):
    """Run bl vision describe and return parsed JSON."""
    bl_bin = "bl"
    proc = subprocess.run(
        [bl_bin, "vision", "describe",
         "--image", str(image_path),
         "--prompt", "Extract all Chinese and numeric text from this screenshot. Return ONLY a JSON array of strings, each string being one visible text block, number, or label. Do not include explanations or markdown.",
         "--output", "json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60
    )
    result = json.loads(proc.stdout)
    content = result["choices"][0]["message"]["content"]
    return content

img = os.path.join(ROOT, "output", "web_big_board.png")
if not os.path.exists(img):
    print(f"Image not found: {img}")
    sys.exit(1)

print("Running bl vision...")
content = run_bl_vision(img)
print(f"Raw output:\n{content[:500]}")
print("...")

# Try to parse as JSON
try:
    texts = json.loads(content)
    if isinstance(texts, list):
        print(f"\nParsed as JSON array, {len(texts)} items")
        for t in texts[:40]:
            print(f"  {t}")
    elif isinstance(texts, dict):
        print(f"\nParsed as dict, keys: {list(texts.keys())}")
except json.JSONDecodeError:
    print("\nNot direct JSON. Trying to extract from markdown...")
    # Try markdown code block
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', content, re.S)
    if match:
        texts = json.loads(match.group(1))
        print(f"Extracted {len(texts)} texts from code block")
        for t in texts[:40]:
            print(f"  {t}")
    else:
        # Fall back to line-by-line
        lines = [l.strip() for l in content.split('\n') if l.strip()]
        print(f"Fallback: {len(lines)} lines")
        for l in lines[:40]:
            print(f"  {l}")
