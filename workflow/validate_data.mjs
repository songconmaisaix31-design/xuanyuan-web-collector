import fs from "node:fs";
import path from "node:path";
import { loadConfig, normalizePath } from "./config.mjs";

const config = loadConfig();
const args = new Set(process.argv.slice(2));
const soft = args.has("--soft");

function readJson(file, label) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (error) {
    return { __readError: `${label} read failed: ${error.message}` };
  }
}

function metric(statusPath, valuePath, source, name, options = {}) {
  const status = get(source, statusPath);
  const value = get(source, valuePath);
  const sourceName = options.sourceName || (source === adb ? "adb" : source === web ? "web" : "");
  return {
    name: sourceName ? `${sourceName}_${name}` : name,
    legacyName: name,
    sourceName,
    status,
    value,
    required: options.required !== false,
    range: options.range,
    kind: options.kind || "number",
  };
}

function get(obj, pathExpr) {
  return pathExpr.split(".").reduce((cur, key) => cur == null ? undefined : cur[key], obj);
}

function inRange(value, range) {
  if (!Array.isArray(range) || typeof value !== "number") return true;
  return value >= range[0] && value <= range[1];
}

function parseLocalTime(text) {
  const match = String(text || "").match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})$/);
  if (!match) return null;
  const [, y, m, d, hh, mm, ss] = match.map(Number);
  return new Date(y, m - 1, d, hh, mm, ss);
}

const web = readJson(config.paths.web_data, "web data");
const adb = readJson(config.paths.adb_data, "adb data");
const checks = config.checks || {};
const ranges = checks.ranges || {};
const issues = [];
const warnings = [];

if (web.__readError) issues.push(web.__readError);
if (adb.__readError) issues.push(adb.__readError);

if (!web.__readError && web.status !== "success") {
  issues.push(`web status is ${web.status || "missing"}, expected success`);
}
if (!adb.__readError && !["success", "partial_success"].includes(adb.status)) {
  issues.push(`adb status is ${adb.status || "missing"}, expected success or partial_success`);
}
if (!web.__readError && web.source_namespace !== "web") {
  issues.push(`web source_namespace is ${web.source_namespace || "missing"}, expected web`);
}
if (!adb.__readError && adb.source_namespace !== "adb") {
  issues.push(`adb source_namespace is ${adb.source_namespace || "missing"}, expected adb`);
}

function expectFieldSource(source, fieldName, expectedPrefix, options = {}) {
  const tag = source.field_sources?.[fieldName];
  if (!tag) {
    if (options.required !== false) issues.push(`${expectedPrefix}_${fieldName} source tag missing`);
    return;
  }
  if (!String(tag).startsWith(`${expectedPrefix}.`)) {
    issues.push(`${expectedPrefix}_${fieldName} source tag ${tag} does not start with ${expectedPrefix}.`);
  }
}

const adbFieldNames = [
  "transaction_amount",
  "transaction_amount_day",
  "transaction_amount_week",
  "effective_orders",
  "effective_orders_day",
  "effective_orders_week",
  "agent_subsidy",
  "agent_subsidy_day",
  "agent_subsidy_week",
  "merchant_subsidy",
  "merchant_subsidy_day",
  "merchant_subsidy_week",
  "platform_subsidy",
  "platform_subsidy_day",
  "platform_subsidy_week",
];
const webBigBoardFieldNames = [
  "avg_predicted_t",
  "avg_predicted_t_day",
  "avg_predicted_t_week",
  "delivery_rate",
  "delivery_rate_day",
  "delivery_rate_week",
  "ontime_rate",
  "ontime_rate_day",
  "ontime_rate_week",
];
const riderLoadFieldNames = [
  "rider_load",
  "rider_load_day",
  "rider_load_week",
];
const webCityCapacityFieldNames = [
  "attendance",
  "attendance_day",
  "attendance_week",
  "working_riders",
  "working_riders_day",
  "working_riders_week",
];

if (!adb.__readError) {
  for (const name of adbFieldNames) expectFieldSource(adb, name, "adb");
}
if (!web.__readError) {
  for (const name of webBigBoardFieldNames) {
    expectFieldSource(web, name, "web.big_board", { required: !name.endsWith("_day") && !name.endsWith("_week") });
  }
  for (const name of webCityCapacityFieldNames) {
    expectFieldSource(web, name, "web.city_capacity", { required: !name.endsWith("_day") && !name.endsWith("_week") });
  }
  for (const name of riderLoadFieldNames) {
    expectWebRiderLoadSource(web, name, { required: !name.endsWith("_day") && !name.endsWith("_week") });
  }
  validateCapacityDetailRows();
}

