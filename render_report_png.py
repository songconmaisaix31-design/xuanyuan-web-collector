import json
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config.json"


def load_json(path, default=None):
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


config = load_json(CONFIG, {})
paths = config.get("paths", {})
web = load_json(paths.get("web_data", ROOT / "xlsx_work" / "mapped_data.json"), {})
adb = load_json(paths.get("adb_data", ROOT / "output" / "adb_data.json"), {})
output_dir = Path(paths.get("output_dir", ROOT / "outputs" / "xuanyuan-template"))
output_dir.mkdir(parents=True, exist_ok=True)


def font(size, bold=False):
    candidates = [
        Path("C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc"),
        Path("C:/Windows/Fonts/simhei.ttf"),
        Path("C:/Windows/Fonts/simsun.ttc"),
    ]
    for item in candidates:
        if item.exists():
            return ImageFont.truetype(str(item), size)
    return ImageFont.load_default()


F = {
    "title": font(34, True),
    "subtitle": font(18),
    "section": font(24, True),
    "header": font(18, True),
    "label": font(17),
    "value": font(28, True),
    "value_sm": font(21, True),
    "delta": font(15),
    "small": font(14),
}

COLORS = {
    "bg": "#F4F7FB",
    "panel": "#FFFFFF",
    "ink": "#111827",
    "muted": "#6B7280",
    "line": "#E5E7EB",
    "soft": "#F8FAFC",
    "accent": "#2563EB",
    "accent2": "#0F766E",
    "green": "#2E7D32",
    "red": "#D32F2F",
    "orange": "#EA580C",
}


def metric(path):
    cur = adb
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    if isinstance(cur, dict):
        return cur.get("value")
    return cur


def web_value(name):
    return web.get(name, {}).get("value") if isinstance(web.get(name), dict) else web.get("values", {}).get(name)


def fmt_num(value, digits=0, suffix=""):
    if value is None:
        return "-"
    try:
        n = float(value)
    except Exception:
        return str(value)
    text = f"{n:,.{digits}f}" if digits else f"{n:,.0f}"
    return f"{text}{suffix}"


def fmt_pct(value):
    if value is None:
        return "-"
    return f"{float(value) * 100:.2f}%"


def fmt_pt(value):
    if value is None:
        return "-"
    return f"{float(value):+.2f}pt"


def fmt_delta(value, kind="pct"):
    if value is None:
        return "-"
    if kind == "pt":
        return fmt_pt(value)
    return f"{float(value) * 100:+.2f}%"


def delta_color(value):
    if value is None:
        return COLORS["muted"]
    if value > 0:
        return COLORS["red"]
    if value < 0:
        return COLORS["green"]
    return COLORS["ink"]


