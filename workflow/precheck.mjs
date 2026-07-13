/**
 * 香河实时播报 · 预检脚本
 *
 * 检查两项前置依赖是否就绪：
 *   1. Web：浏览器中是否有 xy.ele.me 标签页，或能否新建
 *   2. ADB：是否有已授权的 Android 设备
 *
 * Usage:
 *   node workflow/precheck.mjs          # 输出 JSON + stderr 日志
 *   node workflow/precheck.mjs --json   # 纯 JSON，无日志
 */

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(moduleDir, "..");
const adb = path.join(root, "tools", "platform-tools", "adb.exe");
const jsonMode = process.argv.includes("--json");

function log(msg) {
  if (!jsonMode) process.stderr.write(`[precheck] ${msg}\n`);
}

function runBrowserHarness(code, timeout = 30) {
  const out = execFileSync("browser-harness", {
    input: code,
    encoding: "utf8",
    timeout: timeout * 1000,
    stdio: ["pipe", "pipe", "pipe"],
  });
  // 提取最后一行 JSON
  const lines = out.trim().split("\n").filter(Boolean);
  for (const line of lines.reverse()) {
    if (line.startsWith("{")) {
      try { return JSON.parse(line); } catch {}
    }
  }
  return null;
}

// ── Web 检查 ──────────────────────────────────────────
function checkWeb() {
  log("检查 Web 端 ...");

  try {
    // 1. 先看有没有现成的标签页
    const payload = runBrowserHarness(`
import json
tabs = list_tabs(include_chrome=False)
found = [t for t in tabs if "xy.ele.me" in (t.get("url") or "")]
print(json.dumps({"found": len(found) > 0, "count": len(found), "urls": [t.get("url","") for t in found[:3]]}))
`, 15);

    if (payload && payload.found) {
      log(`OK: 发现 ${payload.count} 个 xy.ele.me 标签页`);
      return { status: "ok", detail: `已有 ${payload.count} 个标签页` };
    }

    // 2. 没有则尝试新建
    log("未发现标签页，尝试打开新标签页 ...");
    const navPayload = runBrowserHarness(`
import json
new_tab("https://xy.ele.me/cddp")
wait_for_load(15)
wait_for_network_idle(8, 1000)
info = page_info()
print(json.dumps({"url": info.get("url",""), "title": info.get("title","")}))
`, 30);

    if (navPayload && navPayload.url) {
      log(`OK: 新标签页已打开 → ${navPayload.url}`);
      return { status: "ok", detail: "新标签页已打开（需确认登录态）" };
    }

    return { status: "fail", detail: "无法打开 xy.ele.me/cddp（可能网络或页面异常）" };
  } catch (err) {
    const msg = err.message || String(err);
    if (msg.includes("not found") || msg.includes("ENOENT")) {
      return { status: "fail", detail: "browser-harness 未安装或不在 PATH 中" };
    }
    return { status: "fail", detail: `browser-harness 异常: ${msg.slice(0, 200)}` };
  }
}

// ── ADB 检查 ──────────────────────────────────────────
function checkAdb() {
  log("检查 ADB 端 ...");

  if (!fs.existsSync(adb)) {
    return { status: "fail", detail: `adb 未找到: ${adb}` };
  }

  try {
    const out = execFileSync(adb, ["devices"], {
      encoding: "utf8",
      timeout: 10000,
      stdio: ["ignore", "pipe", "pipe"],
    });

    const lines = out.split("\n");
    let foundDevice = false;
    let unauthorized = false;
    let serial = null;

    for (const line of lines.slice(1)) {
      const parts = line.trim().split(/\s+/);
      if (parts.length < 2) continue;
      if (parts[1] === "device") {
        foundDevice = true;
        serial = parts[0];
      }
      if (parts[1] === "unauthorized") unauthorized = true;
    }

    if (foundDevice) {
      log(`OK: 已授权设备 ${serial}`);
      return { status: "ok", detail: `设备 ${serial} 已连接且已授权` };
    }
    if (unauthorized) {
      return { status: "fail", detail: "设备未授权，请在手机上允许 USB 调试" };
    }
    return { status: "fail", detail: "未发现 Android 设备" };
  } catch (err) {
    return { status: "fail", detail: `adb 执行失败: ${(err.message || String(err)).slice(0, 200)}` };
  }
}

// ── 主流程 ────────────────────────────────────────────
function main() {
  const webResult = checkWeb();
  const adbResult = checkAdb();

  const allOk = webResult.status === "ok" && adbResult.status === "ok";
  const failed = [];
  if (webResult.status !== "ok") failed.push({ name: "web", detail: webResult.detail });
  if (adbResult.status !== "ok") failed.push({ name: "adb", detail: adbResult.detail });

  const report = {
    checked_at: new Date().toISOString(),
    status: allOk ? "passed" : "failed",
    web: webResult,
    adb: adbResult,
    failed,
  };

  console.log(JSON.stringify(report, null, 2));

  if (!jsonMode) {
    if (allOk) {
      log("✅ 全部就绪");
    } else {
      log("❌ 预检未通过：");
      for (const f of failed) {
        log(`   - ${f.name}: ${f.detail}`);
      }
    }
  }

  process.exit(allOk ? 0 : 1);
}

main();
