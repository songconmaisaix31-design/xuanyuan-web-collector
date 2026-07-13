/**
 * 通过 cloudflared Quick Tunnel 将 PNG 发送到钉钉 webhook（仅图片）。
 * 启动后保持 tunnel 存活，Ctrl+C 退出。
 * 
 * 用法: node send_png_dingtalk.mjs [png路径]
 */
import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { loadConfig } from "./workflow/config.mjs";

const config = loadConfig();
const ROOT = config.paths.root;

const pngPath = process.argv[2]
  || path.join(config.paths.output_dir, "filled-preview.png");

if (!fs.existsSync(pngPath)) {
  console.error(`PNG 不存在: ${pngPath}`);
  process.exit(1);
}

const pngDir = path.dirname(pngPath);
const pngFile = path.basename(pngPath);
const HTTP_PORT = 8899;

// ===== 启动 HTTP Server =====
console.log(`[http] 启动 HTTP Server :${HTTP_PORT}`);
const http = spawn("python", [
  "-m", "http.server", String(HTTP_PORT),
  "--directory", pngDir,
], { stdio: "ignore" });

// ===== 启动 cloudflared（绕过代理，崩溃自动重试）=====
console.log(`[cf]   启动 cloudflared tunnel → localhost:${HTTP_PORT}`);
const cfEnv = { ...process.env };
delete cfEnv.HTTP_PROXY; delete cfEnv.HTTPS_PROXY;
delete cfEnv.http_proxy; delete cfEnv.https_proxy;
cfEnv.NO_PROXY = "*";

let cf = null;
let tunnelUrl = null;
let output = "";

function startCf() {
  cf = spawn(
    path.join(ROOT, "cloudflared.exe"),
    ["tunnel", "--url", `http://localhost:${HTTP_PORT}`, "--no-autoupdate"],
    { stdio: ["ignore", "pipe", "pipe"], env: cfEnv },
  );
  cf.stdout.on("data", onCfData);
  cf.stderr.on("data", onCfData);
  cf.on("exit", (code) => {
    if (!tunnelUrl) {
      console.error(`\n[cf] tunnel 退出 (code ${code})，3秒后重试...`);
      setTimeout(startCf, 3000);
    }
  });
}

function onCfData(data) {
  output += data.toString();
  process.stderr.write(data);
  const m = output.match(/https:\/\/(?!api\.)[\w-]+\.trycloudflare\.com/);
  if (m && !tunnelUrl) {
    tunnelUrl = m[0];
    onTunnelReady();
  }
}

startCf();

// ===== Tunnel 就绪后发送钉钉 =====
async function onTunnelReady() {
  const imageUrl = `${tunnelUrl}/${encodeURIComponent(pngFile)}`;
  console.log(`\n[tunnel] ${tunnelUrl}`);

  const ts = Date.now();
  const hmac = createHmac("sha256", config.dingtalk.webhook_secret);
  hmac.update(`${ts}\n${config.dingtalk.webhook_secret}`);
  const sign = encodeURIComponent(hmac.digest("base64"));
  const webhookUrl = `${config.dingtalk.webhook_url}&timestamp=${ts}&sign=${sign}`;

  const body = JSON.stringify({
    msgtype: "markdown",
    markdown: { title: "香河实时播报", text: `![香河](${imageUrl})` },
  });

  try {
    const res = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    const data = await res.json();
    if (data.errcode === 0) {
      console.log(`[钉钉] ✅ 发送成功 (errcode: 0)`);
    } else {
      console.error(`[钉钉] ❌ ${JSON.stringify(data)}`);
    }
  } catch (e) {
    console.error(`[钉钉] 发送失败: ${e.message}`);
  }

  console.log(`\n🟢 Tunnel 保持中... 确认图片收到后按 Ctrl+C 退出`);
}

// ===== 清理 =====
process.on("SIGINT", () => {
  console.log("\n清理中...");
  cf.kill();
  http.kill();
  process.exit(0);
});

console.log("按 Ctrl+C 退出\n");
