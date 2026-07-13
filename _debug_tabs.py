"""Debug: list all xy.ele.me tabs and their URLs."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

code = r'''
import json

tabs = list_tabs(include_chrome=False)
xy_tabs = [t for t in tabs if "xy.ele.me" in (t.get("url") or "")]
for t in xy_tabs:
    print(json.dumps({"url": t.get("url", ""), "title": t.get("title", "")}, ensure_ascii=False))
'''
code = code.encode("ascii", "backslashreplace").decode("ascii")
proc = subprocess.run(
    ["browser-harness"],
    input=code,
    text=True, encoding="utf-8", errors="replace",
    capture_output=True, timeout=30,
)
for line in proc.stdout.strip().split("\n"):
    line = line.strip()
    if line.startswith("{"):
        print(line)
