import crypto from "node:crypto";
import fs from "node:fs";
import { loadConfig } from "./workflow/config.mjs";
import { uploadVercelBlob } from "./workflow/upload_vercel_blob.mjs";

const config = loadConfig();

function sign(secret, timestamp) {
  return crypto.createHmac("sha256", secret).update(`${timestamp}\n${secret}`).digest("base64");
}

function loadJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function getMetric(source, key) {
  return source?.[key]?.value ?? source?.values?.[key] ?? null;
}

function pct(value) {
  if (value == null || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${(number * 100).toFixed(2)}%`;
}

function pt(value) {
  if (value == null || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}pt`;
}

function num(value, digits = 0) {
  if (value == null || value === "") return "--";
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  return number.toLocaleString("zh-CN", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function subsidy(adb, key, part) {
  return adb?.subsidies?.[key]?.[part]?.value ?? null;
}

function delta(value, type = "pct") {
  return type === "pt" ? pt(value) : pct(value);
}

function row(label, value, day, week, type = "pct") {
  return `| ${label} | **${value}** | ${delta(day, type)} | ${delta(week, type)} |`;
}

function alertValue(value, triggered) {
  return triggered ? `<font color="#DC2626">${value}</font>` : value;
}

function buildMarkdown(adb, web, imageUrl) {
  return {
    msgtype: "markdown",
    markdown: {
      title: config.dingtalk.message_title || "香河实时播报",
      text: imageUrl ? `![香河实时播报](${imageUrl})` : "",
    },
  };
}

async function main() {
  const requiredStatus = config.dingtalk.require_quality_status || "passed";
  const quality = loadJson(config.paths.quality_report);
  if (quality?.status !== requiredStatus) {
    console.error(`quality gate blocked send: expected ${requiredStatus}, got ${quality?.status || "missing"}`);
    process.exit(3);
  }

  if (!config.dingtalk.webhook_url) {
    console.error("config.json missing dingtalk.webhook_url");
    process.exit(1);
  }

  const adb = loadJson(config.paths.adb_data);
  const web = loadJson(config.paths.web_data);
  if (!adb || !web) {
    console.error("Missing adb or web data json.");
    process.exit(1);
  }

  const blobResult = await uploadVercelBlob();
  const payload = buildMarkdown(adb, web, blobResult.url);
  const timestamp = Date.now();
  const signature = config.dingtalk.webhook_secret
    ? `&timestamp=${timestamp}&sign=${encodeURIComponent(sign(config.dingtalk.webhook_secret, timestamp))}`
    : "";
  const response = await fetch(`${config.dingtalk.webhook_url}${signature}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const result = await response.json();
  if (result.errcode !== 0) {
    console.error(JSON.stringify(result, null, 2));
    process.exit(2);
  }

  console.log(JSON.stringify({
    status: "sent_markdown_with_vercel_blob_image",
    channel: "dingtalk_webhook",
    png_url: blobResult.url,
    blob_provider: blobResult.provider,
    blob_pathname: blobResult.pathname,
    url_checks: blobResult.url_checks,
  }, null, 2));
}

main();
