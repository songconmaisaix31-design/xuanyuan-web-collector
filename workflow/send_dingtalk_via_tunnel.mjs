/**
 * 通过本地 cloudflared Quick Tunnel 暴露 PNG 并发送钉钉 webhook。
 *
 * 前置条件：
 *   1. cloudflared.exe 位于项目根目录
 *   2. Python 3 可用
 *   3. config.json 中 dingtalk.webhook_url 和 webhook_secret 已配置
 *
 * 用法：
 *   node workflow/send_dingtalk_via_tunnel.mjs [png路径]
 *
 * 经验教训：
 *   - cloudflared 连接 trycloudflare.com 时必须绕过系统代理（清空 HTTP_PROXY/HTTPS_PROXY）
 *   - tunnel 和 HTTP server 需保持存活直到钉钉拉到图片，不能用带 timeout 的 bash
 *   - 钉钉机器人 markdown ![]() 语法支持外部图片，前提是 URL 可被钉钉服务器访问
 */

import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { loadConfig } from "./config.mjs";

const config = loadConfig();
const ROOT = config.paths.root;

const tunnelExe = path.join(ROOT, "cloudflared.exe");
const pngPath = process.argv[2] || path.join(config.paths.output_dir, "filled-preview.png");

if (!fs.existsSync(tunnelExe)) {
  console.error("cloudflared.exe 未找到，请放置在项目根目录");
  process.exit(1);
}

if (!fs.existsSync(pngPath)) {
  console.error(`PNG 文件不存在: ${pngPath}`);
  process.exit(1);
}

const pngDir = path.dirname(pngPath);
const pngFile = path.basename(pngPath);
const httpPort = 8899;

async function assertImageUrlAvailable(url) {
  const checks = [];
  for (let attempt = 1; attempt <= 12; attempt++) {
    if (attempt > 1) {
      await new Promise((resolve) => setTimeout(resolve, 2500));
    }
    const result = await new Promise((resolve) => {
      const curl = spawn("curl.exe", [
        "--location",
        "--silent",
        "--show-error",
        "--max-time", "20",
        "--noproxy", "*",
        "--output", "NUL",
        "--write-out", "%{http_code}\\n%{content_type}\\n%{size_download}",
        url,
      ], {
        cwd: ROOT,
        stdio: ["ignore", "pipe", "pipe"],
        env: {
          ...process.env,
          HTTP_PROXY: "",
          HTTPS_PROXY: "",
          http_proxy: "",
          https_proxy: "",
          NO_PROXY: "*",
        },
      });
      let stdout = "";
      let stderr = "";
      curl.stdout.on("data", (data) => { stdout += data.toString(); });
      curl.stderr.on("data", (data) => { stderr += data.toString(); });
      curl.on("close", (code) => {
        const [statusRaw, contentTypeRaw, sizeRaw] = stdout.trim().split(/\r?\n/);
        resolve({
          attempt,
          code,
          status: Number(statusRaw || 0),
          content_type: contentTypeRaw || "",
          size_download: Number(sizeRaw || 0),
          stderr: stderr.trim(),
        });
      });
    });
    checks.push(result);
    if (
      result.code === 0
      && result.status >= 200
      && result.status < 300
      && String(result.content_type).toLowerCase().includes("image/")
      && result.size_download > 0
    ) {
      return checks;
    }
  }
  throw new Error(`图片 URL 可用性校验失败，已取消发送: ${JSON.stringify(checks)}`);
}

// ========== Step 1: 启动 HTTP Server ==========
console.log(`[1/4] 启动 HTTP Server (port ${httpPort})...`);

// 先释放可能被占用的端口
const killPort = spawn("cmd", ["/c", `for /f "tokens=5" %a in ('netstat -ano ^| findstr :${httpPort}') do taskkill /F /PID %a 2>nul`], {
  stdio: "ignore",
});
await new Promise((resolve) => { killPort.on("close", resolve); setTimeout(resolve, 1000); });

const httpServer = spawn("python", ["-m", "http.server", String(httpPort), "--directory", pngDir], {
  cwd: ROOT,
  stdio: ["ignore", "pipe", "pipe"],
  env: { ...process.env },
});

