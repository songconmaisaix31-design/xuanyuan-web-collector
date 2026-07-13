import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { loadConfig, normalizePath } from "./config.mjs";

const config = loadConfig();
const args = new Set(process.argv.slice(2));
const summary = {
  status: "running",
  started_at: new Date().toISOString(),
  options: {
    skip_web: args.has("--skip-web"),
    skip_adb: args.has("--skip-adb"),
    skip_export: args.has("--skip-export"),
    send_dingtalk: args.has("--no-send-dingtalk")
      ? false
      : (!args.has("--validate-only") && !args.has("--skip-export") && (args.has("--send-dingtalk") || config.dingtalk.enabled_by_default)),
    no_send_dingtalk: args.has("--no-send-dingtalk"),
    validate_only: args.has("--validate-only"),
    archive: !args.has("--no-archive"),
  },
  steps: [],
  outputs: {},
};

const nodeBin = process.execPath;
const pythonBin = process.env.PYTHON || "python";

function runStep(name, command, commandArgs, options = {}) {
  console.log(`\n== ${name} ==`);
  const started = Date.now();
  const result = spawnSync(command, commandArgs, {
    cwd: config.paths.root,
    encoding: "utf8",
    shell: false,
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stdout = result.stdout || "";
  const stderr = result.stderr || "";
  if (stdout) process.stdout.write(stdout);
  if (stderr) process.stderr.write(stderr);

  const step = {
    name,
    command: [command, ...commandArgs].join(" "),
    status: result.status === 0 ? "success" : "failed",
    exit_code: result.status,
    duration_seconds: Number(((Date.now() - started) / 1000).toFixed(2)),
  };
  if (options.captureOutput) {
    step.stdout_tail = stdout.slice(-4000);
    step.stderr_tail = stderr.slice(-4000);
  }
  summary.steps.push(step);

  if (result.status !== 0 && !options.allowFailure) {
    summary.status = "failed";
    writeSummary();
    process.exit(result.status || 1);
  }
  return { stdout, stderr, status: result.status };
}

function writeSummary() {
  summary.finished_at = new Date().toISOString();
  fs.mkdirSync(path.dirname(config.paths.workflow_summary), { recursive: true });
  fs.writeFileSync(config.paths.workflow_summary, JSON.stringify(summary, null, 2) + "\n", "utf8");
}

function parseOutputPath(stdout, key) {
  const line = stdout.split(/\r?\n/).find((item) => item.startsWith(`${key}=`));
  return line ? line.slice(key.length + 1).trim() : null;
}

function readQualityReport() {
  try {
    return JSON.parse(fs.readFileSync(config.paths.quality_report, "utf8"));
  } catch {
    return null;
  }
}

function archiveRun() {
  if (!summary.options.archive) return;
  const result = runStep("archive_run", nodeBin, ["workflow/archive_run.mjs"], { captureOutput: true, allowFailure: true });
  const match = result.stdout.match(/\{[\s\S]*\}/);
  if (match) {
    try {
      const payload = JSON.parse(match[0]);
      summary.outputs.archive_dir = normalizePath(payload.archive_dir);
      summary.outputs.archive_manifest = normalizePath(payload.manifest);
    } catch {
      // Keep the archive step output in summary; parsing is best-effort.
    }
  }
}

try {
  if (!summary.options.validate_only && !summary.options.skip_web) {
    runStep("collect_web_logistics", pythonBin, ["collect_xlsx_web_data.py"]);
  }

  if (!summary.options.validate_only && !summary.options.skip_adb) {
    runStep("collect_adb_trade_marketing", pythonBin, ["collect_device.py"]);
  }

  const validationResult = runStep("validate_input_data", nodeBin, ["workflow/validate_data.mjs"], { allowFailure: true });
  summary.outputs.quality_report = normalizePath(config.paths.quality_report);
  const firstQuality = readQualityReport();
  summary.quality_status = firstQuality?.status || "unknown";
  if (validationResult.status !== 0) {
    summary.status = "failed";
    summary.failure_reason = "input_data_validation_failed";
    writeSummary();
    archiveRun();
    writeSummary();
    process.exit(validationResult.status || 1);
  }

  // 历史对比（校验通过后执行）
  const compareResult = runStep("compare_history", nodeBin, ["workflow/compare_history.mjs"], { allowFailure: true, captureOutput: true });
  summary.outputs.anomaly_report = normalizePath(path.join(config.paths.root, "output", "anomaly_report.json"));
  summary.compare_status = compareResult.status === 0 ? "passed" : (compareResult.status === 2 ? "critical" : (compareResult.status === 1 ? "warning" : "skipped"));
  summary.compare_exit_code = compareResult.status;

  if (!summary.options.validate_only && !summary.options.skip_export) {
    const exportResult = runStep("render_report_png", pythonBin, ["render_report_png.py"], { captureOutput: true });
    const workbook = parseOutputPath(exportResult.stdout, "OUTPUT");
    const preview = parseOutputPath(exportResult.stdout, "PREVIEW");
    if (workbook) summary.outputs.workbook = normalizePath(workbook);
    if (preview) summary.outputs.preview = normalizePath(preview);
  }

  runStep("post_export_review", nodeBin, ["workflow/validate_data.mjs", "--soft"]);
  const finalQuality = readQualityReport();
  summary.quality_status = finalQuality?.status || summary.quality_status;

  const qualityPassed = summary.quality_status === (config.dingtalk.require_quality_status || "passed");

  if (summary.options.send_dingtalk && qualityPassed) {
    const sendResult = runStep("send_dingtalk_message", nodeBin, ["send_dingtalk_report.mjs"], { captureOutput: true });
    const match = sendResult.stdout.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        const payload = JSON.parse(match[0]);
        if (payload.png_url) summary.outputs.dingtalk_png_url = payload.png_url;
        if (payload.r2_key) summary.outputs.r2_key = payload.r2_key;
      } catch {
        // Keep the captured step output for manual inspection.
      }
    }
  } else if (summary.options.send_dingtalk) {
    summary.steps.push({
      name: "send_dingtalk_message",
      status: "skipped",
      reason: `blocked_by_quality_gate: quality_status=${summary.quality_status}`,
      exit_code: null,
      duration_seconds: 0,
    });
  } else {
    summary.steps.push({
      name: "send_dingtalk_message",
      status: "skipped",
      reason: "disabled by --no-send-dingtalk, --validate-only, --skip-export, or config",
      exit_code: null,
      duration_seconds: 0,
    });
  }

  summary.status = "success";
  writeSummary();
  archiveRun();
  writeSummary();
  console.log(`\nWORKFLOW_SUMMARY=${normalizePath(config.paths.workflow_summary)}`);
  console.log(`ANOMALY_REPORT=${normalizePath(path.join(config.paths.root, "output", "anomaly_report.json"))}`);
  console.log(`COMPARE_STATUS=${summary.compare_status || "skipped"}`);
  if (summary.outputs.workbook) console.log(`OUTPUT=${summary.outputs.workbook}`);
  if (summary.outputs.preview) console.log(`PREVIEW=${summary.outputs.preview}`);
} catch (error) {
  summary.status = "failed";
  summary.error = error.stack || error.message;
  writeSummary();
  throw error;
}
