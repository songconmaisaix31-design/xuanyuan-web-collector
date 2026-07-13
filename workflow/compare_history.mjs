/**
 * 香河实时播报 · 历史对比模块
 *
 * 读取最近 2 次运行记录，与当前数据对比，检测异常变化。
 * 输出 output/anomaly_report.json，包含异常详情和整体状态。
 *
 * Usage:
 *   node workflow/compare_history.mjs
 *   node workflow/compare_history.mjs --strict   # 更严格的阈值
 */

import fs from "node:fs";
import path from "node:path";
import { loadConfig, normalizePath } from "./config.mjs";

const config = loadConfig();
const args = new Set(process.argv.slice(2));
const strictMode = args.has("--strict");

// ── 对比阈值（可从 config.json 覆盖） ──────────────────
const thresholds = {
  jump_ratio: strictMode ? 0.50 : (config.compare?.jump_ratio ?? 1.0),        // 关键指标环比跳变阈值（100% 才触发警告）
  rate_drop_pt: strictMode ? 0.05 : (config.compare?.rate_drop_pt ?? 0.10),    // 率类指标下降百分点阈值
  avg_t_jump_ratio: strictMode ? 0.30 : (config.compare?.avg_t_jump_ratio ?? 0.50),
  subsidy_jump_pt: strictMode ? 3.0 : (config.compare?.subsidy_jump_pt ?? 5.0), // 补贴跳变百分点
};

// ── 关注的关键指标列表 ────────────────────────────────
const KEY_METRICS = [
  { key: "adb_transaction_amount", legacyKey: "transaction_amount", label: "交易额",              type: "amount", absKey: true },
  { key: "adb_effective_orders",   legacyKey: "effective_orders",   label: "有效订单",            type: "count",  absKey: true },
  { key: "adb_agent_subsidy",      legacyKey: "agent_subsidy",      label: "代理商补贴",          type: "rate",   unit: "pt" },
  { key: "adb_merchant_subsidy",   legacyKey: "merchant_subsidy",   label: "商户补贴",            type: "rate",   unit: "pt" },
  { key: "adb_platform_subsidy",   legacyKey: "platform_subsidy",   label: "平台补贴",            type: "rate",   unit: "pt" },
  { key: "web_city_capacity_attendance",     legacyKeys: ["web_attendance", "attendance"], label: "出勤骑手数", type: "count" },
  { key: "web_city_capacity_working_riders", legacyKeys: ["web_working_riders", "working_riders"], label: "开工骑手数", type: "count" },
  { key: "web_rider_load",                   legacyKeys: ["web_big_board_rider_load", "web_city_capacity_rider_load", "rider_load"], label: "骑手负载", type: "number" },
  { key: "web_big_board_avg_predicted_t",    legacyKeys: ["web_avg_predicted_t", "avg_predicted_t"], label: "平均预测T", type: "time" },
  { key: "web_big_board_delivery_rate",      legacyKeys: ["web_delivery_rate", "delivery_rate"], label: "妥投率", type: "rate", unit: "pt" },
  { key: "web_big_board_ontime_rate",        legacyKeys: ["web_ontime_rate", "ontime_rate"], label: "准时率", type: "rate", unit: "pt" },
];

// ── 工具函数 ───────────────────────────────────────────
function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function pct(value) {
  if (value == null) return "--";
  return `${(value * 100).toFixed(2)}%`;
}

function pctPt(value) {
  if (value == null) return "--";
  return `${value > 0 ? "+" : ""}${(value * 100).toFixed(2)}pt`;
}

// ── 加载历史 ───────────────────────────────────────────
function loadHistoricalRuns(limit = 2) {
  const runsPath = path.join(config.paths.history_dir, "runs.jsonl");
  if (!fs.existsSync(runsPath)) return [];

  const lines = fs.readFileSync(runsPath, "utf8").trim().split("\n").filter(Boolean);
  const entries = lines.map((line) => {
    try { return JSON.parse(line); } catch { return null; }
  }).filter(Boolean);

  // 取最近的 limit 条
  const recent = entries.slice(-limit);
  const results = [];
  for (const entry of recent) {
    const manifestPath = path.join(config.paths.history_dir, entry.run_id, "manifest.json");
    const manifest = readJson(manifestPath);
    if (manifest) {
      results.push({
        runId: entry.run_id,
        archivedAt: entry.archived_at,
        status: entry.status,
        qualityStatus: entry.quality_status,
        metrics: manifest.metrics || {},
        issues: manifest.issues || [],
        warnings: manifest.warnings || [],
        updatedAt: entry.updated_at,
      });
    }
  }
  return results;
}