httpServer.stderr.on("data", (d) => process.stderr.write(`[http] ${d}`));

// Python http.server 的 "Serving HTTP" 日志在 stderr，等待即可
await new Promise((resolve) => setTimeout(resolve, 2000));

// ========== Step 2: 启动 cloudflared Tunnel (绕过代理，支持重试) ==========
console.log("[2/4] 启动 cloudflared Quick Tunnel（绕过代理）...");
const tunnelEnv = { ...process.env };
delete tunnelEnv.HTTP_PROXY;
delete tunnelEnv.HTTPS_PROXY;
delete tunnelEnv.http_proxy;
delete tunnelEnv.https_proxy;
tunnelEnv.NO_PROXY = "*";

let tunnelUrl = null;

let tunnelProcess = null;

for (let attempt = 1; attempt <= 3; attempt++) {
  if (attempt > 1) console.log(`   重试 ${attempt}/3...`);
  let tunnelBuffer = "";
  let tunnelKilled = false;

  const tunnel = spawn(tunnelExe, ["tunnel", "--url", `http://localhost:${httpPort}`, "--no-autoupdate"], {
    cwd: ROOT,
    stdio: ["ignore", "pipe", "pipe"],
    env: tunnelEnv,
  });
  tunnelProcess = tunnel;

  function onTunnelData(data) {
    const msg = data.toString();
    tunnelBuffer += msg;
    process.stderr.write(`[cf] ${msg}`);
    const match = tunnelBuffer.match(/https:\/\/(?!api\.)[a-zA-Z0-9-]+\.trycloudflare\.com/);
    if (match && !tunnelUrl) {
      tunnelUrl = match[0];
    }
  }

  tunnel.stdout.on("data", onTunnelData);
  tunnel.stderr.on("data", onTunnelData);

  try {
    await new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        tunnelKilled = true;
        tunnel.kill();
        reject(new Error(`Tunnel 启动超时 (attempt ${attempt})`));
      }, 15000);
      const check = setInterval(() => {
        if (tunnelUrl) { clearInterval(check); clearTimeout(timeout); resolve(); }
      }, 200);
    });
    break;
  } catch (err) {
    if (!tunnelKilled) tunnel.kill();
    if (attempt === 3) throw err;
    await new Promise((r) => setTimeout(r, 2000));
  }
}

console.log(`   Tunnel URL: ${tunnelUrl}`);

// ========== Step 3: 构造钉钉消息 ==========
console.log("[3/4] 生成签名并发送钉钉...");
const imageUrl = `${tunnelUrl}/${encodeURIComponent(pngFile)}`;
const urlChecks = await assertImageUrlAvailable(imageUrl);
console.log(`   图片 URL 校验通过: ${JSON.stringify(urlChecks)}`);
const timestamp = Date.now();
const hmac = createHmac("sha256", config.dingtalk.webhook_secret);
hmac.update(`${timestamp}\n${config.dingtalk.webhook_secret}`);
const sign = encodeURIComponent(hmac.digest("base64"));

const webhookUrl = `${config.dingtalk.webhook_url}&timestamp=${timestamp}&sign=${sign}`;

const payload = {
  msgtype: "markdown",
  markdown: {
    title: config.dingtalk.message_title || "香河实时播报",
    text: `![香河实时播报](${imageUrl})`,
  },
};

const response = await fetch(webhookUrl, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

const result = await response.json();
if (result.errcode !== 0) {
  console.error(`   DingTalk 返回错误: ${JSON.stringify(result)}`);
} else {
  console.log(`   ✅ 发送成功 (errcode: 0)`);
  console.log(`   图片 URL: ${imageUrl}`);
}

// ========== Step 4: 保持存活，等待钉钉拉图 ==========
console.log("[4/4] Tunnel 保持存活（30 秒后自动关闭）...");
console.log("   按 Ctrl+C 可提前终止");

// 等待 30 秒让钉钉拉取图片
await new Promise((resolve) => setTimeout(resolve, 30000));

// 清理
tunnelProcess?.kill();
httpServer.kill();
console.log("清理完成。");
