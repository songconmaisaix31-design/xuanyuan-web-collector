import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const moduleDir = path.dirname(fileURLToPath(import.meta.url));
const fallbackRoot = path.resolve(moduleDir, "..");

export function loadConfig() {
  const configPath = path.join(fallbackRoot, "config.json");
  const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
  const root = normalizePath(config.paths?.root || fallbackRoot);
  config.paths = {
    ...config.paths,
    root,
    template_xlsx: normalizePath(config.paths.template_xlsx),
    output_dir: normalizePath(config.paths.output_dir),
    history_dir: normalizePath(config.paths.history_dir || path.join(root, "history")),
    web_data: normalizePath(config.paths.web_data),
    adb_data: normalizePath(config.paths.adb_data),
    quality_report: normalizePath(config.paths.quality_report),
    workflow_summary: normalizePath(config.paths.workflow_summary),
  };
  return config;
}

export function normalizePath(value) {
  return String(value).replace(/\\/g, "/");
}

export function timestampForFilename(date = new Date()) {
  return date.toISOString().replace(/[-:T]/g, "").slice(0, 12);
}

export function latestFile(dir, pattern) {
  if (!fs.existsSync(dir)) return null;
  return fs.readdirSync(dir)
    .filter((name) => pattern.test(name))
    .map((name) => {
      const full = path.join(dir, name);
      return { name, full: normalizePath(full), mtime: fs.statSync(full).mtimeMs };
    })
    .sort((a, b) => b.mtime - a.mtime)[0] || null;
}
