import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { loadConfig, normalizePath, timestampForFilename } from "./config.mjs";

const config = loadConfig();

function parseEnvFile(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return {};
  const values = {};
  for (const rawLine of fs.readFileSync(filePath, "utf8").split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

function loadLatestReportPath() {
  const latestReport = path.join(config.paths.root, "output", "latest_report.json");
  if (fs.existsSync(latestReport)) {
    const payload = JSON.parse(fs.readFileSync(latestReport, "utf8"));
    if (payload.latest_preview && fs.existsSync(payload.latest_preview)) return payload.latest_preview;
    if (payload.preview && fs.existsSync(payload.preview)) return payload.preview;
  }
  return path.join(config.paths.output_dir, "filled-preview.png");
}

function curlCheck(url) {
  return new Promise((resolve, reject) => {
    const curl = spawn("curl.exe", [
      "--location",
      "--silent",
      "--show-error",
      "--max-time",
      "20",
      "--noproxy",
      "*",
      "--output",
      "NUL",
      "--write-out",
      "%{http_code}\n%{content_type}\n%{size_download}",
      url,
    ], {
      env: {
        ...process.env,
        HTTP_PROXY: "",
        HTTPS_PROXY: "",
        http_proxy: "",
        https_proxy: "",
        NO_PROXY: "*",
      },
      shell: false,
    });

    let stdout = "";
    let stderr = "";
    curl.stdout.on("data", (chunk) => { stdout += chunk; });
    curl.stderr.on("data", (chunk) => { stderr += chunk; });
    curl.on("error", reject);
    curl.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(`curl url check failed: ${stderr || stdout || `exit ${code}`}`));
        return;
      }
      const [statusLine, contentTypeLine, sizeLine] = stdout.trim().split(/\r?\n/);
      resolve({
        status: Number(statusLine),
        content_type: contentTypeLine || "",
        size_download: Number(sizeLine || 0),
      });
    });
  });
}

export async function assertPublicImageUrlAvailable(url) {
  const check = await curlCheck(url);
  if (
    check.status < 200
    || check.status >= 300
    || !check.content_type.toLowerCase().includes("image/")
    || !Number.isFinite(check.size_download)
    || check.size_download <= 0
  ) {
    throw new Error(`Vercel Blob URL is not a reachable image: ${JSON.stringify(check)}`);
  }
  return check;
}

export async function uploadVercelBlob(filePath = loadLatestReportPath()) {
  const blobConfig = config.vercel_blob || {};
  const envValues = parseEnvFile(blobConfig.env_file);
  const uploadServerUrl = (
    process.env.UPLOAD_SERVER_URL
    || envValues.UPLOAD_SERVER_URL
    || blobConfig.upload_server_url
    || ""
  ).replace(/\/+$/, "");
  const tokenEnvName = blobConfig.upload_token_env || "UPLOAD_TOKEN";
  const uploadToken = process.env[tokenEnvName] || envValues[tokenEnvName] || "";

  if (!uploadServerUrl) {
    throw new Error("Vercel Blob upload server URL is missing");
  }
  if (!uploadToken) {
    throw new Error(`Vercel Blob upload token is missing: ${tokenEnvName}`);
  }
  if (!fs.existsSync(filePath)) {
    throw new Error(`PNG not found for Vercel Blob upload: ${filePath}`);
  }

  const body = fs.readFileSync(filePath);
  const uploadName = `xianghe-report-${timestampForFilename(new Date())}.png`;
  const form = new FormData();
  form.append("file", new Blob([body], { type: "image/png" }), uploadName);

  const response = await fetch(`${uploadServerUrl}/api/upload`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${uploadToken}`,
    },
    body: form,
  });
  const payload = await response.json().catch(async () => ({ error: await response.text() }));
  if (!response.ok || payload.ok !== true || !payload.url) {
    throw new Error(`Vercel Blob upload failed: HTTP ${response.status} ${JSON.stringify(payload).slice(0, 500)}`);
  }

  const urlChecks = await assertPublicImageUrlAvailable(payload.url);
  const result = {
    status: "uploaded",
    provider: "vercel_blob",
    source: normalizePath(filePath),
    url: payload.url,
    pathname: payload.pathname || null,
    content_type: payload.contentType || "image/png",
    url_checks: urlChecks,
    uploaded_at: new Date().toISOString(),
  };
  const out = path.join(config.paths.root, "output", "vercel_blob_upload.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n", "utf8");
  return result;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  uploadVercelBlob(process.argv[2]).then((result) => {
    console.log(JSON.stringify(result, null, 2));
  }).catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
