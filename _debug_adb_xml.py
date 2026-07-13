import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

adb = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/tools/platform-tools/adb.exe")
serial = "10AF860RJM006AP"
out = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/output/_check.xml")

subprocess.run([str(adb), "-s", serial, "shell", "uiautomator", "dump", "/sdcard/_check.xml"], timeout=20)
subprocess.run([str(adb), "-s", serial, "pull", "/sdcard/_check.xml", str(out)], timeout=20)
subprocess.run([str(adb), "-s", serial, "shell", "rm", "/sdcard/_check.xml"], timeout=10)

tree = ET.parse(out)
root = tree.getroot()
all_nodes = list(root.iter("node"))
print(f"Total XML nodes: {len(all_nodes)}")

nodes = []
for node in root.iter("node"):
    text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
    bounds = node.attrib.get("bounds", "")
    clz = node.attrib.get("class", "").split(".")[-1][:30]
    if text:
        nodes.append({"text": text[:80], "class": clz, "bounds": bounds})

for i, n in enumerate(nodes[:80]):
    print(f'{i}: [{n["class"]}] {n["text"]}')

print(f"\n---\nText-bearing nodes: {len(nodes)}")