// ── 当前数据 ───────────────────────────────────────────
function loadCurrentMetrics() {
  const quality = readJson(config.paths.quality_report);
  if (!quality || !quality.metrics) return null;
  return {
    metrics: quality.metrics,
    issues: quality.issues || [],
    warnings: quality.warnings || [],
    status: quality.status,
    updatedAt: quality.sources?.web?.updated_at || quality.sources?.adb?.collected_at || "",
  };
}

// ── 对比逻辑 ───────────────────────────────────────────
function compareMetric(current, previous, spec) {
  if (current == null || previous == null) return null;

  const delta = current - previous;
  const absCurrent = Math.abs(current);
  const absPrevious = Math.abs(previous);

  let ratio = 0;
  if (absPrevious > 0.0001) {
    ratio = Math.abs(delta / absPrevious);
  }

  const result = {
    key: spec.key,
    label: spec.label,
    current,
    previous,
    delta,
    ratio,
    type: spec.type,
  };

  // 判断异常等级
  if (spec.type === "rate" && spec.unit === "pt") {
    // 率类（已为小数），转换为百分点比较
    const deltaPt = Math.abs(delta * 100);
    if (deltaPt >= thresholds.subsidy_jump_pt * 1.5) {
      result.severity = "critical";
      result.reason = `${spec.label} 环比跳变 ${deltaPt.toFixed(1)}pt`;
    } else if (deltaPt >= thresholds.subsidy_jump_pt) {
      result.severity = "warning";
      result.reason = `${spec.label} 环比变化 ${deltaPt.toFixed(1)}pt`;
    } else {
      result.severity = "ok";
    }
  } else if (spec.type === "time") {
    if (ratio >= thresholds.avg_t_jump_ratio * 1.5) {
      result.severity = "critical";
      result.reason = `${spec.label} 环比跳变 ${pct(ratio)}（${delta > 0 ? "+" : ""}${delta.toFixed(2)}）`;
    } else if (ratio >= thresholds.avg_t_jump_ratio) {
      result.severity = "warning";
      result.reason = `${spec.label} 环比变化 ${pct(ratio)}（${delta > 0 ? "+" : ""}${delta.toFixed(2)}）`;
    } else {
      result.severity = "ok";
    }
  } else {
    if (ratio >= thresholds.jump_ratio * 1.5) {
      result.severity = "critical";
      result.reason = `${spec.label} 环比跳变 ${pct(ratio)}（${delta > 0 ? "+" : ""}${delta.toFixed(2)}）`;
    } else if (ratio >= thresholds.jump_ratio) {
      result.severity = "warning";
      result.reason = `${spec.label} 环比变化 ${pct(ratio)}（${delta > 0 ? "+" : ""}${delta.toFixed(2)}）`;
    } else {
      result.severity = "ok";
    }
  }

  // 特殊规则：妥投率/准时率下降额外告警
  if ((spec.key === "web_big_board_delivery_rate" || spec.key === "web_big_board_ontime_rate") && delta < -0.03) {
    const dropPt = Math.abs(delta * 100);
    if (dropPt >= 5) {
      result.severity = "critical";
      result.reason = `${spec.label} 骤降 ${dropPt.toFixed(1)}pt（${pct(previous)} → ${pct(current)}）`;
    } else if (dropPt >= 3) {
      if (result.severity === "ok") result.severity = "warning";
      result.reason = `${spec.label} 下降 ${dropPt.toFixed(1)}pt（${pct(previous)} → ${pct(current)}）`;
    }
  }

  // 平均预测T 上升特殊告警
  if (spec.key === "web_big_board_avg_predicted_t" && delta > 10) {
    result.severity = "critical";
    result.reason = `${spec.label} 骤升 ${delta.toFixed(1)}min（${previous.toFixed(1)} → ${current.toFixed(1)}）`;
  }

  return result;
}

// ── 比较质量状态 ───────────────────────────────────────
function compareQuality(current, previousRun) {
  const findings = [];

  // 新出现的问题
  const prevIssueSet = new Set(previousRun.issues || []);
  const newIssues = (current.issues || []).filter((i) => !prevIssueSet.has(i));
  if (newIssues.length) {
    findings.push({
      severity: "critical",
      type: "new_issues",
      reason: `${newIssues.length} 个新问题：${newIssues.join("；")}`,
      detail: newIssues,
    });
  }

  // 新出现的警告
  const prevWarnSet = new Set(previousRun.warnings || []);
  const newWarnings = (current.warnings || []).filter((w) => !prevWarnSet.has(w));
  if (newWarnings.length) {
    findings.push({
      severity: "warning",
      type: "new_warnings",
      reason: `${newWarnings.length} 个新警告：${newWarnings.join("；")}`,
      detail: newWarnings,
    });
  }

  // 质量状态降级
  if (previousRun.qualityStatus === "passed" && current.status !== "passed") {
    findings.push({
      severity: "critical",
      type: "quality_degraded",
      reason: `数据质量从 passed 降级为 ${current.status}`,
    });
  }

  return findings;
}

