import json
d = json.load(open("xlsx_work/mapped_data.json", encoding="utf-8"))
v = d.get("values", {})
print("delivery_rate:", v.get("delivery_rate"))
print("ontime_rate:", v.get("ontime_rate"))
print("navigation business_big_network selected:", d.get("navigation", {}).get("business_big_network", {}).get("selected"))
print("status:", d.get("status"))
