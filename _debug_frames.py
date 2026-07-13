"""Debug: inspect the xy.ele.me page structure."""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

code = r'''
import json

tabs = list_tabs(include_chrome=False)
xy_tabs = [t for t in tabs if "xy.ele.me" in (t.get("url") or "")]
if xy_tabs:
    switch_tab(xy_tabs[0])
else:
    new_tab("https://xy.ele.me/cddp")
wait_for_load(20)
wait_for_network_idle(10, 800)

# Check all frames
frame_tree = cdp("Page.getFrameTree")
frame_info = []

def walk(node, depth=0):
    frame = node.get("frame", {})
    url = (frame.get("url") or "") + "#" + (frame.get("urlFragment") or "")
    frame_info.append({
        "depth": depth,
        "id": frame.get("id"),
        "url": url,
        "name": frame.get("name", ""),
    })
    for child in node.get("childFrames") or []:
        walk(child, depth + 1)

walk(frame_tree.get("frameTree", {}))
print(json.dumps({"tab_count": len(xy_tabs), "frames": frame_info}, ensure_ascii=False))
'''
code = code.encode("ascii", "backslashreplace").decode("ascii")
proc = subprocess.run(
    ["browser-harness"],
    input=code,
    text=True, encoding="utf-8", errors="replace",
    capture_output=True, timeout=60,
)

# Extract last JSON line
for line in reversed(proc.stdout.strip().split("\n")):
    line = line.strip()
    if line.startswith("{"):
        print(line)
        break
else:
    print("STDOUT:", proc.stdout[-2000:])
    print("STDERR:", proc.stderr[-2000:])