const updatedAt = parseLocalTime(web.updated_at);
if (!updatedAt) {
  issues.push("web updated_at is missing or not yyyy-mm-dd HH:mm:ss");
} else {
  const ageMinutes = (Date.now() - updatedAt.getTime()) / 60000;
  if (ageMinutes > checks.max_data_age_minutes) {
    warnings.push(`web data is ${ageMinutes.toFixed(1)} minutes old`);
  }
}

const rateRange = ranges.rate;
const deltaRange = ranges.delta_rate;
const ptRange = ranges.subsidy_pt;
const amount = adb.transaction_amount?.value;
const orders = adb.effective_orders?.value;
const transactionTarget = config.excel?.transaction_target;
const metrics = [
  metric("transaction_amount.status", "transaction_amount.value", adb, "transaction_amount", { range: ranges.transaction_amount }),
  metric("transaction_amount_day.status", "transaction_amount_day.value", adb, "transaction_amount_day", { range: deltaRange }),
  metric("transaction_amount_week.status", "transaction_amount_week.value", adb, "transaction_amount_week", { range: deltaRange }),
  { name: "transaction_target", value: config.excel?.transaction_target, status: config.excel?.transaction_target == null ? "invalid" : "success", range: ranges.transaction_amount },
  {
    name: "transaction_completion",
    value: typeof amount === "number" && typeof transactionTarget === "number" && transactionTarget > 0 ? amount / transactionTarget : null,
    status: typeof amount === "number" && typeof transactionTarget === "number" && transactionTarget > 0 ? "success" : "invalid",
    range: rateRange,
  },
  metric("effective_orders.status", "effective_orders.value", adb, "effective_orders", { range: ranges.effective_orders }),
  metric("effective_orders_day.status", "effective_orders_day.value", adb, "effective_orders_day", { range: deltaRange }),
  metric("effective_orders_week.status", "effective_orders_week.value", adb, "effective_orders_week", { range: deltaRange }),
  metric("subsidies.agent_subsidy.value.status", "subsidies.agent_subsidy.value.value", adb, "agent_subsidy", { range: rateRange }),
  metric("subsidies.agent_subsidy.day.status", "subsidies.agent_subsidy.day.value", adb, "agent_subsidy_day", { range: ptRange }),
  metric("subsidies.agent_subsidy.week.status", "subsidies.agent_subsidy.week.value", adb, "agent_subsidy_week", { range: ptRange }),
  metric("subsidies.merchant_subsidy.value.status", "subsidies.merchant_subsidy.value.value", adb, "merchant_subsidy", { range: rateRange }),
  metric("subsidies.merchant_subsidy.day.status", "subsidies.merchant_subsidy.day.value", adb, "merchant_subsidy_day", { range: ptRange }),
  metric("subsidies.merchant_subsidy.week.status", "subsidies.merchant_subsidy.week.value", adb, "merchant_subsidy_week", { range: ptRange }),
  metric("subsidies.platform_subsidy.value.status", "subsidies.platform_subsidy.value.value", adb, "platform_subsidy", { range: rateRange }),
  metric("subsidies.platform_subsidy.day.status", "subsidies.platform_subsidy.day.value", adb, "platform_subsidy_day", { range: ptRange }),
  metric("subsidies.platform_subsidy.week.status", "subsidies.platform_subsidy.week.value", adb, "platform_subsidy_week", { range: ptRange }),
  webValueMetric("attendance", ranges.attendance, { sourcePrefix: "web_city_capacity" }),
  webValueMetric("attendance_day", deltaRange, { sourcePrefix: "web_city_capacity", required: false }),
  webValueMetric("attendance_week", deltaRange, { sourcePrefix: "web_city_capacity", required: false }),
  webValueMetric("working_riders", ranges.attendance, { sourcePrefix: "web_city_capacity" }),
  webValueMetric("working_riders_day", deltaRange, { sourcePrefix: "web_city_capacity", required: false }),
  webValueMetric("working_riders_week", deltaRange, { sourcePrefix: "web_city_capacity", required: false }),
  capacityMetric("dedicated", "attendance", "dedicated_attendance", ranges.attendance),
  capacityMetric("dedicated", "working_riders", "dedicated_working_riders", ranges.attendance),
  capacityMetric("preferred", "attendance", "preferred_attendance", ranges.attendance),
  capacityMetric("preferred", "working_riders", "preferred_working_riders", ranges.attendance),
  webValueMetric("rider_load", ranges.rider_load, { sourcePrefix: webRiderLoadSourcePrefix("rider_load") }),
  webValueMetric("rider_load_day", deltaRange, { sourcePrefix: webRiderLoadSourcePrefix("rider_load_day"), required: false }),
  webValueMetric("rider_load_week", deltaRange, { sourcePrefix: webRiderLoadSourcePrefix("rider_load_week"), required: false }),
  webValueMetric("avg_predicted_t", ranges.avg_t, { sourcePrefix: "web_big_board" }),
  webValueMetric("avg_predicted_t_day", deltaRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("avg_predicted_t_week", deltaRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("delivery_rate", rateRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("delivery_rate_day", deltaRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("delivery_rate_week", deltaRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("ontime_rate", rateRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("ontime_rate_day", deltaRange, { sourcePrefix: "web_big_board" }),
  webValueMetric("ontime_rate_week", deltaRange, { sourcePrefix: "web_big_board" }),
];

function capacityMetric(row, metricName, name, range) {
  const value = web.capacity_rows?.[row]?.[metricName]?.value;
  const status = web.capacity_rows?.[row]?.[metricName]?.status;
  return { name: `web_city_capacity_${name}`, legacyName: name, sourceName: "web.city_capacity", value, status: status === "success" ? "success" : "invalid", range };
}

function webValueMetric(name, range, options = {}) {
  const sourcePrefix = options.sourcePrefix || "web";
  const prefixedName = `${sourcePrefix}_${name}`;
  const value = web.web_values?.[prefixedName] ?? web.values?.[name];
  return {
    name: prefixedName,
    legacyName: name,
    sourceName: sourcePrefix === "web_city_capacity" ? "web.city_capacity" : (sourcePrefix === "web_big_board" ? "web.big_board" : sourcePrefix),
    value,
    status: value == null ? "invalid" : "success",
    range,
    required: options.required !== false,
  };
}

function expectWebRiderLoadSource(source, fieldName, options = {}) {
  const tag = source.field_sources?.[fieldName];
  if (!tag) {
    if (options.required !== false) issues.push(`web_${fieldName} source tag missing`);
    return;
  }
  if (!String(tag).startsWith("web.big_board.") && !String(tag).startsWith("web.city_capacity.")) {
    issues.push(`web_${fieldName} source tag ${tag} is not web.big_board.* or web.city_capacity.*`);
  }
}

function webRiderLoadSourcePrefix(name) {
  const tag = web.field_sources?.[name] || "";
  return tag.startsWith("web.city_capacity.") ? "web_city_capacity" : "web_big_board";
}

function validateCapacityDetailRows() {
  const requiredMetrics = ["attendance", "working_riders", "delivery_rate", "ontime_rate"];
  const rows = Array.isArray(web.capacity_detail_rows) ? web.capacity_detail_rows : [];
  if (!rows.length) {
    issues.push("web.city_capacity capacity_detail_rows missing");
    return;
  }
  for (const row of rows) {
    const label = row.line || "unknown";
    if (label.includes("联盟")) continue;
    for (const metricName of requiredMetrics) {
      if (typeof row[metricName] !== "number" || !Number.isFinite(row[metricName])) {
        issues.push(`web.city_capacity ${label}.${metricName} missing or invalid`);
      }
    }
  }
}

for (const item of metrics) {
  if (item.status !== "success") {
    if (item.required !== false) {
      issues.push(`${item.name} missing or invalid`);
    }
    continue;
  }
  if (typeof item.value !== "number") {
    issues.push(`${item.name} is not numeric`);
    continue;
  }
  if (!inRange(item.value, item.range)) {
    warnings.push(`${item.name}=${item.value} outside expected range ${item.range?.join("~")}`);
  }
}

if (typeof amount === "number" && typeof orders === "number" && orders > 0) {
  const perOrder = amount / orders;
  const cross = checks.cross_checks || {};
  if (perOrder < cross.min_transaction_amount_per_order || perOrder > cross.max_transaction_amount_per_order) {
    warnings.push(`transaction amount per order ${perOrder.toFixed(2)} outside expected range`);
  }
}

const report = {
  status: issues.length ? "failed" : (warnings.length ? "warning" : "passed"),
  checked_at: new Date().toISOString(),
  sources: {
    web: {
      path: normalizePath(config.paths.web_data),
      status: web.status,
      updated_at: web.updated_at,
    },
    adb: {
      path: normalizePath(config.paths.adb_data),
      status: adb.status,
      collected_at: adb.collected_at,
      device: adb.device,
    },
  },
  metrics: Object.fromEntries(metrics.map((item) => [item.name, item.value ?? null])),
  issues,
  warnings,
};

fs.mkdirSync(path.dirname(config.paths.quality_report), { recursive: true });
fs.writeFileSync(config.paths.quality_report, JSON.stringify(report, null, 2) + "\n", "utf8");
console.log(JSON.stringify(report, null, 2));

if (issues.length && !soft) {
  process.exit(1);
}