function metricValue(metrics, spec) {
  if (!metrics) return undefined;
  if (metrics[spec.key] !== undefined) return metrics[spec.key];
  for (const key of spec.legacyKeys || []) {
    if (metrics[key] !== undefined) return metrics[key];
  }
  return metrics[spec.legacyKey];
}

// ── 主函数 ────────────────────────────────────────────
function main() {
  const current = loadCurrentMetrics();
  if (!current) {
    const report = {
      status: "skipped",
      reason: "no_current_quality_data",
      checkedAt: new Date().toISOString(),
      comparisons: [],
      findings: [],
    };
    writeReport(report);
    console.log(JSON.stringify(report, null, 2));
    return;
  }

  const historicalRuns = loadHistoricalRuns(2);

  if (historicalRuns.length === 0) {
    const report = {
      status: "skipped",
      reason: "no_historical_data",
      checkedAt: new Date().toISOString(),
      comparisons: [],
      findings: [],
    };
    writeReport(report);
    console.log(JSON.stringify(report, null, 2));
    return;
  }

  const latestRun = historicalRuns[historicalRuns.length - 1];
  const comparisons = [];
  const findings = [];

  // 指标对比（只与最近一次对比）
  for (const spec of KEY_METRICS) {
    const currentVal = metricValue(current.metrics, spec);
    const previousVal = metricValue(latestRun.metrics, spec);
    const result = compareMetric(currentVal, previousVal, spec);
    if (result) {
      comparisons.push(result);
      if (result.severity !== "ok") {
        findings.push(result);
      }
    }
  }

  // 质量变化检测
  const qualityFindings = compareQuality(current, latestRun);
  findings.push(...qualityFindings);

  // 确定整体状态
  let overallStatus = "passed";
  if (findings.some((f) => f.severity === "critical")) {
    overallStatus = "critical";
  } else if (findings.some((f) => f.severity === "warning")) {
    overallStatus = "warning";
  }

  const report = {
    status: overallStatus,
    checkedAt: new Date().toISOString(),
    currentRun: {
      updatedAt: current.updatedAt,
      qualityStatus: current.status,
      issues: current.issues,
      warnings: current.warnings,
    },
    comparedWith: {
      runId: latestRun.runId,
      archivedAt: latestRun.archivedAt,
      qualityStatus: latestRun.qualityStatus,
    },
    availableHistory: historicalRuns.length,
    thresholds,
    comparisons,
    findings,
    summary: buildSummary(findings, comparisons, historicalRuns.length),
  };

  writeReport(report);
  console.log(JSON.stringify(report, null, 2));

  if (overallStatus === "critical") {
    process.exit(2);
  } else if (overallStatus === "warning") {
    process.exit(1);
  }
}

function writeReport(report) {
  const outputPath = config.paths.root
    ? path.join(config.paths.root, "output", "anomaly_report.json")
    : "output/anomaly_report.json";
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, JSON.stringify(report, null, 2) + "\n", "utf8");
}

function buildSummary(findings, comparisons, historyCount) {
  if (historyCount === 0) return "无历史数据，跳过对比";

  const criticals = findings.filter((f) => f.severity === "critical");
  const warnings = findings.filter((f) => f.severity === "warning");

  const lines = [];
  lines.push(`与最近 1 次记录对比（共 ${historyCount} 条可用历史）`);

  const changedMetrics = comparisons.filter((c) => c.severity !== "ok");
  lines.push(`${comparisons.length} 项指标已对比，${changedMetrics.length} 项有变化`);

  if (criticals.length) {
    lines.push(`⚠️ ${criticals.length} 项严重异常：`);
    for (const c of criticals) lines.push(`  - ${c.reason}`);
  }
  if (warnings.length) {
    lines.push(`⚡ ${warnings.length} 项警告：`);
    for (const w of warnings) lines.push(`  - ${w.reason}`);
  }
  if (!criticals.length && !warnings.length) {
    lines.push("✅ 无异常");
  }

  return lines.join("\n");
}

main();
