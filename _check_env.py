import json
d = json.load(open("xlsx_work/mapped_data.json", encoding="utf-8"))
print("updated_at:", d.get("updated_at"))
print("ADB available?", __import__("os").path.exists("tools/platform-tools/adb.exe"))
