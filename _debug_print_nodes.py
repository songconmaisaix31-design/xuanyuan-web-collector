import json

with open("D:\\AI-Workspace\\Projects\\xuanyuan-web-collector\\output\\adb_trade_text.json", "r", encoding="utf-8") as f:
    d = json.load(f)

for i, n in enumerate(d.get("nodes", [])[:200]):
    t = n["text"][:80]
    print(f"{i}: {t}")