def round_rect(draw, box, radius=10, fill="#FFFFFF", outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def text(draw, xy, content, fnt, fill=None, anchor=None):
    draw.text(xy, str(content), font=fnt, fill=fill or COLORS["ink"], anchor=anchor)


def draw_metric_cell(draw, x, y, w, h, label, value, day, week, value_kind="num", delta_kind="pct", alert=False):
    text(draw, (x + 14, y + 12), label, F["label"], COLORS["muted"])
    value_text = value
    if value_kind == "pct":
        value_text = fmt_pct(value)
    elif value_kind == "num1":
        value_text = fmt_num(value, 1)
    elif value_kind == "num2":
        value_text = fmt_num(value, 2)
    elif value_kind == "count":
        value_text = fmt_num(value, 0)
    value_color = COLORS["red"] if alert else COLORS["ink"]
    text(draw, (x + 14, y + 44), value_text, F["value"], value_color)
    text(draw, (x + 14, y + 86), "日环比", F["delta"], COLORS["muted"])
    text(draw, (x + 78, y + 86), fmt_delta(day, delta_kind), F["delta"], delta_color(day))
    text(draw, (x + 14, y + 112), "周同比", F["delta"], COLORS["muted"])
    text(draw, (x + 78, y + 112), fmt_delta(week, delta_kind), F["delta"], delta_color(week))


def draw_section(draw, x, y, title, accent="#2563EB"):
    round_rect(draw, (x, y, x + 8, y + 28), radius=4, fill=accent)
    text(draw, (x + 18, y - 1), title, F["section"], COLORS["ink"])


def draw_summary_grid(draw, x, y, items, cols=4, cell_h=138, gap=12):
    cell_w = (W - x * 2 - gap * (cols - 1)) // cols
    for i, item in enumerate(items):
        cx = x + (i % cols) * (cell_w + gap)
        cy = y + (i // cols) * (cell_h + gap)
        round_rect(draw, (cx, cy, cx + cell_w, cy + cell_h), radius=8, fill=COLORS["panel"], outline=COLORS["line"])
        draw_metric_cell(draw, cx, cy, cell_w, cell_h, **item)
    return y + ((len(items) + cols - 1) // cols) * (cell_h + gap) - gap


def capacity_metric(row, name):
    row_key = capacity_row_key(row.get("line", ""))
    # 汇总行的妥投率使用物流核心（盯大盘）的值
    if row_key == "raw_summary" and name == "delivery_rate":
        return {
            "value": web.get("values", {}).get("delivery_rate"),
            "day": web.get("values", {}).get("delivery_rate_day"),
            "week": web.get("values", {}).get("delivery_rate_week"),
        }
    source_metric = web.get("capacity_rows", {}).get(row_key, {}).get(name, {}) if row_key else {}
    return {
        "value": row.get(name) if row.get(name) is not None else source_metric.get("value"),
        "day": row.get(f"{name}_day") if row.get(f"{name}_day") is not None else source_metric.get("day_value"),
        "week": row.get(f"{name}_week") if row.get(f"{name}_week") is not None else source_metric.get("week_value"),
    }


def capacity_row_key(label):
    text_value = str(label or "")
    if "汇总" in text_value:
        return "raw_summary"
    if "专送" in text_value:
        return "dedicated"
    if "蜂跑" in text_value:
        return "fengpao"
    if "优选" in text_value:
        return "preferred"
    if "普众" in text_value:
        return "ordinary"
    if "联盟" in text_value:
        return "alliance"
    return None


def draw_capacity_detail(draw, x, y, rows):
    headers = [
        ("运力线", 130),
        ("出勤骑手数", 170),
        ("开工骑手数", 170),
        ("妥投率", 170),
        ("准时率", 170),
    ]
    row_h = 98
    table_w = sum(w for _, w in headers)
    round_rect(draw, (x, y, x + table_w, y + 48 + row_h * len(rows)), radius=8, fill=COLORS["panel"], outline=COLORS["line"])
    cx = x
    for label, width in headers:
        text(draw, (cx + 16, y + 14), label, F["header"], COLORS["ink"])
        cx += width
    draw.line((x, y + 48, x + table_w, y + 48), fill=COLORS["line"], width=1)
    cy = y + 48
    for idx, row in enumerate(rows):
        if idx % 2 == 1:
            draw.rectangle((x + 1, cy, x + table_w - 1, cy + row_h), fill=COLORS["soft"])
        text(draw, (x + 16, cy + 34), row.get("line", "-"), F["label"], COLORS["ink"])
        cx = x + headers[0][1]
        for key, kind in [
            ("attendance", "count"),
            ("working_riders", "count"),
            ("delivery_rate", "pct"),
            ("ontime_rate", "pct"),
        ]:
            info = capacity_metric(row, key)
            value = fmt_pct(info["value"]) if kind == "pct" else fmt_num(info["value"], 0)
            text(draw, (cx + 16, cy + 14), value, F["value_sm"], COLORS["ink"])
            text(draw, (cx + 16, cy + 48), "日环比", F["delta"], COLORS["muted"])
            text(draw, (cx + 78, cy + 48), fmt_delta(info["day"]), F["delta"], delta_color(info["day"]))
            text(draw, (cx + 16, cy + 72), "周同比", F["delta"], COLORS["muted"])
            text(draw, (cx + 78, cy + 72), fmt_delta(info["week"]), F["delta"], delta_color(info["week"]))
            cx += 170
        cy += row_h
        if idx < len(rows) - 1:
            draw.line((x, cy, x + table_w, cy), fill=COLORS["line"], width=1)
    return y + 48 + row_h * len(rows)


W = 920
detail_rows = web.get("capacity_detail_rows", [])
detail_rows = detail_rows[:7]
height = 940 + 48 + 98 * max(1, len(detail_rows)) + 72
img = Image.new("RGB", (W, height), COLORS["bg"])
draw = ImageDraw.Draw(img)

margin = 32
updated = web.get("updated_at") or adb.get("collected_at") or ""
round_rect(draw, (margin, 24, W - margin, 112), radius=12, fill=COLORS["panel"], outline=COLORS["line"])
text(draw, (margin + 24, 42), "香河实时播报", F["title"], COLORS["ink"])
text(draw, (margin + 26, 86), f"数据更新  {updated}", F["subtitle"], COLORS["muted"])
text(draw, (W - margin - 24, 62), "自动采集", F["subtitle"], COLORS["accent2"], anchor="ra")

y = 140
draw_section(draw, margin, y, "交易结果", COLORS["accent"])
y += 42
amount = metric("transaction_amount.value")
orders = metric("effective_orders.value")
transaction_target = config.get("excel", {}).get("transaction_target")
order_target = config.get("excel", {}).get("order_target")
trade_items = [
    {"label": "交易额", "value": amount, "day": metric("transaction_amount_day.value"), "week": metric("transaction_amount_week.value"), "value_kind": "num2"},
    {"label": "交易额完成率", "value": (amount / transaction_target if amount and transaction_target else None), "day": None, "week": None, "value_kind": "pct"},
    {"label": "有效订单", "value": orders, "day": metric("effective_orders_day.value"), "week": metric("effective_orders_week.value"), "value_kind": "count"},
    {"label": "订单完成率", "value": (orders / order_target if orders and order_target else None), "day": None, "week": None, "value_kind": "pct"},
]
y = draw_summary_grid(draw, margin, y, trade_items, cols=4) + 34

draw_section(draw, margin, y, "补贴监控", COLORS["orange"])
y += 42
sub = adb.get("subsidies", {})
subsidy_items = [
    {"label": "代理商补贴", "value": sub.get("agent_subsidy", {}).get("value", {}).get("value"), "day": sub.get("agent_subsidy", {}).get("day", {}).get("value"), "week": sub.get("agent_subsidy", {}).get("week", {}).get("value"), "value_kind": "pct", "delta_kind": "pt"},
    {"label": "商户补贴", "value": sub.get("merchant_subsidy", {}).get("value", {}).get("value"), "day": sub.get("merchant_subsidy", {}).get("day", {}).get("value"), "week": sub.get("merchant_subsidy", {}).get("week", {}).get("value"), "value_kind": "pct", "delta_kind": "pt"},
    {"label": "平台补贴", "value": sub.get("platform_subsidy", {}).get("value", {}).get("value"), "day": sub.get("platform_subsidy", {}).get("day", {}).get("value"), "week": sub.get("platform_subsidy", {}).get("week", {}).get("value"), "value_kind": "pct", "delta_kind": "pt"},
]
y = draw_summary_grid(draw, margin, y, subsidy_items, cols=3) + 34

draw_section(draw, margin, y, "物流核心", COLORS["accent2"])
y += 42
alerts = config.get("presentation", {}).get("alerts", {})
logistics_items = [
    {"label": "骑手负载", "value": web.get("values", {}).get("rider_load"), "day": web.get("values", {}).get("rider_load_day"), "week": web.get("values", {}).get("rider_load_week"), "value_kind": "num2"},
    {"label": "平均预测T", "value": web.get("values", {}).get("avg_predicted_t"), "day": web.get("values", {}).get("avg_predicted_t_day"), "week": web.get("values", {}).get("avg_predicted_t_week"), "value_kind": "num2", "alert": (web.get("values", {}).get("avg_predicted_t") or 0) > alerts.get("avg_predicted_t_gt", 30)},
    {"label": "妥投率", "value": web.get("values", {}).get("delivery_rate"), "day": web.get("values", {}).get("delivery_rate_day"), "week": web.get("values", {}).get("delivery_rate_week"), "value_kind": "pct", "alert": (web.get("values", {}).get("delivery_rate") or 1) < alerts.get("delivery_rate_lt", 0.98)},
    {"label": "准时率", "value": web.get("values", {}).get("ontime_rate"), "day": web.get("values", {}).get("ontime_rate_day"), "week": web.get("values", {}).get("ontime_rate_week"), "value_kind": "pct", "alert": (web.get("values", {}).get("ontime_rate") or 1) < alerts.get("ontime_rate_lt", 0.9)},
]
y = draw_summary_grid(draw, margin, y, logistics_items, cols=4) + 34

draw_section(draw, margin, y, "运力线骑手明细", COLORS["accent"])
y += 42
y = draw_capacity_detail(draw, margin, y, detail_rows)

footer_y = y + 34
text(draw, (margin, footer_y), f"香河数据自动填报 · {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}", F["small"], COLORS["muted"])
img = img.crop((0, 0, W, min(height, footer_y + 34)))

stamp = datetime.now().strftime("%Y%m%d%H%M")
base = config.get("excel", {}).get("output_basename", "香河实时播报-已填")
preview_path = output_dir / f"{base}-{stamp}.png"
latest_path = output_dir / "filled-preview.png"
img.save(preview_path)
img.save(latest_path)

result = {
    "status": "success",
    "preview": str(preview_path).replace("\\", "/"),
    "latest_preview": str(latest_path).replace("\\", "/"),
    "updated_at": updated,
}
out_dir = ROOT / "output"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "latest_report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"PREVIEW={result['preview']}")
print(json.dumps(result, ensure_ascii=False, indent=2))
