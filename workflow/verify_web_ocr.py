"""Verify web screenshot via bl vision (replaces PaddleOCR).

Extracts text from web_big_board.png using the Bridge CLI vision model.
Checks that the correct business line (大网) is selected and that
妥投率/准时率 values match the web-scraped data.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEB_DATA = ROOT / "xlsx_work" / "mapped_data.json"
SCREENSHOT = ROOT / "output" / "web_big_board.png"
REPORT = ROOT / "output" / "web_ocr_report.json"


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_percent(text):
    values = []
    for match in re.finditer(r"([+-]?\d+(?:\.\d+)?)\s*%", text):
        values.append(float(match.group(1)) / 100)
    return values


def pct_text(value):
    return f"{value * 100:.2f}%"


def find_bl():
    """Locate the bl CLI, same approach as collect_device.py."""
    return (
        shutil.which("bl")
        or shutil.which("bl.cmd")
        or str(Path.home() / "AppData" / "Roaming" / "npm" / "bl.cmd")
    )


def run_bl_vision(image_path):
    """Run bl vision describe and return list of {text} dicts (compatible with
    the old flatten_paddle_result format so downstream parsing stays the same)."""
    bl_bin = find_bl()
    if not bl_bin or not Path(bl_bin).exists():
        raise RuntimeError(
            "bl CLI not found. Install Bridge CLI or set PADDLEOCR_PYTHON "
            "to a Python environment with PaddleOCR installed."
        )
    proc = subprocess.run(
        [
            bl_bin, "vision", "describe",
            "--image", str(image_path),
            "--prompt",
            "Extract all visible text from this dashboard screenshot. "
            "Return ONLY a JSON array of strings, preserving every label, number, and percentage exactly as shown. "
            "Do not explain or summarize.",
            "--output", "json",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    try:
        body = json.loads(proc.stdout)
        content = body["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        raise RuntimeError(f"bl vision output parse failed: {exc}") from exc

    # Try to parse response as JSON array of strings
    texts = []
    if content.strip().startswith("["):
        try:
            raw = json.loads(content)
            if isinstance(raw, list):
                texts = [str(t) for t in raw if t]
        except json.JSONDecodeError:
            pass

    # Fallback: extract text from markdown code block
    if not texts:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.S)
        if match:
            try:
                raw = json.loads(match.group(1))
                if isinstance(raw, list):
                    texts = [str(t) for t in raw if t]
            except json.JSONDecodeError:
                pass

    # Last resort: split into lines
    if not texts:
        texts = [
            line.strip() for line in content.split("\n")
            if line.strip() and not line.strip().startswith("```")
        ]

    texts = [t for t in texts if t]
    # Build lines in the same format as flatten_paddle_result
    lines = [{"text": t, "score": None, "box": None} for t in texts]
    return lines


def run_ocr(image_path):
    """Try bl vision first, fall back to PaddleOCR via PADDLEOCR_PYTHON env."""
    # Check for explicit PaddleOCR fallback
    configured_python = os.environ.get("PADDLEOCR_PYTHON")
    if configured_python:
        current = Path(sys.executable).resolve()
        target = Path(configured_python).resolve()
        if current != target and os.environ.get("PADDLEOCR_VERIFY_CHILD") != "1":
            env = os.environ.copy()
            env["PADDLEOCR_VERIFY_CHILD"] = "1"
            proc = subprocess.run(
                [str(target), str(Path(__file__).resolve())],
                cwd=str(ROOT), env=env, timeout=120,
            )
            raise SystemExit(proc.returncode)

    # Primary: bl vision
    return run_bl_vision(image_path)


def close_to_any(expected, candidates, tolerance=0.003):
    return any(abs(expected - candidate) <= tolerance for candidate in candidates)


def main():
    issues = []
    warnings = []
    if not WEB_DATA.exists():
        issues.append(f"web data missing: {WEB_DATA}")
    if not SCREENSHOT.exists():
        issues.append(f"web screenshot missing: {SCREENSHOT}")
    if issues:
        write_report("failed", issues, warnings, [], "")
        return 1

    data = load_json(WEB_DATA)
    nav = data.get("navigation", {}).get("business_big_network", {})
    if nav.get("selected") is not True:
        issues.append("business line 大网 was not selected by browser workflow")

    lines = run_ocr(SCREENSHOT)
    text = "\n".join(line["text"] for line in lines)
    compact = re.sub(r"\s+", "", text)
    if "大网" not in compact:
        issues.append("OCR did not confirm 大网 in the selected business line")
    if "妥投" not in compact:
        issues.append("OCR did not find 妥投 text")
    if "准时" not in compact:
        issues.append("OCR did not find 准时 text")

    percents = parse_percent(text)
    expected_delivery = data.get("values", {}).get("delivery_rate")
    expected_ontime = data.get("values", {}).get("ontime_rate")
    if isinstance(expected_delivery, (int, float)) and not close_to_any(expected_delivery, percents):
        issues.append(f"OCR percent values did not match 妥投率 {pct_text(expected_delivery)}")
    if isinstance(expected_ontime, (int, float)) and not close_to_any(expected_ontime, percents):
        issues.append(f"OCR percent values did not match 用户T准时率 {pct_text(expected_ontime)}")
    if len(lines) < 20:
        warnings.append(f"OCR returned only {len(lines)} text lines")

    status = "failed" if issues else ("warning" if warnings else "passed")
    write_report(status, issues, warnings, lines, text)
    print(json.dumps(load_json(REPORT), ensure_ascii=False, indent=2))
    return 1 if issues else 0


def write_report(status, issues, warnings, lines, text):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "screenshot": str(SCREENSHOT).replace("\\", "/"),
        "line_count": len(lines),
        "issues": issues,
        "warnings": warnings,
        "sample_text": text[:2000],
        "lines": lines[:200],
    }
    with REPORT.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        write_report("failed", [str(exc)], [], [], "")
        print(json.dumps(load_json(REPORT), ensure_ascii=False, indent=2))
        raise SystemExit(1)
