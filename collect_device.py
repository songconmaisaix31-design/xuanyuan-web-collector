import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
ADB = ROOT / "tools" / "platform-tools" / "adb.exe"
OUTPUT = ROOT / "output"
DEVICE_OUTPUT = OUTPUT / "adb_data.json"
CONFIG_PATH = ROOT / "config.json"


def load_config():
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def run_adb(*args, timeout=20):
    if not ADB.exists():
        raise FileNotFoundError(f"adb not found: {ADB}")
    return subprocess.run(
        [str(ADB), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def parse_json_object(text):
    if not text:
        return {}
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except Exception:
        return {}


def vision_extract(image_path, prompt, timeout=60, attempts=3):
    bl_bin = shutil.which("bl") or shutil.which("bl.cmd") or str(Path.home() / "AppData" / "Roaming" / "npm" / "bl.cmd")
    last_error = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 * attempt)
        proc = subprocess.run(
            [
                bl_bin, "vision", "describe",
                "--image", str(image_path),
                "--prompt", prompt,
                "--output", "json",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if proc.returncode != 0:
            last_error = proc.stderr.strip() or proc.stdout.strip()
            continue
        try:
            payload = json.loads(proc.stdout)
            content = payload["choices"][0]["message"]["content"]
        except Exception as exc:
            last_error = f"vision response parse failed: {exc}"
            continue
        data = parse_json_object(content)
        if data:
            return data, None
        last_error = "vision response did not contain JSON"
    return {}, last_error


def apply_vision_metric(base, image_path, page):
    if page == "trade":
        prompt = (
            "Output JSON only. First verify the screenshot is the transaction tab and contains "
            "the cards named 毛GMV and 有效订单量. If it is not the transaction tab, return null "
            "for every value. Extract these card values from the screenshot: "
            "毛GMV transaction amount, 毛GMV day ratio, 毛GMV week ratio, "
            "有效订单量 count, 有效订单量 day ratio, 有效订单量 week ratio. "
            "Use keys transaction_amount, transaction_amount_day, transaction_amount_week, "
            "effective_orders, effective_orders_day, effective_orders_week. Keep the visible numeric strings. "
            "Do not use 净GMV or 中高笔单有效订单数."
        )
        data, error = vision_extract(image_path, prompt)
        if error:
            base["errors"].append(f"trade vision fallback failed: {error}")
            return
        if base["transaction_amount"]["status"] != "success":
            base["transaction_amount"] = clean_number(data.get("transaction_amount"))
        if base["transaction_amount_day"]["status"] != "success":
            base["transaction_amount_day"] = clean_delta(data.get("transaction_amount_day"))
        if base["transaction_amount_week"]["status"] != "success":
            base["transaction_amount_week"] = clean_delta(data.get("transaction_amount_week"))
        if base["effective_orders"]["status"] != "success":
            base["effective_orders"] = clean_number(data.get("effective_orders"))
        if base["effective_orders_day"]["status"] != "success":
            base["effective_orders_day"] = clean_delta(data.get("effective_orders_day"))
        if base["effective_orders_week"]["status"] != "success":
            base["effective_orders_week"] = clean_delta(data.get("effective_orders_week"))
        base["vision_fallback_trade"] = data
        return

    prompt = (
        "Output JSON only. Extract the subsidy strength cards, their day-over-day change, and their week-over-week change: "
        "merchant subsidy strength, Ele.me subsidy strength, agent subsidy strength. "
        "Use keys merchant_subsidy, merchant_subsidy_day, platform_subsidy, "
        "platform_subsidy_day, platform_subsidy_week, merchant_subsidy_week, "
        "agent_subsidy, agent_subsidy_day, agent_subsidy_week. Keep the visible numeric strings."
    )
    data, error = vision_extract(image_path, prompt)
    if error:
        base["errors"].append(f"marketing vision fallback failed: {error}")
        return
    for key in ["merchant_subsidy", "platform_subsidy", "agent_subsidy"]:
        if base["subsidies"][key]["value"]["status"] != "success":
            base["subsidies"][key]["value"] = clean_number(data.get(key))
        day_key = f"{key}_day"
        if base["subsidies"][key]["day"]["status"] != "success":
            base["subsidies"][key]["day"] = clean_delta(data.get(day_key))
        week_key = f"{key}_week"
        if base["subsidies"][key]["week"]["status"] != "success":
            base["subsidies"][key]["week"] = clean_delta(data.get(week_key))
    base["vision_fallback_marketing"] = data


def connect_configured_mumu(config):
    for serial in config.get("adb", {}).get("connect_serials", []):
        run_adb("connect", serial, timeout=8)


def first_device():
    config = load_config()
    connect_configured_mumu(config)
    proc = run_adb("devices", timeout=10)
    devices = []
    unauthorized = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        if parts[1] == "device":
            devices.append(parts[0])
        elif parts[1] == "unauthorized":
            unauthorized.append(parts[0])

    preferred = config.get("adb", {}).get("preferred_serials", [])
    for serial in preferred:
        if serial in devices:
            return serial, None

    if config.get("adb", {}).get("require_mumu"):
        mumu_like = [
            serial for serial in devices
            if serial.startswith("127.0.0.1:") or serial.startswith("emulator-")
        ]
        if mumu_like:
            return mumu_like[0], None
        return None, "no_mumu_device"

    if devices:
        return devices[0], None
    if unauthorized:
        return None, "device_unauthorized"
    return None, "no_device"


def adb_device(serial, *args, timeout=20):
    return run_adb("-s", serial, *args, timeout=timeout)


def tap(serial, x, y):
    adb_device(serial, "shell", "input", "tap", str(x), str(y), timeout=10)


def keyevent(serial, code):
    adb_device(serial, "shell", "input", "keyevent", str(code), timeout=10)


def tap_text(serial, text, stem, x_range=None, y_range=None):
    nodes = wait_for_loaded_nodes(serial, stem, min_nodes=3, attempts=2, delay=0.5)
    candidates = []
    for node in nodes:
        rect = node.get("rect")
        if not rect or node.get("text") != text:
            continue
        if x_range and not (x_range[0] <= rect["cx"] <= x_range[1]):
            continue
        if y_range and not (y_range[0] <= rect["cy"] <= y_range[1]):
            continue
        candidates.append(node)
    if not candidates:
        return False
    candidates.sort(key=lambda item: (item["rect"]["y1"], item["rect"]["x1"]))
    rect = candidates[0]["rect"]
    tap(serial, rect["cx"], rect["cy"])
    return True


def capture(serial, stem):
    remote = f"/sdcard/{stem}.png"
    local = OUTPUT / f"{stem}.png"
    adb_device(serial, "shell", "screencap", "-p", remote, timeout=10)
    adb_device(serial, "pull", remote, str(local), timeout=20)
    adb_device(serial, "shell", "rm", remote, timeout=10)
    return str(local)


def dump_xml(serial, stem):
    remote = f"/sdcard/{stem}.xml"
    local = OUTPUT / f"{stem}.xml"
    last_error = None
    for attempt in range(2):
        try:
            adb_device(serial, "shell", "uiautomator", "dump", remote, timeout=20)
            adb_device(serial, "pull", remote, str(local), timeout=20)
            try:
                adb_device(serial, "shell", "rm", remote, timeout=10)
            except subprocess.TimeoutExpired:
                pass
            return local
        except subprocess.TimeoutExpired as exc:
            last_error = exc
            time.sleep(1 + attempt)
    raise last_error


def parse_bounds(bounds):
    match = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not match:
        return None
    x1, y1, x2, y2 = map(int, match.groups())
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "cx": (x1 + x2) // 2, "cy": (y1 + y2) // 2}


def read_nodes(xml_path):
    if not xml_path.exists():
        return []
    root = ET.parse(xml_path).getroot()
    nodes = []
    for node in root.iter("node"):
        text = (node.attrib.get("text") or node.attrib.get("content-desc") or "").strip()
        if not text:
            continue
        nodes.append({
            "text": text,
            "bounds": node.attrib.get("bounds", ""),
            "rect": parse_bounds(node.attrib.get("bounds", "")),
        })
    return nodes


def clean_number(raw):
    if raw is None:
        return {"raw": raw, "value": None, "status": "invalid"}
    text = str(raw).strip()
    if not text or text in {"--", "-", "loading", "not_found"}:
        return {"raw": text, "value": None, "status": "invalid"}

    normalized = text.replace(",", "").replace("¥", "").replace("￥", "").replace("元", "").strip()
    multiplier = 1
    has_percent = "%" in normalized
    normalized = normalized.replace("%", "")
    if "万" in normalized:
        multiplier = 10000
        normalized = normalized.replace("万", "")

    match = re.search(r"[+-]?\d+(?:\.\d+)?", normalized)
    if not match:
        return {"raw": text, "value": None, "status": "invalid"}
    value = float(match.group(0)) * multiplier
    if has_percent:
        value = value / 100
    if value.is_integer():
        value = int(value)
    return {"raw": text, "value": value, "status": "success"}


def clean_delta(raw):
    text = str(raw or "").strip()
    if "平" in text:
        return {"raw": text, "value": 0, "status": "success"}
    if "0.00" in text and not re.search(r"[1-9]", text):
        return {"raw": text, "value": 0, "status": "success"}
    return clean_number(text)


def merge_text_parts(parts):
    return "".join(str(part).strip() for part in parts if str(part).strip())


def has_real_bounds(node):
    rect = node.get("rect")
    return rect and (rect["x2"] > rect["x1"]) and (rect["y2"] > rect["y1"])


def numericish(text):
    text = str(text or "").strip()
    return bool(re.search(r"\d", text)) or text in {"+", "-", ".", "%"} or any(unit in text for unit in ["万", "元", "%"])


def merge_numeric_in_box(nodes, x1, y1, x2, y2):
    parts = [
        node for node in nodes
        if has_real_bounds(node)
        and x1 <= node["rect"]["cx"] <= x2
        and y1 <= node["rect"]["cy"] <= y2
        and numericish(node["text"])
        and not str(node["text"]).startswith("AlibabaSans")
    ]
    parts.sort(key=lambda node: (node["rect"]["y1"], node["rect"]["x1"]))
    return merge_text_parts(node["text"] for node in parts)


def extract_card_by_box(nodes, x1, label_y1, x2):
    value_raw = merge_numeric_in_box(nodes, x1, label_y1 + 30, x2, label_y1 + 125)
    day_raw = merge_numeric_in_box(nodes, x1, label_y1 + 105, x2, label_y1 + 165)
    week_raw = merge_numeric_in_box(nodes, x1, label_y1 + 140, x2, label_y1 + 205)
    return {
        "value": clean_number(value_raw),
        "day": clean_delta(day_raw),
        "week": clean_delta(week_raw),
    }


def metric_value(metric):
    return metric.get("value") if isinstance(metric, dict) else None


def metric_ok(metric):
    return isinstance(metric, dict) and metric.get("status") == "success" and metric.get("value") is not None


def empty_trade_metrics():
    return {
        "transaction_amount": {"raw": "", "value": None, "status": "invalid"},
        "transaction_amount_day": {"raw": "", "value": None, "status": "invalid"},
        "transaction_amount_week": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders_day": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders_week": {"raw": "", "value": None, "status": "invalid"},
    }


def trade_metrics_complete(metrics):
    return all(
        metric_ok(metrics[key])
        for key in [
            "transaction_amount",
            "transaction_amount_day",
            "transaction_amount_week",
            "effective_orders",
            "effective_orders_day",
            "effective_orders_week",
        ]
    )


def trade_metrics_sane(metrics):
    if not trade_metrics_complete(metrics):
        return False
    transaction_amount = metric_value(metrics["transaction_amount"])
    effective_orders = metric_value(metrics["effective_orders"])
    return transaction_amount is not None and transaction_amount > 0 and effective_orders is not None and effective_orders > 0


def trade_subtraction_sane(total, excluded, calculated):
    if not trade_metrics_sane(total) or not trade_metrics_sane(excluded) or not trade_metrics_sane(calculated):
        return False
    return (
        metric_value(total["transaction_amount"]) >= metric_value(excluded["transaction_amount"])
        and metric_value(total["effective_orders"]) >= metric_value(excluded["effective_orders"])
    )


def assign_trade_metrics(target, metrics):
    for key, value in metrics.items():
        if key in target:
            target[key] = value


def formatted_number(value, digits=2):
    if value is None:
        return ""
    if isinstance(value, int) or (isinstance(value, float) and value.is_integer()):
        return f"{int(value):,}.00"
    return f"{float(value):,.{digits}f}"


def formatted_delta(value):
    if value is None:
        return ""
    return f"{float(value) * 100:+.2f}%"


def subtract_number_metric(total, excluded, digits=2):
    if not metric_ok(total) or not metric_ok(excluded):
        return {"raw": "", "value": None, "status": "invalid"}
    value = metric_value(total) - metric_value(excluded)
    if digits == 0:
        value = int(round(value))
    else:
        value = round(float(value), digits)
    return {"raw": formatted_number(value, digits), "value": value, "status": "success"}


def previous_value(current_metric, delta_metric):
    if not metric_ok(current_metric) or not metric_ok(delta_metric):
        return None
    denominator = 1 + float(metric_value(delta_metric))
    if abs(denominator) < 1e-9:
        return None
    return float(metric_value(current_metric)) / denominator


def subtract_delta_metric(total_current, total_delta, excluded_current, excluded_delta):
    total_previous = previous_value(total_current, total_delta)
    excluded_previous = previous_value(excluded_current, excluded_delta)
    if total_previous is None or excluded_previous is None:
        return {"raw": "", "value": None, "status": "invalid"}
    current = float(metric_value(total_current)) - float(metric_value(excluded_current))
    previous = total_previous - excluded_previous
    if abs(previous) < 1e-9:
        return {"raw": "", "value": None, "status": "invalid"}
    value = (current - previous) / previous
    return {"raw": formatted_delta(value), "value": value, "status": "success"}


def subtract_trade_metrics(total, excluded):
    return {
        "transaction_amount": subtract_number_metric(total["transaction_amount"], excluded["transaction_amount"], digits=2),
        "transaction_amount_day": subtract_delta_metric(
            total["transaction_amount"],
            total["transaction_amount_day"],
            excluded["transaction_amount"],
            excluded["transaction_amount_day"],
        ),
        "transaction_amount_week": subtract_delta_metric(
            total["transaction_amount"],
            total["transaction_amount_week"],
            excluded["transaction_amount"],
            excluded["transaction_amount_week"],
        ),
        "effective_orders": subtract_number_metric(total["effective_orders"], excluded["effective_orders"], digits=0),
        "effective_orders_day": subtract_delta_metric(
            total["effective_orders"],
            total["effective_orders_day"],
            excluded["effective_orders"],
            excluded["effective_orders_day"],
        ),
        "effective_orders_week": subtract_delta_metric(
            total["effective_orders"],
            total["effective_orders_week"],
            excluded["effective_orders"],
            excluded["effective_orders_week"],
        ),
    }


def tap_point(config, name, default):
    points = config.get("adb", {}).get("tap_points", {})
    point = points.get(name)
    if isinstance(point, list) and len(point) == 2:
        return int(point[0]), int(point[1])
    return default


def dismiss_dropdown(serial):
    tap(serial, 540, 1700)
    time.sleep(0.4)


def business_line_labels():
    return {"\u5168\u90e8\u4e1a\u52a1\u7ebf", "FML", "CKA", "KA", "\u65b0\u96f6\u552e"}


def current_business_line(nodes):
    labels = business_line_labels()
    for node in nodes:
        rect = node.get("rect")
        if not rect:
            continue
        if 650 <= rect["cx"] <= 920 and 115 <= rect["cy"] <= 175 and node.get("text") in labels:
            return node["text"]
    return ""


def business_dropdown_open(nodes):
    option_count = 0
    labels = business_line_labels()
    for node in nodes:
        rect = node.get("rect")
        if not rect:
            continue
        if rect["x1"] <= 60 and 180 <= rect["cy"] <= 540 and node.get("text") in labels:
            option_count += 1
    return option_count >= 3


def select_business_line(serial, config, line_name):
    selector = tap_point(config, "business_line_selector", (805, 150))
    options = {
        "all": tap_point(config, "business_line_all", (90, 205)),
        "new_retail": tap_point(config, "business_line_new_retail", (90, 515)),
    }
    dismiss_dropdown(serial)
    tap(serial, *selector)
    time.sleep(0.8)
    tap(serial, *options[line_name])
    time.sleep(2.2)


def extract_trade_metrics(nodes):
    if not is_trade_page(nodes):
        return empty_trade_metrics()
    transaction_metric = extract_card_by_box(nodes, 382, 350, 700)
    effective_metric = extract_card_by_box(nodes, 722, 350, 1040)
    metrics = empty_trade_metrics()
    metrics["transaction_amount"] = transaction_metric["value"]
    metrics["transaction_amount_day"] = transaction_metric["day"]
    metrics["transaction_amount_week"] = transaction_metric["week"]
    metrics["effective_orders"] = effective_metric["value"]
    metrics["effective_orders_day"] = effective_metric["day"]
    metrics["effective_orders_week"] = effective_metric["week"]
    return metrics


def collect_trade_snapshot(serial, stem):
    nodes = []
    metrics = empty_trade_metrics()
    errors = []
    image_path = ""
    for attempt in range(3):
        open_trade_tab(serial, f"{stem}_trade_tab_{attempt}")
        time.sleep(1.5)
        image_path = capture(serial, stem)
        nodes = wait_for_loaded_nodes(serial, f"{stem}_{attempt}", min_nodes=3, attempts=1, delay=0.2)
        if business_dropdown_open(nodes):
            keyevent(serial, 4)
            time.sleep(1)
            continue
        metrics = extract_trade_metrics(nodes)
        snapshot = {**metrics, "errors": errors}
        if not trade_metrics_complete(metrics):
            apply_vision_metric(snapshot, image_path, "trade")
            metrics = {key: snapshot[key] for key in metrics}
        if trade_metrics_sane(metrics):
            break
        errors.append("trade screenshot extraction failed or invalid")
        time.sleep(1.2)

    write_json(OUTPUT / f"{stem}_text.json", {"nodes": nodes})
    return {
        "metrics": metrics,
        "screenshot": image_path,
        "errors": errors,
    }

def wait_for_loaded_nodes(serial, stem, min_nodes=20, attempts=8, delay=1):
    last_nodes = []
    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        try:
            xml_path = dump_xml(serial, stem)
        except subprocess.TimeoutExpired:
            continue
        last_nodes = read_nodes(xml_path)
        real_nodes = [node for node in last_nodes if has_real_bounds(node)]
        if len(real_nodes) >= min_nodes:
            return last_nodes
    return last_nodes


def page_has_text(nodes, *needles):
    texts = [str(node.get("text") or "") for node in nodes]
    return any(any(needle in text for text in texts) for needle in needles)


def is_trade_page(nodes):
    return (
        page_has_text(nodes, "\u6bdbGMV")
        and page_has_text(nodes, "\u6709\u6548\u8ba2\u5355\u91cf")
        and not page_has_text(nodes, "\u5546\u6237\u8865\u8d34\u529b\u5ea6", "\u4ee3\u7406\u5546\u8865\u8d34\u529b\u5ea6")
    )


def open_trade_tab(serial, stem):
    nodes = ensure_main_data_page(serial, f"{stem}_main")
    dismiss_dropdown(serial)
    tap(serial, 189, 220)
    time.sleep(1.2)
    return wait_for_loaded_nodes(serial, f"{stem}_after", min_nodes=10, attempts=2, delay=0.5)


def ensure_main_data_page(serial, stem):
    nodes = wait_for_loaded_nodes(serial, stem, min_nodes=3, attempts=2, delay=0.5)
    if page_has_text(nodes, "创建计划", "您还未创建拜访计划", "轩辕"):
        keyevent(serial, 4)
        time.sleep(1.2)
        nodes = wait_for_loaded_nodes(serial, f"{stem}_after_back", min_nodes=3, attempts=2, delay=0.5)
    return nodes


def open_marketing_tab(serial):
    for attempt in range(3):
        ensure_main_data_page(serial, f"adb_before_marketing_{attempt}")
        if not tap_text(serial, "营销", f"adb_marketing_tab_{attempt}", x_range=(760, 980), y_range=(170, 270)):
            tap(serial, 891, 220)
        time.sleep(2)
        nodes = wait_for_loaded_nodes(serial, f"adb_marketing_probe_{attempt}", min_nodes=10, attempts=2, delay=0.5)
        if page_has_text(nodes, "创建计划", "您还未创建拜访计划", "轩辕"):
            keyevent(serial, 4)
            time.sleep(1.2)
            continue
        if page_has_text(nodes, "商户补贴", "饿了么补贴", "代理商补贴", "营销"):
            return nodes
    return wait_for_loaded_nodes(serial, "adb_marketing_probe_final", min_nodes=10, attempts=2, delay=0.5)


def collect():
    config = load_config()
    serial, error = first_device()
    base = {
        "source": "adb_screen",
        "collected_at": now_iso(),
        "status": "failed",
        "device": serial,
        "transaction_amount": {"raw": "", "value": None, "status": "invalid"},
        "transaction_amount_day": {"raw": "", "value": None, "status": "invalid"},
        "transaction_amount_week": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders_day": {"raw": "", "value": None, "status": "invalid"},
        "effective_orders_week": {"raw": "", "value": None, "status": "invalid"},
        "subsidies": {
            "agent_subsidy": {"value": {"raw": "", "value": None, "status": "invalid"}, "day": {"raw": "", "value": None, "status": "invalid"}, "week": {"raw": "", "value": None, "status": "invalid"}},
            "merchant_subsidy": {"value": {"raw": "", "value": None, "status": "invalid"}, "day": {"raw": "", "value": None, "status": "invalid"}, "week": {"raw": "", "value": None, "status": "invalid"}},
            "platform_subsidy": {"value": {"raw": "", "value": None, "status": "invalid"}, "day": {"raw": "", "value": None, "status": "invalid"}, "week": {"raw": "", "value": None, "status": "invalid"}},
        },
        "screenshots": {},
        "trade_business_lines": {},
        "errors": [],
    }

    if error:
        base["status"] = error
        base["errors"].append(error)
        return base

    base["source"] = "mumu_adb_screen"

    open_trade_tab(serial, "adb_initial_trade")
    select_business_line(serial, config, "all")
    open_trade_tab(serial, "adb_all_before_snapshot")
    all_trade = collect_trade_snapshot(serial, "adb_trade_all")
    base["screenshots"]["trade_all_business_lines"] = all_trade["screenshot"]
    base["trade_business_lines"]["all"] = all_trade["metrics"]
    base["errors"].extend(f"all business line: {error}" for error in all_trade["errors"])

    select_business_line(serial, config, "new_retail")
    open_trade_tab(serial, "adb_new_retail_before_snapshot")
    new_retail_trade = collect_trade_snapshot(serial, "adb_trade_new_retail")
    base["screenshots"]["trade_new_retail"] = new_retail_trade["screenshot"]
    base["trade_business_lines"]["new_retail"] = new_retail_trade["metrics"]
    base["errors"].extend(f"new retail: {error}" for error in new_retail_trade["errors"])

    calculated_trade = subtract_trade_metrics(all_trade["metrics"], new_retail_trade["metrics"])
    base["trade_business_lines"]["all_minus_new_retail"] = calculated_trade
    if trade_subtraction_sane(all_trade["metrics"], new_retail_trade["metrics"], calculated_trade):
        assign_trade_metrics(base, calculated_trade)
    else:
        base["errors"].append("trade subtraction sanity check failed")
    base["screenshots"]["trade"] = all_trade["screenshot"]

    select_business_line(serial, config, "all")
    marketing_nodes = open_marketing_tab(serial)
    if len([node for node in marketing_nodes if has_real_bounds(node)]) < 20:
        marketing_nodes = wait_for_loaded_nodes(serial, "adb_marketing", min_nodes=20, attempts=8, delay=1)
    base["screenshots"]["marketing"] = capture(serial, "adb_marketing")
    write_json(OUTPUT / "adb_marketing_text.json", {"nodes": marketing_nodes})

    base["subsidies"]["merchant_subsidy"] = extract_card_by_box(marketing_nodes, 42, 585, 360)
    base["subsidies"]["platform_subsidy"] = extract_card_by_box(marketing_nodes, 382, 585, 700)
    base["subsidies"]["agent_subsidy"] = extract_card_by_box(marketing_nodes, 722, 585, 1040)
    if not all(
        metric["value"]["status"] == "success" and metric["day"]["status"] == "success" and metric["week"]["status"] == "success"
        for metric in base["subsidies"].values()
    ):
        apply_vision_metric(base, base["screenshots"]["marketing"], "marketing")

    # 回到履约界面（默认界面）
    tap(serial, 540, 210)

    ok_any = (
        base["transaction_amount"]["status"] == "success"
        or base["effective_orders"]["status"] == "success"
        or any(item["value"]["status"] == "success" for item in base["subsidies"].values())
    )
    base["status"] = "success" if ok_any and not base["errors"] else ("partial_success" if ok_any else "failed")
    base["source_namespace"] = "adb"
    base["field_sources"] = {
        "transaction_amount": "adb.trade.all_minus_new_retail",
        "transaction_amount_day": "adb.trade.all_minus_new_retail",
        "transaction_amount_week": "adb.trade.all_minus_new_retail",
        "effective_orders": "adb.trade.all_minus_new_retail",
        "effective_orders_day": "adb.trade.all_minus_new_retail",
        "effective_orders_week": "adb.trade.all_minus_new_retail",
        "agent_subsidy": "adb.marketing",
        "agent_subsidy_day": "adb.marketing",
        "agent_subsidy_week": "adb.marketing",
        "merchant_subsidy": "adb.marketing",
        "merchant_subsidy_day": "adb.marketing",
        "merchant_subsidy_week": "adb.marketing",
        "platform_subsidy": "adb.marketing",
        "platform_subsidy_day": "adb.marketing",
        "platform_subsidy_week": "adb.marketing",
    }
    base["adb_values"] = {
        "adb_transaction_amount": base["transaction_amount"]["value"],
        "adb_transaction_amount_day": base["transaction_amount_day"]["value"],
        "adb_transaction_amount_week": base["transaction_amount_week"]["value"],
        "adb_effective_orders": base["effective_orders"]["value"],
        "adb_effective_orders_day": base["effective_orders_day"]["value"],
        "adb_effective_orders_week": base["effective_orders_week"]["value"],
        "adb_trade_all_transaction_amount": base["trade_business_lines"]["all"]["transaction_amount"]["value"],
        "adb_trade_all_effective_orders": base["trade_business_lines"]["all"]["effective_orders"]["value"],
        "adb_trade_new_retail_transaction_amount": base["trade_business_lines"]["new_retail"]["transaction_amount"]["value"],
        "adb_trade_new_retail_effective_orders": base["trade_business_lines"]["new_retail"]["effective_orders"]["value"],
        "adb_agent_subsidy": base["subsidies"]["agent_subsidy"]["value"]["value"],
        "adb_agent_subsidy_day": base["subsidies"]["agent_subsidy"]["day"]["value"],
        "adb_agent_subsidy_week": base["subsidies"]["agent_subsidy"]["week"]["value"],
        "adb_merchant_subsidy": base["subsidies"]["merchant_subsidy"]["value"]["value"],
        "adb_merchant_subsidy_day": base["subsidies"]["merchant_subsidy"]["day"]["value"],
        "adb_merchant_subsidy_week": base["subsidies"]["merchant_subsidy"]["week"]["value"],
        "adb_platform_subsidy": base["subsidies"]["platform_subsidy"]["value"]["value"],
        "adb_platform_subsidy_day": base["subsidies"]["platform_subsidy"]["day"]["value"],
        "adb_platform_subsidy_week": base["subsidies"]["platform_subsidy"]["week"]["value"],
    }
    return base


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    data = collect()
    write_json(DEVICE_OUTPUT, data)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data["status"] in {"success", "partial_success", "no_device", "no_mumu_device", "device_unauthorized"} else 1


if __name__ == "__main__":
    sys.exit(main())
