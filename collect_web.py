import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
CONFIG = ROOT / "config.json"
RESULT = OUTPUT / "result.json"
LOG = OUTPUT / "run.log"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_config():
    with CONFIG.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def clean_number(raw, kind="decimal"):
    if raw is None:
        return {"raw": raw, "value": None, "status": "invalid"}
    text = str(raw).strip()
    if not text or text in {"--", "-", "加载中", "未找到", "解析失败"}:
        return {"raw": raw, "value": None, "status": "invalid"}

    normalized = text.replace(",", "").replace("¥", "").replace("￥", "").strip()
    multiplier = Decimal("1")
    is_percent = normalized.endswith("%")
    if is_percent:
        normalized = normalized[:-1].strip()
    if normalized.endswith("万"):
        normalized = normalized[:-1].strip()
        multiplier = Decimal("10000")

    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return {"raw": raw, "value": None, "status": "invalid"}

    try:
        value = Decimal(match.group(0)) * multiplier
        if kind == "integer":
            value = int(value)
        else:
            value = float(value)
        return {"raw": raw, "value": value, "status": "success"}
    except (InvalidOperation, ValueError):
        return {"raw": raw, "value": None, "status": "invalid"}


def base_result(config, status="failed", errors=None, url=""):
    return {
        "source": "xuanyuan_web",
        "city_name": config.get("city_name", ""),
        "collected_at": now_iso(),
        "url": url,
        "status": status,
        "metrics": {},
        "errors": errors or [],
    }


