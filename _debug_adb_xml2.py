import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

adb = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/tools/platform-tools/adb.exe")
serial = "10AF860RJM006AP"
out = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/output/_check.xml")

tree = ET.parse(out)
root = tree.getroot()

# Print all node attributes
for i, node in enumerate(root.iter("node")):
    attrs = dict(node.attrib)
    text = (attrs.get("text") or "").strip()
    cd = (attrs.get("content-desc") or "").strip()
    clz = attrs.get("class", "").split(".")[-1][:25]
    bounds = attrs.get("bounds", "")
    if text or cd:
        info = f'text="{text[:40]}"' if text else f'cd="{cd[:60]}"'
        print(f'{i:3d} [{clz:25s}] {info}  {bounds}')
    else:
        print(f'{i:3d} [{clz:25s}] (no text)  {bounds}')

print(f"\nTotal: {len(list(root.iter('node')))} nodes")
