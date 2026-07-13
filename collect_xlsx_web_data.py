import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "xlsx_work" / "mapped_data.json"


def run_browser_harness():
    code = r'''
import base64
import json
import os
import re
import time

tabs = list_tabs(include_chrome=False)
xy_tabs = [t for t in tabs if "xy.ele.me" in (t.get("url") or "")]
# Prefer the cddp (盯大盘) tab; fallback to any xy.ele.me tab; open new as last resort
cddp_tabs = [t for t in xy_tabs if "cddp" in t.get("url", "")]
target = (cddp_tabs or xy_tabs)[0] if (cddp_tabs or xy_tabs) else None
if target:
    switch_tab(target)
else:
    new_tab("https://xy.ele.me/cddp")
wait_for_load(20)
wait_for_network_idle(10, 800)

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

def frame_context():
    frame_id = walk(cdp("Page.getFrameTree").get("frameTree", {}))
    if not frame_id:
        print(json.dumps({"status": "failed", "error": "business frame not found"}, ensure_ascii=False))
        raise SystemExit
    ctx = cdp("Page.createIsolatedWorld", frameId=frame_id, worldName="xuanyuan_xlsx_web", grantUniveralAccess=True)
    return ctx.get("executionContextId")

context_id = frame_context()

def eval_json(expression):
    r = cdp(
        "Runtime.evaluate",
        expression="Promise.resolve(" + expression + ").then((value) => JSON.stringify(value))",
        contextId=context_id,
        returnByValue=True,
        awaitPromise=True,
    )
    return json.loads(r.get("result", {}).get("value", "null"))

def click_text(text, contains=False):
    needle = json.dumps(text, ensure_ascii=False)
    mode = "includes" if contains else "exact"
    expression = f"""(() => {{
      const wanted = {needle};
      const mode = {json.dumps(mode)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const elements = [...document.querySelectorAll('button, [role=button], .ant-tabs-tab-btn, .ant-tabs-tab, .ant-radio-button-wrapper, .ant-segmented-item, span, div, a')];
      const matches = elements.map((el) => {{
        const text = norm(el.innerText || el.textContent || '');
        const target = norm(wanted);
        if (!text || (mode === 'exact' ? text !== target : !text.includes(target))) return null;
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return null;
        return {{ el, area: rect.width * rect.height, x: rect.x, y: rect.y, w: rect.width, h: rect.height }};
      }}).filter(Boolean).sort((a, b) => a.area - b.area);
      if (!matches.length) return {{ clicked: false, text: wanted }};
      matches[0].el.click();
      return {{ clicked: true, text: wanted, rect: {{ x: matches[0].x, y: matches[0].y, w: matches[0].w, h: matches[0].h }} }};
    }})()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(8, 500)
    return result

def click_query_button():
    expression = """(async () => {
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      document.body.click();
      await delay(250);
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };
      const buttons = [...document.querySelectorAll('button')]
        .filter(visible)
        .map((el) => {
          const text = norm(el.innerText || el.textContent || '');
          const r = el.getBoundingClientRect();
          const disabled = el.disabled || el.getAttribute('aria-disabled') === 'true' || String(el.className || '').includes('disabled');
          return { el, text, disabled, x: r.x, y: r.y, w: r.width, h: r.height };
        })
        .filter((item) => item.text === '查询' && !item.disabled)
        .sort((a, b) => b.y - a.y || b.x - a.x);
      if (!buttons.length) return { clicked: false, reason: 'query_button_not_found' };
      const target = buttons[0];
      target.el.scrollIntoView({ block: 'center', inline: 'center' });
      await delay(100);
      target.el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, view: window }));
      target.el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, view: window }));
      target.el.click();
      return {
        clicked: true,
        text: '查询',
        rect: { x: target.x, y: target.y, w: target.w, h: target.h },
        candidates: buttons.map((item) => ({ x: item.x, y: item.y, w: item.w, h: item.h })).slice(0, 5)
      };
    })()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(12, 800)
    return result

def choose_option(target, select_hint=""):
    expression = f"""(async () => {{
      const target = {json.dumps(target, ensure_ascii=False)};
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visible = (el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const visibleOptions = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode')]
        .filter(visible)
        .map((el) => {{
          const text = norm(el.innerText || el.textContent || '');
          const r = el.getBoundingClientRect();
          return {{ el, text, area: Math.max(1, r.width * r.height) }};
        }})
        .filter((item) => item.text === norm(target) || item.text.includes(norm(target)))
        .sort((a, b) => a.area - b.area);
      if (visibleOptions.length) {{
        const checkbox = visibleOptions[0].el.querySelector('.ant-select-tree-checkbox') || visibleOptions[0].el;
        checkbox.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        checkbox.click();
        await delay(500);
        return {{ selected: true, target, hint, source: 'visible-dropdown' }};
      }}
      const selects = [...document.querySelectorAll('.ant-select')]
        .filter(visible)
        .filter((el) => {{
          if (!hint) return true;
          const item = el.closest('.ant-form-item') || el.parentElement;
          return norm(item?.innerText || item?.textContent || '').includes(norm(hint));
        }});
      for (const select of selects) {{
        const selector = select.querySelector('.ant-select-selector') || select;
        selector.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        selector.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        selector.click();
        await delay(350);
        const options = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode')]
          .map((el) => {{
            const text = norm(el.innerText || el.textContent || '');
            const r = el.getBoundingClientRect();
            return {{ el, text, area: Math.max(1, r.width * r.height) }};
          }})
          .filter((item) => item.text === norm(target) || item.text.includes(norm(target)))
          .sort((a, b) => a.area - b.area);
        if (options.length) {{
          const checkbox = options[0].el.querySelector('.ant-select-tree-checkbox') || options[0].el;
          checkbox.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
          checkbox.click();
          await delay(500);
          return {{ selected: true, target, hint, selectText: select.innerText || select.textContent || '' }};
        }}
        document.body.click();
        await delay(100);
      }}
      return {{ selected: false, target, hint }};
    }})()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(8, 500)
    return result

def expand_tree_node(target, select_hint=""):
    expression = f"""(async () => {{
      const target = {json.dumps(target, ensure_ascii=False)};
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visible = (el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const selects = [...document.querySelectorAll('.ant-select')]
        .filter(visible)
        .filter((el) => {{
          if (!hint) return true;
          const item = el.closest('.ant-form-item') || el.parentElement;
          return norm(item?.innerText || item?.textContent || '').includes(norm(hint));
        }});
      for (const select of selects) {{
        const selector = select.querySelector('.ant-select-selector') || select;
        selector.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        selector.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        selector.click();
        await delay(350);
        const nodes = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode')]
          .map((el) => {{
            const text = norm(el.innerText || el.textContent || '');
            const r = el.getBoundingClientRect();
            const className = String(el.className || '');
            return {{ el, text, className, area: Math.max(1, r.width * r.height) }};
          }})
          .filter((item) => item.text === norm(target) || item.text.includes(norm(target)))
          .sort((a, b) => a.area - b.area);
        if (nodes.length) {{
          const node = nodes[0];
          const switcher = node.el.querySelector('.ant-select-tree-switcher');
          const alreadyOpen = node.className.includes('switcher-open') || String(switcher?.className || '').includes('open');
          if (switcher && !alreadyOpen) {{
            switcher.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
            switcher.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
            switcher.click();
            await delay(500);
          }}
          return {{ expanded: true, target, hint, alreadyOpen, selectText: select.innerText || select.textContent || '' }};
        }}
        document.body.click();
        await delay(100);
      }}
      return {{ expanded: false, target, hint }};
    }})()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(8, 500)
    return result

def choose_tree_child(parent_targets, child_target, select_hint=""):
    expression = f"""(async () => {{
      const parentTargets = {json.dumps(parent_targets, ensure_ascii=False)};
      const childTarget = {json.dumps(child_target, ensure_ascii=False)};
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visible = (el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const optionItems = () => [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')]
        .filter(visible)
        .map((el) => {{
          const text = norm(el.innerText || el.textContent || '');
          const r = el.getBoundingClientRect();
          const checkbox = el.querySelector('.ant-select-tree-checkbox');
          const checked = String(el.className || '').includes('checkbox-checked')
            || String(checkbox?.className || '').includes('checkbox-checked')
            || checkbox?.getAttribute('aria-checked') === 'true';
          return {{ el, text, checkbox, checked, area: Math.max(1, r.width * r.height) }};
        }});
      const findItem = (target) => optionItems()
        .filter((item) => item.text === norm(target) || item.text.includes(norm(target)))
        .sort((a, b) => a.area - b.area)[0];
      const clickItem = async (item) => {{
        if (!item) return false;
        if (item.checked) return 'already-checked';
        const target = item.checkbox || item.el;
        target.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        target.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        target.click();
        await delay(500);
        return true;
      }};
      const selects = [...document.querySelectorAll('.ant-select')]
        .filter(visible)
        .filter((el) => {{
          if (!hint) return true;
          const item = el.closest('.ant-form-item') || el.parentElement;
          return norm(item?.innerText || item?.textContent || '').includes(norm(hint));
        }});
      for (const select of selects) {{
        const selector = select.querySelector('.ant-select-selector') || select;
        selector.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        selector.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        selector.click();
        await delay(400);

        let child = findItem(childTarget);
        if (!child) {{
          for (const parentTarget of parentTargets) {{
            const parent = findItem(parentTarget);
            if (!parent) continue;
            const switcher = parent.el.querySelector('.ant-select-tree-switcher');
            const alreadyOpen = String(parent.el.className || '').includes('switcher-open') || String(switcher?.className || '').includes('open');
            if (switcher && !alreadyOpen) {{
              switcher.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
              switcher.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
              switcher.click();
              await delay(500);
            }}
            child = findItem(childTarget);
            if (child) {{
              const clicked = await clickItem(child);
              return {{ selected: true, childTarget, parentTarget, hint, clicked, selectText: select.innerText || select.textContent || '' }};
            }}
          }}
        }} else {{
          const clicked = await clickItem(child);
          return {{ selected: true, childTarget, parentTarget: null, hint, clicked, selectText: select.innerText || select.textContent || '' }};
        }}
        document.body.click();
        await delay(100);
      }}
      return {{ selected: false, childTarget, parentTargets, hint }};
    }})()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(8, 500)
    return result

def verify_tree_child_selected(child_target, select_hint=""):
    expression = f"""(async () => {{
      const childTarget = {json.dumps(child_target, ensure_ascii=False)};
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visible = (el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const forms = [...document.querySelectorAll('.ant-form-item')]
        .filter(visible)
        .filter((el) => !hint || norm(el.innerText || el.textContent || '').includes(norm(hint)));
      const form = forms[0];
      if (!form) return {{ selected: false, childTarget, hint, reason: 'form_not_found' }};
      const formText = form.innerText || form.textContent || '';
      const displaySelected = norm(formText).includes(norm(childTarget));
      const select = form.querySelector('.ant-select');
      if (select) {{
        const selector = select.querySelector('.ant-select-selector') || select;
        selector.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        selector.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        selector.click();
        await delay(350);
      }}
      const item = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')]
        .filter(visible)
        .map((el) => {{
          const text = norm(el.innerText || el.textContent || '');
          const checkbox = el.querySelector('.ant-select-tree-checkbox');
          const checked = String(el.className || '').includes('checkbox-checked')
            || String(checkbox?.className || '').includes('checkbox-checked')
            || checkbox?.getAttribute('aria-checked') === 'true';
          return {{ text, checked }};
        }})
        .find((row) => row.text === norm(childTarget) || row.text.includes(norm(childTarget)));
      document.body.click();
      await delay(100);
      return {{
        selected: displaySelected,
        displaySelected,
        dropdownChecked: !!item?.checked,
        childTarget,
        hint,
        formText,
      }};
    }})()"""
    result = eval_json(expression)
    time.sleep(0.5)
    wait_for_network_idle(5, 500)
    return result

def clear_option(select_hint):
    expression = f"""(() => {{
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const forms = [...document.querySelectorAll('.ant-form-item')]
        .filter((el) => norm(el.innerText || el.textContent || '').includes(norm(hint)));
      for (const form of forms) {{
        const clear = form.querySelector('.ant-select-clear');
        if (clear) {{
          clear.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
          clear.click();
          return {{ cleared: true, hint }};
        }}
      }}
      return {{ cleared: false, hint }};
    }})()"""
    result = eval_json(expression)
    time.sleep(1)
    wait_for_network_idle(8, 500)
    return result

def ensure_options(targets, select_hint=""):
    expression = f"""(async () => {{
      const targets = {json.dumps(targets, ensure_ascii=False)};
      const hint = {json.dumps(select_hint, ensure_ascii=False)};
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const visible = (el) => {{
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }};
      const forms = [...document.querySelectorAll('.ant-form-item')]
        .filter(visible)
        .filter((el) => !hint || norm(el.innerText || el.textContent || '').includes(norm(hint)))
        .sort((a, b) => {{
          const ai = String(a.className || '').includes('ant-form-item-inline') ? 0 : 1;
          const bi = String(b.className || '').includes('ant-form-item-inline') ? 0 : 1;
          return ai - bi;
        }});
      const selects = forms.map((form) => form.querySelector('.ant-select')).filter(Boolean);
      const selected = [];
      const missing = [];
      const clicked = [];
      if (!selects.length) return {{ selected, missing: targets, clicked, hint }};
      const select = selects[0];
      for (const target of targets) {{
        const selector = select.querySelector('.ant-select-selector') || select;
        selector.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        selector.dispatchEvent(new MouseEvent('mouseup', {{ bubbles: true, cancelable: true, view: window }}));
        selector.click();
        await delay(350);
        const options = [...document.querySelectorAll('.ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-tree-treenode, .ant-select-dropdown:not(.ant-select-dropdown-hidden) .ant-select-item-option')]
          .map((el) => {{
            const text = norm(el.innerText || el.textContent || '');
            const r = el.getBoundingClientRect();
            const checked = String(el.className || '').includes('checkbox-checked') || !!el.querySelector('.ant-select-tree-checkbox-checked');
            return {{ el, text, checked, area: Math.max(1, r.width * r.height) }};
          }})
          .filter((item) => item.text === norm(target) || item.text.includes(norm(target)))
          .sort((a, b) => a.area - b.area);
        if (!options.length) {{
          missing.push(target);
          document.body.click();
          await delay(100);
          continue;
        }}
        const option = options[0];
        if (option.checked) {{
          selected.push(target);
          document.body.click();
          await delay(100);
          continue;
        }}
        const checkbox = option.el.querySelector('.ant-select-tree-checkbox') || option.el;
        checkbox.dispatchEvent(new MouseEvent('mousedown', {{ bubbles: true, cancelable: true, view: window }}));
        checkbox.click();
        clicked.push(target);
        await delay(300);
      }}
      document.body.click();
      return {{ selected, missing, clicked, hint }};
    }})()"""
    try:
        result = eval_json(expression)
        time.sleep(1)
        wait_for_network_idle(8, 500)
        return result
    except Exception as exc:
        try:
            cdp("Page.stopLoading")
        except Exception:
            pass
        return {
            "selected": [],
            "missing": targets,
            "clicked": [],
            "hint": select_hint,
            "error": str(exc)[:300],
        }

def current_payload():
    payload = eval_json("({url: location.href, title: document.title, text: document.body.innerText || ''})")
    payload["lines"] = [x.strip() for x in payload.get("text", "").split("\n") if x.strip()]
    return payload

def extract_big_board_cards():
    return eval_json("""(() => {
      const norm = (s) => String(s || '').replace(/\\s+/g, '');
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      };
      const cleanValue = (s) => String(s || '').replace(/\\s+/g, '').trim();
      const pickDelta = (lines, label) => {
        const wanted = String(label || '').includes('�')
          ? ['\\u65e5\\u73af\\u6bd4', '\\u5468\\u540c\\u6bd4']
          : [label];
        for (let i = 0; i < lines.length; i += 1) {
          const text = lines[i];
          for (const item of wanted) {
            if (norm(text) === item && i + 1 < lines.length) return cleanValue(lines[i + 1]);
            if (norm(text).startsWith(item)) return cleanValue(text.replace(item, ''));
          }
        }
        return '';
      };
      const keyForTitle = (title) => {
        const t = norm(title);
        if (t === '\\u9a91\\u624b\\u8d1f\\u8f7d') return 'rider_load';
        if (t === '\\u5e73\\u5747\\u9884\\u6d4bT') return 'avg_predicted_t';
        if (t === '\\u59a5\\u6295\\u7387') return 'delivery_rate';
        if (t === '\\u7528\\u6237T\\u51c6\\u65f6\\u7387\\uff08\\u901a\\u7528\\uff09') return 'ontime_rate';
        if (t === '骑手负载') return 'rider_load';
        if (t === '平均预测T') return 'avg_predicted_t';
        if (t === '妥投率') return 'delivery_rate';
        if (t === '用户T准时率（通用）') return 'ontime_rate';
        return null;
      };
      const result = {};
      const cards = [...document.querySelectorAll('.ant-statistic')]
        .filter(visible)
        .map((stat) => {
          const title = stat.querySelector('.ant-statistic-title')?.innerText || '';
          const value = stat.querySelector('.ant-statistic-content-value')?.innerText
            || stat.querySelector('.ant-statistic-content')?.innerText
            || '';
          const box = stat.closest('.ant-card, .ant-col, [class*=card], [class*=Card]') || stat.parentElement;
          const lines = String(box?.innerText || stat.innerText || '').split('\\n').map((x) => x.trim()).filter(Boolean);
          const rect = stat.getBoundingClientRect();
          return { title, value, lines, x: rect.x, y: rect.y };
        });
      for (const card of cards) {
        const key = keyForTitle(card.title);
        if (!key) continue;
        result[key] = {
          raw: cleanValue(card.value),
          day: pickDelta(card.lines, '日环比'),
          week: pickDelta(card.lines, '周同比'),
          title: card.title,
          x: card.x,
          y: card.y,
          lines: card.lines.slice(0, 10),
        };
      }
      return result;
    })()""")

def wait_for_big_board_render(timeout=35, min_wait=8):
    time.sleep(min_wait)
    deadline = time.time() + timeout
    required = ["rider_load", "avg_predicted_t", "delivery_rate", "ontime_rate"]
    last_signature = None
    stable_count = 0
    last_cards = {}
    while time.time() < deadline:
        cards = extract_big_board_cards()
        last_cards = cards or {}
        signature = json.dumps(
            {name: (cards.get(name, {}) if isinstance(cards, dict) else {}).get("raw") for name in required},
            sort_keys=True,
            ensure_ascii=False,
        )
        complete = isinstance(cards, dict) and all((cards.get(name, {}) or {}).get("raw") for name in required)
        spinning = eval_json("""(() => [...document.querySelectorAll('.ant-spin-spinning, .ant-skeleton, .ant-skeleton-active')]
          .some((el) => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          }))()""")
        if complete and not spinning and signature == last_signature:
            stable_count += 1
            if stable_count >= 3:
                return {"status": "stable", "cards": cards, "signature": signature}
        else:
            stable_count = 0
        last_signature = signature
        time.sleep(1.2)
    return {"status": "timeout", "cards": last_cards, "signature": last_signature}

navigation = {}
navigation["big_board_tab"] = click_text("\u76ef\u5927\u76d8")
navigation["business_big_network"] = choose_tree_child(["\u5185\u7f51", "\u5185\u5355"], "\u5927\u7f51", "\u4e1a\u52a1\u7ebf")
navigation["business_big_network_verify"] = verify_tree_child_selected("\u5927\u7f51", "\u4e1a\u52a1\u7ebf")
if not navigation["business_big_network_verify"].get("selected"):
    print(json.dumps({
        "status": "failed",
        "error": "business line 大网 was not verified; refusing to read default/all data",
        "navigation": navigation,
    }, ensure_ascii=False))
    raise SystemExit
navigation["business_big_network"]["selected"] = True
navigation["business_big_network"]["verified_by_form_display"] = True
navigation["business_query"] = click_query_button()
if not navigation["business_query"].get("clicked"):
    print(json.dumps({"status": "failed", "error": "business query button was not clicked", "navigation": navigation}, ensure_ascii=False))
    raise SystemExit
# 等待查询结果加载完成
wait_for_network_idle(10, 1000)
time.sleep(1.5)
# 先在页面顶部获取 payload（卡片数据在 DOM 顶部）
business_payload = current_payload()
# 从 DOM 卡片直接提取指标值，避免文字解析被表格干扰
big_board_cards = eval_json("""(() => {
  const result = {};
  // 盯大盘页面中，指标卡片为 ant-statistic 组件，label 是标题，value 是内容
  const cards = [...document.querySelectorAll('.ant-statistic')];
  for (const card of cards) {
    const title = (card.querySelector('.ant-statistic-title')?.innerText || '').replace(/\\s+/g, '');
    const value = (card.querySelector('.ant-statistic-content-value')?.innerText || '').trim();
    if (!title || !value) continue;
    // 提取关键指标
    const n = parseFloat(value.replace(/,/g, ''));
    if (!isNaN(n)) {
      if (title.includes('\u59a5\u6295\u7387')) result.delivery_rate_card = n;
      if (title.includes('\u51c6\u65f6\u7387') || title.includes('\u7528\u6237T\u51c6\u65f6')) result.ontime_rate_card = n;
    }
  }
  return result;
})()""")
wait_for_network_idle(15, 1200)
big_board_render = wait_for_big_board_render()
big_board_cards = big_board_render.get("cards", {})
business_payload = current_payload()
try:
    cdp("Runtime.evaluate", expression="window.scrollBy(0, 800)", contextId=context_id)
    time.sleep(1)
    big_board_screenshot = cdp("Page.captureScreenshot", format="png").get("data")
    if big_board_screenshot:
        os.makedirs("output", exist_ok=True)
        with open("output/web_big_board.png", "wb") as screenshot_file:
            screenshot_file.write(base64.b64decode(big_board_screenshot))
    business_payload_scrolled = current_payload()
except Exception:
    business_payload_scrolled = {"lines": []}
business_lines = business_payload.get("lines", [])
for item in business_payload_scrolled.get("lines", []):
    if item not in business_lines:
        business_lines.append(item)

day_label = "\u65e5\u73af\u6bd4"
week_label = "\u5468\u540c\u6bd4"
update_prefix = "\u6570\u636e\u66f4\u65b0\u65f6\u95f4\uff1a"

def parse_num(s):
    s = str(s).replace(",", "").replace("\u00a5", "").replace("\uffe5", "").strip()
    s = s.replace("\u5206\u949f", "").replace("\u5355", "").replace("\u4eba", "")
    if not s or s in ("--", "-"):
        return None
    match = re.search(r"[+-]?\d+(?:\.\d+)?", s)
    if not match:
        return None
    if "%" in s:
        return float(match.group(0)) / 100
    if s.endswith("\u5206"):
        s = match.group(0)
    try:
        v = float(match.group(0))
        return int(v) if v.is_integer() else v
    except Exception:
        return None

def clean_delta(raw, label):
    raw = str(raw or "").strip()
    return raw[len(label):].strip() if raw.startswith(label) else raw

def metric_from_cards(source_lines, label):
    for i, line in enumerate(source_lines):
        if line != label:
            continue
        value = source_lines[i + 1] if i + 1 < len(source_lines) else ""
        if parse_num(value) is None:
            continue
        day = ""
        week = ""
        for j in range(i + 2, min(i + 8, len(source_lines))):
            if source_lines[j] == day_label and j + 1 < len(source_lines):
                day = source_lines[j + 1]
            if source_lines[j] == week_label and j + 1 < len(source_lines):
                week = source_lines[j + 1]
        return {
            "raw": value,
            "day": day,
            "week": week,
            "value": parse_num(value),
            "day_value": parse_num(day),
            "week_value": parse_num(week),
            "status": "success",
        }
    return {"raw": "", "day": "", "week": "", "value": None, "day_value": None, "week_value": None, "status": "invalid"}

def metric_from_dom_cards(card_metrics, name):
    card = card_metrics.get(name, {}) if isinstance(card_metrics, dict) else {}
    value = card.get("raw", "")
    parsed = parse_num(value)
    if parsed is None:
        return {"raw": "", "day": "", "week": "", "value": None, "day_value": None, "week_value": None, "status": "invalid"}
    day = card.get("day", "")
    week = card.get("week", "")
    return {
        "raw": value,
        "day": day,
        "week": week,
        "value": parsed,
        "day_value": parse_num(day),
        "week_value": parse_num(week),
        "status": "success",
        "dom_card": card,
    }

def prefer_dom_metric(card_metrics, name, source_lines, label):
    metric = metric_from_dom_cards(card_metrics, name)
    return metric if metric.get("status") == "success" else metric_from_cards(source_lines, label)

def parse_big_board_cards(source_lines, card_metrics):
    return {
        "source_label": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51",
        "orders": metric_from_cards(source_lines, "\u63a8\u5355\u91cf"),
        "rider_load": prefer_dom_metric(card_metrics, "rider_load", source_lines, "\u9a91\u624b\u8d1f\u8f7d"),
        "avg_predicted_t": prefer_dom_metric(card_metrics, "avg_predicted_t", source_lines, "\u5e73\u5747\u9884\u6d4bT"),
        "delivery_rate": prefer_dom_metric(card_metrics, "delivery_rate", source_lines, "\u59a5\u6295\u7387"),
        "ontime_rate": prefer_dom_metric(card_metrics, "ontime_rate", source_lines, "\u7528\u6237T\u51c6\u65f6\u7387\uff08\u901a\u7528\uff09"),
    }

def parse_city_rows(source_lines):
    city = "\u9999\u6cb3\u53bf"
    header_start = None
    first_row = None
    for i, line in enumerate(source_lines):
        if source_lines[i].startswith(city + "\t"):
            first_row = i
            for j in range(i - 1, -1, -1):
                if source_lines[j] == "\u63a8\u5355\u91cf":
                    header_start = j
                    break
        if first_row is not None:
            break
    if header_start is None or first_row is None:
        return {}, []

    headers = source_lines[header_start:first_row]
    if headers and "\u63a8\u5355\u91cf" not in headers[0]:
        while headers and "\u63a8\u5355\u91cf" not in headers[0]:
            headers.pop(0)
    header_index = {name: idx for idx, name in enumerate(headers)}

    def metric_from_row(row_start, header_name):
        idx = header_index.get(header_name)
        if idx is None:
            return {"raw": "", "day": "", "week": "", "value": None, "day_value": None, "week_value": None, "status": "invalid"}
        base = row_start + 1 + idx * 3
        raw = source_lines[base] if base < len(source_lines) else ""
        day = clean_delta(source_lines[base + 1] if base + 1 < len(source_lines) else "", day_label)
        week = clean_delta(source_lines[base + 2] if base + 2 < len(source_lines) else "", week_label)
        value = parse_num(raw)
        return {
            "raw": raw,
            "day": day,
            "week": week,
            "value": value,
            "day_value": parse_num(day),
            "week_value": parse_num(week),
            "status": "success" if value is not None else "invalid",
        }

    result = {}
    for i in range(first_row, len(source_lines)):
        if not source_lines[i].startswith(city + "\t"):
            continue
        source_name = source_lines[i].split("\t", 1)[1].strip()
        result[source_name] = {
            "source_label": "\u9999\u6cb3\u53bf\u6c47\u603b" if source_name == "-" else source_name,
            "orders": metric_from_row(i, "\u63a8\u5355\u91cf"),
            "attendance": metric_from_row(i, "\u51fa\u52e4\u9a91\u624b\u6570"),
            "working_riders": metric_from_row(i, "\u5f00\u5de5\u9a91\u624b\u6570"),
            "rider_load": metric_from_row(i, "\u9a91\u624b\u8d1f\u8f7d"),
            "avg_predicted_t": metric_from_row(i, "\u5e73\u5747\u9884\u6d4bT"),
            "delivery_rate": metric_from_row(i, "\u59a5\u6295\u7387"),
            "ontime_rate": metric_from_row(i, "\u7528\u6237T\u51c6\u65f6\u7387\uff08\u901a\u7528\uff09"),
        }
    return result, headers

business_rows, business_headers = parse_city_rows(business_lines)
business_summary = parse_big_board_cards(business_lines, big_board_cards)
big_board_metric_names = ["avg_predicted_t", "delivery_rate", "ontime_rate"]
big_board_metric_issues = [
    name for name in big_board_metric_names
    if business_summary.get(name, {}).get("status") != "success"
]

navigation["city_tab"] = click_text("\u76ef\u57ce\u5e02")
navigation["capacity_tab"] = click_text("\u8fd0\u529b")
navigation["capacity_clear"] = clear_option("\u8fd0\u529b\u7ebf")
navigation["capacity_big_logistics"] = choose_option("\u5927\u7269\u6d41", "\u8fd0\u529b\u7ebf")
navigation["capacity_ensure_lines"] = ensure_options(["\u4e13\u9001", "\u8702\u8dd1", "\u4f18\u9009", "\u666e\u4f17", "\u8054\u76df"], "\u8fd0\u529b\u7ebf")
navigation["capacity_query"] = click_text("\u67e5\u8be2", contains=True)
payload = current_payload()
lines = payload.get("lines", [])
capacity_raw_rows, parsed_headers = parse_city_rows(lines)

def mapped_capacity_rows(rows):
    mapped = {}
    for source_name, target_name in [("-", "raw_summary"), ("\u4e13\u9001", "dedicated"), ("\u4f18\u9009", "preferred"), ("\u666e\u4f17", "ordinary"), ("\u8702\u8dd1", "fengpao"), ("\u4f18\u8fdc", "remote"), ("\u8054\u76df", "alliance"), ("\u672a\u77e5", "unknown")]:
        if source_name in rows:
            mapped[target_name] = rows[source_name]
    return mapped

def simple_metric(value):
    return {"raw": str(value) if value is not None else "", "value": value, "status": "success" if value is not None else "invalid"}

capacity_line_order = ["\u4e13\u9001", "\u8702\u8dd1", "\u4f18\u9009", "\u666e\u4f17", "\u8054\u76df"]
known_labels = [name for name in capacity_line_order if name in capacity_raw_rows]
known_detail = [capacity_raw_rows[name] for name in known_labels]
summary_attendance = sum((row.get("attendance", {}).get("value") or 0) for row in known_detail)
summary_working = sum((row.get("working_riders", {}).get("value") or 0) for row in known_detail)
capacity_rows = mapped_capacity_rows(capacity_raw_rows)
capacity_rows["summary"] = {
    "source_label": "\u8fd0\u529b\u7ebf\u6c47\u603b\uff08\u4e0d\u542b\u672a\u77e5\uff09",
    "attendance": simple_metric(summary_attendance if known_detail else None),
    "working_riders": simple_metric(summary_working if known_detail else None),
    "delivery_rate": capacity_raw_rows.get("-", {}).get("delivery_rate", simple_metric(None)),
    "ontime_rate": capacity_raw_rows.get("-", {}).get("ontime_rate", simple_metric(None)),
}
capacity_detail_rows = [
    {
        "line": "\u6c47\u603b\uff08\u4e0d\u542b\u672a\u77e5\uff09",
        "attendance": summary_attendance if known_detail else None,
        "attendance_day": capacity_raw_rows.get("-", {}).get("attendance", {}).get("day_value"),
        "attendance_week": capacity_raw_rows.get("-", {}).get("attendance", {}).get("week_value"),
        "working_riders": summary_working if known_detail else None,
        "working_riders_day": capacity_raw_rows.get("-", {}).get("working_riders", {}).get("day_value"),
        "working_riders_week": capacity_raw_rows.get("-", {}).get("working_riders", {}).get("week_value"),
        "delivery_rate": capacity_raw_rows.get("-", {}).get("delivery_rate", {}).get("value"),
        "delivery_rate_day": capacity_raw_rows.get("-", {}).get("delivery_rate", {}).get("day_value"),
        "delivery_rate_week": capacity_raw_rows.get("-", {}).get("delivery_rate", {}).get("week_value"),
        "ontime_rate": capacity_raw_rows.get("-", {}).get("ontime_rate", {}).get("value"),
        "ontime_rate_day": capacity_raw_rows.get("-", {}).get("ontime_rate", {}).get("day_value"),
        "ontime_rate_week": capacity_raw_rows.get("-", {}).get("ontime_rate", {}).get("week_value"),
    },
]
for source_name in known_labels:
    row = capacity_raw_rows[source_name]
    capacity_detail_rows.append({
        "line": source_name,
        "attendance": row.get("attendance", {}).get("value"),
        "attendance_day": row.get("attendance", {}).get("day_value"),
        "attendance_week": row.get("attendance", {}).get("week_value"),
        "working_riders": row.get("working_riders", {}).get("value"),
        "working_riders_day": row.get("working_riders", {}).get("day_value"),
        "working_riders_week": row.get("working_riders", {}).get("week_value"),
        "delivery_rate": row.get("delivery_rate", {}).get("value"),
        "delivery_rate_day": row.get("delivery_rate", {}).get("day_value"),
        "delivery_rate_week": row.get("delivery_rate", {}).get("week_value"),
        "ontime_rate": row.get("ontime_rate", {}).get("value"),
        "ontime_rate_day": row.get("ontime_rate", {}).get("day_value"),
        "ontime_rate_week": row.get("ontime_rate", {}).get("week_value"),
    })

capacity_summary = capacity_rows.get("summary", {})
def row_metric(name):
    return business_summary.get(name, {"raw": "", "day": "", "week": "", "value": None, "day_value": None, "week_value": None, "status": "invalid"})

def capacity_metric(name):
    return capacity_summary.get(name, {"raw": "", "day": "", "week": "", "value": None, "day_value": None, "week_value": None, "status": "invalid"})

def rider_load_metric():
    metric = row_metric("rider_load")
    if metric.get("status") == "success":
        return metric, "web.big_board"
    return capacity_rows.get("raw_summary", {}).get("rider_load", metric), "web.city_capacity"

updated_at = ""
for line in business_lines + lines:
    if line.startswith(update_prefix):
        updated_at = line[len(update_prefix):].strip()
        break
rider_load, rider_load_source_prefix = rider_load_metric()
values = {
    "attendance": capacity_metric("attendance")["value"],
    "attendance_day": None,
    "attendance_week": None,
    "working_riders": capacity_metric("working_riders")["value"],
    "working_riders_day": None,
    "working_riders_week": None,
    "rider_load": rider_load["value"],
    "rider_load_day": rider_load["day_value"],
    "rider_load_week": rider_load["week_value"],
    "avg_predicted_t": row_metric("avg_predicted_t")["value"],
    "avg_predicted_t_day": row_metric("avg_predicted_t")["day_value"],
    "avg_predicted_t_week": row_metric("avg_predicted_t")["week_value"],
    "delivery_rate": row_metric("delivery_rate")["value"],
    "delivery_rate_day": row_metric("delivery_rate")["day_value"],
    "delivery_rate_week": row_metric("delivery_rate")["week_value"],
    "ontime_rate": row_metric("ontime_rate")["value"],
    "ontime_rate_day": row_metric("ontime_rate")["day_value"],
    "ontime_rate_week": row_metric("ontime_rate")["week_value"],
}
field_sources = {
    "attendance": "web.city_capacity.attendance",
    "attendance_day": "web.city_capacity.attendance_day",
    "attendance_week": "web.city_capacity.attendance_week",
    "working_riders": "web.city_capacity.working_riders",
    "working_riders_day": "web.city_capacity.working_riders_day",
    "working_riders_week": "web.city_capacity.working_riders_week",
    "rider_load": f"{rider_load_source_prefix}.rider_load",
    "rider_load_day": f"{rider_load_source_prefix}.rider_load_day",
    "rider_load_week": f"{rider_load_source_prefix}.rider_load_week",
    "avg_predicted_t": "web.big_board.avg_predicted_t",
    "avg_predicted_t_day": "web.big_board.avg_predicted_t_day",
    "avg_predicted_t_week": "web.big_board.avg_predicted_t_week",
    "delivery_rate": "web.big_board.delivery_rate",
    "delivery_rate_day": "web.big_board.delivery_rate_day",
    "delivery_rate_week": "web.big_board.delivery_rate_week",
    "ontime_rate": "web.big_board.ontime_rate",
    "ontime_rate_day": "web.big_board.ontime_rate_day",
    "ontime_rate_week": "web.big_board.ontime_rate_week",
}
web_big_board_values = {
    "web_big_board_avg_predicted_t": values["avg_predicted_t"],
    "web_big_board_avg_predicted_t_day": values["avg_predicted_t_day"],
    "web_big_board_avg_predicted_t_week": values["avg_predicted_t_week"],
    "web_big_board_delivery_rate": values["delivery_rate"],
    "web_big_board_delivery_rate_day": values["delivery_rate_day"],
    "web_big_board_delivery_rate_week": values["delivery_rate_week"],
    "web_big_board_ontime_rate": values["ontime_rate"],
    "web_big_board_ontime_rate_day": values["ontime_rate_day"],
    "web_big_board_ontime_rate_week": values["ontime_rate_week"],
}
if rider_load_source_prefix == "web.big_board":
    web_big_board_values.update({
        "web_big_board_rider_load": values["rider_load"],
        "web_big_board_rider_load_day": values["rider_load_day"],
        "web_big_board_rider_load_week": values["rider_load_week"],
    })
web_city_capacity_values = {
    "web_city_capacity_attendance": values["attendance"],
    "web_city_capacity_attendance_day": values["attendance_day"],
    "web_city_capacity_attendance_week": values["attendance_week"],
    "web_city_capacity_working_riders": values["working_riders"],
    "web_city_capacity_working_riders_day": values["working_riders_day"],
    "web_city_capacity_working_riders_week": values["working_riders_week"],
}
if rider_load_source_prefix == "web.city_capacity":
    web_city_capacity_values.update({
        "web_city_capacity_rider_load": values["rider_load"],
        "web_city_capacity_rider_load_day": values["rider_load_day"],
        "web_city_capacity_rider_load_week": values["rider_load_week"],
    })
out = {
    "status": "failed" if big_board_metric_issues else "success",
    "errors": [f"\u76ef\u5927\u76d8-\u5927\u7f51\u5361\u7247\u6307\u6807\u7f3a\u5931: {', '.join(big_board_metric_issues)}"] if big_board_metric_issues else [],
    "source_namespace": "web",
    "source_url": "https://xy.ele.me/cddp",
    "frame_url": payload.get("url", ""),
    "updated_at": updated_at,
    "navigation": navigation,
    "big_board_render": big_board_render,
    "big_board_metric_source": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51-\u70b9\u51fb\u5927\u7f51\u540e\u5f53\u524d\u754c\u9762",
    "logistics_metric_sources": {
        "delivery_rate": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51-\u70b9\u51fb\u5927\u7f51\u540e\u7684\u59a5\u6295\u7387",
        "ontime_rate": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51-\u70b9\u51fb\u5927\u7f51\u540e\u7684\u7528\u6237T\u51c6\u65f6\u7387\uff08\u901a\u7528\uff09",
        "avg_predicted_t": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51-\u70b9\u51fb\u5927\u7f51\u540e\u7684\u5e73\u5747\u9884\u6d4bT",
        "rider_load": "\u76ef\u5927\u76d8-\u4e1a\u52a1\u7ebf\u5927\u7f51-\u70b9\u51fb\u5927\u7f51\u540e\u7684\u9a91\u624b\u8d1f\u8f7d",
    },
    "big_board_card_metrics": {name: business_summary.get(name) for name in ["rider_load", *big_board_metric_names]},
    "business_headers": business_headers,
    "table_headers": parsed_headers,
    "business_rows": business_rows,
    "capacity_rows": capacity_rows,
    "capacity_detail_rows": capacity_detail_rows,
    "field_sources": field_sources,
    "web_big_board_values": web_big_board_values,
    "web_city_capacity_values": web_city_capacity_values,
    "web_values": {**web_big_board_values, **web_city_capacity_values},
    "values": values,
}
print(json.dumps(out, ensure_ascii=False))
'''
    code = code.encode("ascii", "backslashreplace").decode("ascii")
    return subprocess.run(
        ["browser-harness"],
        input=code,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        cwd=str(ROOT),
        timeout=120,
    )


def main():
    proc = run_browser_harness()
    payload = None
    for line in reversed([x.strip() for x in proc.stdout.splitlines() if x.strip()]):
        if line.startswith("{") and line.endswith("}"):
            payload = json.loads(line)
            break
    if payload is None:
        payload = {"status": "failed", "error": (proc.stderr or proc.stdout)[-1000:]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("status") == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