def run_browser_harness(config):
    harness_code = r'''
import json, os, re, time
from datetime import datetime, timezone

out_dir = r"__OUT_DIR__"
config = __CONFIG_JSON__
os.makedirs(out_dir, exist_ok=True)

def save_json(name, data):
    with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")

def stamp():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

def runtime_value(response, expression):
    if response.get("exceptionDetails"):
        raise RuntimeError("JavaScript evaluation failed: " + json.dumps(response.get("exceptionDetails"), ensure_ascii=False))
    result = response.get("result", {})
    if "value" in result:
        return result["value"]
    return None

def app_context_id():
    def walk(node):
        frame = node.get("frame", {})
        url = (frame.get("url") or "") + "#" + (frame.get("urlFragment") or "")
        if "dm-area-data-board" in url:
            return frame.get("id")
        for child in node.get("childFrames") or []:
            found = walk(child)
            if found:
                return found
        return None
    tree = cdp("Page.getFrameTree").get("frameTree", {})
    frame_id = walk(tree)
    if not frame_id:
        return None
    return cdp("Page.createIsolatedWorld", frameId=frame_id, worldName="xuanyuan_collect", grantUniveralAccess=True).get("executionContextId")

APP_CONTEXT_ID = None

def app_js(expression):
    global APP_CONTEXT_ID
    if APP_CONTEXT_ID is None:
        APP_CONTEXT_ID = app_context_id()
    if not APP_CONTEXT_ID:
        return js(expression)
    response = cdp("Runtime.evaluate", expression=expression, contextId=APP_CONTEXT_ID, returnByValue=True, awaitPromise=True)
    return runtime_value(response, expression)

def visible_snapshot():
    return app_js("""
    (() => {
      const visible = (el) => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      };
      const textOf = (el) => (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
      const mainText = Array.from(document.querySelectorAll('body *'))
        .filter(visible)
        .map(textOf)
        .filter(Boolean)
        .filter((v, i, a) => v.length <= 120 && a.indexOf(v) === i)
        .slice(0, 300);
      const buttons = Array.from(document.querySelectorAll('button,[role=button],a,input[type=button],input[type=submit]'))
        .filter(visible)
        .map(el => ({
          text: (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim(),
          tag: el.tagName.toLowerCase(),
          rect: (() => { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; })()
        }))
        .filter(x => x.text)
        .slice(0, 120);
      const candidateFields = mainText.filter(t => /订单|交易|金额|销售|营业|收入|客单|转化|曝光|访问|支付|退款|评分|库存|商品|门店|城市|数据|统计|分析/.test(t)).slice(0, 120);
      return {main_text: mainText, buttons, candidate_fields: candidateFields};
    })()
    """)

def has_login_wall(snapshot):
    text = "\\n".join(snapshot.get("main_text", []) + [b.get("text", "") for b in snapshot.get("buttons", [])])
    return any(word in text for word in ["登录", "手机号登录", "验证码", "账号异常", "重新登录"])

def city_text(snapshot):
    target = config.get("city_name") or ""
    if target and target != "目标城市":
        haystack = "\\n".join(snapshot.get("main_text", []))
        if target in haystack:
            return target
    for item in snapshot.get("candidate_fields", []):
        if "城市" in item or "当前城市" in item:
            return item
    return ""

def find_button_by_text(text):
    if not text:
        return None
    return app_js("""
    ((needle) => {
      const norm = (s) => (s || '').replace(/\\s+/g, '');
      const wanted = norm(needle);
      const visible = (el) => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const nodes = Array.from(document.querySelectorAll('button,[role=button],a,input[type=button],input[type=submit]'));
      for (const el of nodes) {
        if (!visible(el)) continue;
        const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim();
        if (label && norm(label).includes(wanted)) {
          const r = el.getBoundingClientRect();
          return {text: label, x: r.x + r.width / 2, y: r.y + r.height / 2};
        }
      }
      return null;
    })
    """ + "(" + json.dumps(text, ensure_ascii=False) + ")")

def click_text_once(text):
    button = find_button_by_text(text)
    if not button:
        return None
    clicked = app_js("""
    ((needle) => {
      const norm = (s) => (s || '').replace(/\\s+/g, '');
      const wanted = norm(needle);
      const visible = (el) => {
        const style = getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const nodes = Array.from(document.querySelectorAll('button,[role=button],a,input[type=button],input[type=submit]'));
      for (const el of nodes) {
        if (!visible(el)) continue;
        const label = (el.innerText || el.value || el.getAttribute('aria-label') || el.title || '').replace(/\\s+/g, ' ').trim();
        if (label && norm(label).includes(wanted)) {
          el.click();
          return true;
        }
      }
      return false;
    })
    """ + "(" + json.dumps(text, ensure_ascii=False) + ")")
    if not clicked:
        return None
    wait(1)
    wait_for_load(10)
    wait_for_network_idle(10, 800)
    return button

def extract_fields(fields):
    return app_js("""
    ((fields) => {
      const bodyText = document.body.innerText || '';
      const lines = bodyText.split(/\\n+/).map(s => s.trim()).filter(Boolean);
      const out = {};
      const valuePattern = '([-+]?¥?￥?[0-9][0-9,]*(?:\\\\.[0-9]+)?%?万?|--)';
      for (const [key, spec] of Object.entries(fields || {})) {
        const label = spec.label || '';
        let raw = null;
        if (label) {
          for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            if (!line.includes(label)) continue;
            const after = line.slice(line.indexOf(label) + label.length);
            let m = after.match(new RegExp(valuePattern));
            if (!m && i + 1 < lines.length) m = lines[i + 1].match(new RegExp(valuePattern));
            if (m) { raw = m[1]; break; }
          }
        }
        out[key] = raw === null ? "未找到" : raw;
      }
      return out;
    })
    """ + "(" + json.dumps(fields, ensure_ascii=False) + ")")

tabs = list_tabs(include_chrome=False)
xy_tabs = [t for t in tabs if "xy.ele.me" in (t.get("url") or "")]
if xy_tabs:
    switch_tab(xy_tabs[0])
else:
    new_tab(config.get("site_url") or "https://xy.ele.me/")

wait_for_load(20)
wait_for_network_idle(10, 800)
capture_screenshot(os.path.join(out_dir, "inspect.png"))
info = page_info()
snapshot = visible_snapshot()
logged_in = not has_login_wall(snapshot)
city = city_text(snapshot)
page_info_data = {
    "url": info.get("url", ""),
    "title": info.get("title", ""),
    "logged_in": logged_in,
    "city_text": city,
    "captured_at": stamp()
}
save_json("page-info.json", page_info_data)
save_json("visible-text.json", snapshot)

if not logged_in:
    capture_screenshot(os.path.join(out_dir, "login_required.png"))
    print(json.dumps({"status": "login_required", "page_info": page_info_data}, ensure_ascii=False))
    raise SystemExit

target_city = config.get("city_name") or ""
if target_city and target_city != "目标城市" and city != target_city:
    print(json.dumps({"status": "city_unconfirmed", "page_info": page_info_data, "city_text": city}, ensure_ascii=False))
    raise SystemExit

target_text = config.get("target_page_text") or ""
if not target_text:
    candidates = [x for x in snapshot.get("main_text", []) if re.search(r"数据|查询|统计|分析|经营|报表", x)]
    print(json.dumps({"status": "page_not_found", "page_info": page_info_data, "candidates": candidates[:30], "reason": "target_page_text is empty"}, ensure_ascii=False))
    raise SystemExit

current_text = "\\n".join(snapshot.get("main_text", []))
if target_text in (info.get("title", "") or "") or target_text in current_text:
    entry = {"text": target_text, "already_current": True}
else:
    entry = click_text_once(target_text)
    if not entry:
        print(json.dumps({"status": "page_not_found", "page_info": page_info_data, "reason": "target page entry not found: " + target_text}, ensure_ascii=False))
        raise SystemExit

wait(1)
capture_screenshot(os.path.join(out_dir, "before_click.png"))
before = visible_snapshot()

query_text = config.get("query_button_text") or ""
if not query_text:
    safe = [b for b in before.get("buttons", []) if re.search(r"查询|刷新|确认|搜索", b.get("text", ""))]
    if safe:
        query_text = safe[0]["text"]
    else:
        print(json.dumps({"status": "page_not_found", "page_info": page_info_data, "entry": entry, "reason": "query_button_text is empty and no safe button found"}, ensure_ascii=False))
        raise SystemExit

clicked = click_text_once(query_text)
if not clicked:
    print(json.dumps({"status": "page_not_found", "page_info": page_info_data, "entry": entry, "reason": "query button not found: " + query_text}, ensure_ascii=False))
    raise SystemExit

capture_screenshot(os.path.join(out_dir, "after_click.png"))
raw_fields = extract_fields(config.get("fields") or {})
print(json.dumps({
    "status": "success",
    "page_info": page_info(),
    "initial_page_info": page_info_data,
    "city_text": city,
    "entry": entry,
    "clicked": clicked,
    "raw_fields": raw_fields,
    "data_source": "DOM"
}, ensure_ascii=False))
'''
    harness_code = harness_code.replace("__OUT_DIR__", str(OUTPUT).replace("\\", "\\\\"))
    harness_code = harness_code.replace("__CONFIG_JSON__", json.dumps(config, ensure_ascii=True))
    harness_code = harness_code.encode("ascii", "backslashreplace").decode("ascii")

    return subprocess.run(
        ["browser-harness"],
        input=harness_code,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=str(ROOT),
        timeout=120,
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    config = load_config()
    errors = []

    try:
        proc = run_browser_harness(config)
    except FileNotFoundError:
        result = base_result(config, "failed", ["Browser Harness 未安装或不在 PATH 中"])
        write_json(RESULT, result)
        LOG.write_text("browser-harness command not found\n", encoding="utf-8")
        return 1
    except subprocess.TimeoutExpired as exc:
        result = base_result(config, "failed", ["Browser Harness 执行超时"])
        write_json(RESULT, result)
        LOG.write_text(str(exc), encoding="utf-8")
        return 1

    LOG.write_text(
        "STDOUT:\n" + proc.stdout + "\nSTDERR:\n" + proc.stderr,
        encoding="utf-8",
    )

    payload = None
    for line in reversed([x.strip() for x in proc.stdout.splitlines() if x.strip()]):
        if line.startswith("{") and line.endswith("}"):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    if payload is None:
        msg = proc.stderr.strip() or proc.stdout.strip() or "Browser Harness 未返回 JSON"
        if "Allow remote debugging" in msg or "DevToolsActivePort" in msg:
            errors.append("Chrome 远程调试未授权：请在 chrome://inspect/#remote-debugging 勾选允许并点击 Allow")
        else:
            errors.append(msg[-1000:])
        result = base_result(config, "failed", errors)
        write_json(RESULT, result)
        return proc.returncode or 1

    status = payload.get("status", "failed")
    page_info = payload.get("page_info") or payload.get("initial_page_info") or {}
    result = base_result(config, status, [], page_info.get("url", ""))

    if status == "success":
        raw_fields = payload.get("raw_fields") or {}
        metrics = {}
        for key, raw in raw_fields.items():
            spec = (config.get("fields") or {}).get(key, {})
            metrics[key] = clean_number(raw, spec.get("type", "decimal"))
        result["metrics"] = metrics
        if not metrics:
            result["status"] = "partial_success"
            result["errors"].append("已完成点击和截图，但 config.json 未配置字段")
    else:
        reason = payload.get("reason")
        if reason:
            result["errors"].append(reason)
        candidates = payload.get("candidates")
        if candidates:
            result["errors"].append("候选入口已写入 run.log 和 visible-text.json")

    write_json(RESULT, result)
    return 0 if result["status"] in {"success", "partial_success"} else 1


if __name__ == "__main__":
    sys.exit(main())
