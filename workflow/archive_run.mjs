import fs from "node:fs";
import path from "node:path";
import { loadConfig, normalizePath, timestampForFilename } from "./config.mjs";

const config = loadConfig();

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function copyIfExists(source, targetDir, name = null) {
  if (!source || !fs.existsSync(source)) return null;
  fs.mkdirSync(targetDir, { recursive: true });
  const target = path.join(targetDir, name || path.basename(source));
  fs.copyFileSync(source, target);
  return normalizePath(target);
}

function fromSummary(summary, key) {
  return summary?.outputs?.[key] || null;
}

const summary = readJson(config.paths.workflow_summary) || {};
const quality = readJson(config.paths.quality_report) || {};
const startedAt = summary.started_at ? new Date(summary.started_at) : new Date();
const runId = timestampForFilename(startedAt);
const archiveDir = path.join(config.paths.history_dir, runId);

const files = {};
files.web_data = copyIfExists(config.paths.web_data, archiveDir, "web_data.json");
files.adb_data = copyIfExists(config.paths.adb_data, archiveDir, "adb_data.json");
files.quality_report = copyIfExists(config.paths.quality_report, archiveDir, "quality_report.json");
files.workflow_summary = copyIfExists(config.paths.workflow_summary, archiveDir, "workflow_summary.json");
files.workbook = copyIfExists(fromSummary(summary, "workbook"), archiveDir);
files.preview = copyIfExists(fromSummary(summary, "preview"), archiveDir);

const rawDir = path.join(archiveDir, "raw");
for (const name of [
  "adb_trade.png",
  "adb_trade.xml",
  "adb_trade_text.json",
  "adb_marketing.png",
  "adb_marketing.xml",
  "adb_marketing_text.json",
]) {
  const copied = copyIfExists(path.join(config.paths.root, "output", name), rawDir, name);
  if (copied) files[`raw/${name}`] = copied;
}

const manifest = {
  run_id: runId,
  archived_at: new Date().toISOString(),
  status: summary.status || "unknown",
  quality_status: quality.status || "unknown",
  warnings: quality.warnings || [],
  issues: quality.issues || [],
  sources: quality.sources || {},
  metrics: quality.metrics || {},
  files,
};

fs.mkdirSync(archiveDir, { recursive: true });
const manifestPath = path.join(archiveDir, "manifest.json");
fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2) + "\n", "utf8");

fs.mkdirSync(config.paths.history_dir, { recursive: true });
fs.appendFileSync(
  path.join(config.paths.history_dir, "runs.jsonl"),
  JSON.stringify({
    run_id: runId,
    archived_at: manifest.archived_at,
    status: manifest.status,
    quality_status: manifest.quality_status,
    updated_at: manifest.sources.web?.updated_at || null,
    adb_collected_at: manifest.sources.adb?.collected_at || null,
    preview: files.preview || null,
    workbook: files.workbook || null,
    warning_count: manifest.warnings.length,
    issue_count: manifest.issues.length,
  }) + "\n",
  "utf8",
);

console.log(JSON.stringify({
  status: "archived",
  run_id: runId,
  archive_dir: normalizePath(archiveDir),
  manifest: normalizePath(manifestPath),
}, null, 2));
