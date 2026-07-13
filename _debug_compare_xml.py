import xml.etree.ElementTree as ET
from pathlib import Path

# Compare: initial XML from successful run vs current
initial = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/output/adb_initial.xml")
current = Path("D:/AI-Workspace/Projects/xuanyuan-web-collector/output/_check.xml")

print("=== 之前成功时的初始 XML ===")
tree1 = ET.parse(initial)
root1 = tree1.getroot()
count1 = 0
for node in root1.iter("node"):
    text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
    if text and len(text) > 1:
        count1 += 1
        clz = node.attrib.get("class","").split(".")[-1][:25]
        print(f'  [{clz}] {text[:80]}')

print(f"\n总文本节点数: {count1}")

print("\n=== 现在的 XML ===")
tree2 = ET.parse(current)
root2 = tree2.getroot()
count2 = 0
for node in root2.iter("node"):
    text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
    if text and len(text) > 1:
        count2 += 1
        clz = node.attrib.get("class","").split(".")[-1][:25]
        print(f'  [{clz}] {text[:80]}')

print(f"\n总文本节点数: {count2}")
