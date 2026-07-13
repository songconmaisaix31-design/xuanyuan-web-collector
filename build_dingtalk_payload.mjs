/**
 * Build DingTalk webhook JSON payload with Cloudflare Tunnel PNG URL.
 * Does NOT send the message - only prints the payload JSON.
 */
import crypto from "node:crypto";
import fs from "node:fs";
import { loadConfig } from "./workflow/config.mjs";

const config = loadConfig();
const TUNNEL_PNG_URL = "https://estates-rio-affordable-risks.trycloudflare.com/report.png";

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

const adb = loadJson(config.paths.adb_data);
const web = loadJson(config.paths.web_data);
if (!adb || !web) {
  console.error("Missing adb or web data json.");
  process.exit(1);
}

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
      "## 香河实时播报",
      "",
      `**数据更新** ${web.updated_at || adb.collected_at || "未知"}`,
      "",
      `![香河实时播报](${TUNNEL_PNG_URL})`,
      "",
      "### 交易结果",
      "| 指标 | 数值 | 日环比 | 周环比 |",
      "|---|---:|---:|---:|",
      row("交易额", num(amount, 2), amountDay, amountWeek),
      `| 交易额目标 | ${num(config.excel.transaction_target, 2)} | -- | -- |`,
      `| 交易额完成率 | **${pct(amount / config.excel.transaction_target)}** | -- | -- |`,
      row("有效订单", `${num(orders)} 单`, ordersDay, ordersWeek),
      `| 订单目标 | ${num(config.excel.order_target)} | -- | -- |`,
      `| 订单完成率 | **${pct(orders / config.excel.order_target)}** | -- | -- |`,
      "",
      "### 补贴监控",
      "| 指标 | 数值 | 日环比 | 周环比 |",
      "|---|---:|---:|---:|",
      row("代理商补贴", pct(subsidy(adb, "agent_subsidy", "value")), subsidy(adb, "agent_subsidy", "day"), subsidy(adb, "agent_subsidy", "week"), "pt"),
      row("商户补贴", pct(subsidy(adb, "merchant_subsidy", "value")), subsidy(adb, "merchant_subsidy", "day"), subsidy(adb, "merchant_subsidy", "week"), "pt"),
      row("平台补贴", pct(subsidy(adb, "platform_subsidy", "value")), subsidy(adb, "platform_subsidy", "day"), subsidy(adb, "platform_subsidy", "week"), "pt"),
      "",
      "### 物流",
      "| 指标 | 数值 | 日环比 | 周环比 |",
      "|---|---:|---:|---:|",
      row("出勤骑手数", `${num(getMetric(web, "attendance"))} 人`, getMetric(web, "attendance_day"), getMetric(web, "attendance_week")),
      row("开工骑手数", `${num(getMetric(web, "working_riders"))} 人`, getMetric(web, "working_riders_day"), getMetric(web, "working_riders_week")),
      row("骑手负载", num(getMetric(web, "rider_load"), 2), getMetric(web, "rider_load_day"), getMetric(web, "rider_load_week")),
      row("平均预测T", alertValue(num(avgPredictedT, 2), avgPredictedTAlert), getMetric(web, "avg_predicted_t_day"), getMetric(web, "avg_predicted_t_week")),
      row("妥投率", alertValue(pct(deliveryRate), deliveryRateAlert), getMetric(web, "delivery_rate_day"), getMetric(web, "delivery_rate_week")),
      row("准时率", alertValue(pct(ontimeRate), ontimeRateAlert), getMetric(web, "ontime_rate_day"), getMetric(web, "ontime_rate_week")),
      "",
      "---",
      `自动发送时间：${new Date().toLocaleString("zh-CN", { hour12: false })}`,
    ].filter((line) => line !== null).join("\n"),
  },
};

// Print signature info and the full payload
const timestamp = Date.now();
const sign = crypto.createHmac("sha256", config.dingtalk.webhook_secret)
  .update(`${timestamp}\n${config.dingtalk.webhook_secret}`)
  .digest("base64");

console.log("=== 钉钉 Webhook 请求信息 ===");
console.log(`POST ${config.dingtalk.webhook_url}&timestamp=${timestamp}&sign=${encodeURIComponent(sign)}`);
console.log("Content-Type: application/json");
console.log("");
console.log("=== 请求体 JSON ===");
console.log(JSON.stringify(payload, null, 2));

// Also write to a file
const outPath = "output/dingtalk_payload.json";
fs.mkdirSync("output", { recursive: true });
fs.writeFileSync(outPath, JSON.stringify({
  webhook_url: config.dingtalk.webhook_url,
  timestamp,
  signature: sign,
  payload,
}, null, 2) + "\n", "utf8");
console.log(`\n(完整信息已写入 ${outPath})`);
