import crypto from "node:crypto";
import fs from "node:fs";
import { loadConfig } from "./workflow/config.mjs";

const config = loadConfig();
const TUNNEL_PNG_URL = "https://hunt-satisfactory-these-inspired.trycloudflare.com/report.png";

function loadJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; }
}

function getMetric(source, key) {
  return source?.[key]?.value ?? source?.values?.[key] ?? null;
}

function pct(value) {
  if (value == null || value === "") return "--";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${(n * 100).toFixed(2)}%`;
}

function pt(value) {
  if (value == null || value === "") return "--";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n > 0 ? "+" : ""}${n.toFixed(2)}pt`;
}

function num(value, digits = 0) {
  if (value == null || value === "") return "--";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
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

const adb = loadJson(config.paths.adb_data);
const web = loadJson(config.paths.web_data);
if (!adb || !web) { console.error("Missing data"); process.exit(1); }

const amount = getMetric(adb, "transaction_amount");
const amountDay = getMetric(adb, "transaction_amount_day");
const amountWeek = getMetric(adb, "transaction_amount_week");
const orders = getMetric(adb, "effective_orders");
const ordersDay = getMetric(adb, "effective_orders_day");
const ordersWeek = getMetric(adb, "effective_orders_week");
const alertConfig = config.presentation?.alerts || {};
const avgPredictedT = getMetric(web, "avg_predicted_t");
const deliveryRate = getMetric(web, "delivery_rate");
const ontimeRate = getMetric(web, "ontime_rate");
const avgPredictedTAlert = typeof avgPredictedT === "number" && avgPredictedT > (alertConfig.avg_predicted_t_gt ?? 30);
const deliveryRateAlert = typeof deliveryRate === "number" && deliveryRate < (alertConfig.delivery_rate_lt ?? 0.98);
const ontimeRateAlert = typeof ontimeRate === "number" && ontimeRate < (alertConfig.ontime_rate_lt ?? 0.9);

const payload = {
  msgtype: "markdown",
  markdown: {
    title: config.dingtalk.message_title || "香河实时播报",
    text: [
      `![香河实时播报](${TUNNEL_PNG_URL})`,
    ].join("\n"),
  },
};

const webhookUrl = config.dingtalk.webhook_url;
const secret = config.dingtalk.webhook_secret;
const timestamp = Date.now();
const sign = crypto.createHmac("sha256", secret).update(`${timestamp}\n${secret}`).digest("base64");

const response = await fetch(`${webhookUrl}&timestamp=${timestamp}&sign=${encodeURIComponent(sign)}`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});

const result = await response.json();
console.log(JSON.stringify({ status: result, png_url: TUNNEL_PNG_URL }, null, 2));
