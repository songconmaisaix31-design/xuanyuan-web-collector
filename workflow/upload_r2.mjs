import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig, normalizePath, timestampForFilename } from "./config.mjs";

const config = loadConfig();

function envValue(nameOrValue) {
  return nameOrValue ? process.env[nameOrValue] : "";
}

function hmac(key, value, encoding) {
  return crypto.createHmac("sha256", key).update(value).digest(encoding);
}

function sha256(value, encoding = "hex") {
  return crypto.createHash("sha256").update(value).digest(encoding);
}

function signingKey(secret, date, region, service) {
  const kDate = hmac(`AWS4${secret}`, date);
  const kRegion = hmac(kDate, region);
  const kService = hmac(kRegion, service);
  return hmac(kService, "aws4_request");
}

function isoBasic(date) {
  return date.toISOString().replace(/[:-]|\.\d{3}/g, "");
}

function publicUrl(baseUrl, key) {
  return `${baseUrl.replace(/\/+$/, "")}/${key.split("/").map(encodeURIComponent).join("/")}`;
}

function loadLatestReportPath() {
  const latestReport = path.join(config.paths.root, "output", "latest_report.json");
  if (fs.existsSync(latestReport)) {
    const payload = JSON.parse(fs.readFileSync(latestReport, "utf8"));
    if (payload.preview && fs.existsSync(payload.preview)) return payload.preview;
    if (payload.latest_preview && fs.existsSync(payload.latest_preview)) return payload.latest_preview;
  }
  return path.join(config.paths.output_dir, "filled-preview.png");
}

export async function uploadR2(filePath = loadLatestReportPath()) {
  const r2 = config.r2 || {};
  const accountId = envValue(r2.account_id_env) || r2.account_id;
  const accessKeyId = envValue(r2.access_key_id_env) || r2.access_key_id;
  const secretAccessKey = envValue(r2.secret_access_key_env) || r2.secret_access_key;
  const bucket = envValue(r2.bucket_env) || r2.bucket;
  const publicBaseUrl = envValue(r2.public_base_url_env) || r2.public_base_url;
  const missing = [];
  if (!accountId) missing.push(r2.account_id_env || "r2.account_id");
  if (!accessKeyId) missing.push(r2.access_key_id_env || "r2.access_key_id");
  if (!secretAccessKey) missing.push(r2.secret_access_key_env || "r2.secret_access_key");
  if (!bucket) missing.push(r2.bucket_env || "r2.bucket");
  if (!publicBaseUrl) missing.push(r2.public_base_url_env || "r2.public_base_url");
  if (missing.length) {
    throw new Error(`R2 config missing: ${missing.join(", ")}`);
  }
  if (!fs.existsSync(filePath)) {
    throw new Error(`PNG not found for R2 upload: ${filePath}`);
  }

  const body = fs.readFileSync(filePath);
  const now = new Date();
  const amzDate = isoBasic(now);
  const dateStamp = amzDate.slice(0, 8);
  const region = "auto";
  const service = "s3";
  const prefix = String(r2.key_prefix || "reports").replace(/^\/+|\/+$/g, "");
  const key = `${prefix}/${timestampForFilename(now)}-${path.basename(filePath).replace(/[^\w.\-\u4e00-\u9fa5]/g, "_")}`;
  const encodedKey = key.split("/").map(encodeURIComponent).join("/");
  const host = `${accountId}.r2.cloudflarestorage.com`;
  const canonicalUri = `/${bucket}/${encodedKey}`;
  const payloadHash = sha256(body);
  const headers = {
    "content-type": "image/png",
    host,
    "x-amz-content-sha256": payloadHash,
    "x-amz-date": amzDate,
  };
  const signedHeaders = Object.keys(headers).sort().join(";");
  const canonicalHeaders = Object.keys(headers).sort().map((name) => `${name}:${headers[name]}\n`).join("");
  const canonicalRequest = [
    "PUT",
    canonicalUri,
    "",
    canonicalHeaders,
    signedHeaders,
    payloadHash,
  ].join("\n");
  const credentialScope = `${dateStamp}/${region}/${service}/aws4_request`;
  const stringToSign = [
    "AWS4-HMAC-SHA256",
    amzDate,
    credentialScope,
    sha256(canonicalRequest),
  ].join("\n");
  const signature = hmac(signingKey(secretAccessKey, dateStamp, region, service), stringToSign, "hex");
  const authorization = `AWS4-HMAC-SHA256 Credential=${accessKeyId}/${credentialScope}, SignedHeaders=${signedHeaders}, Signature=${signature}`;
  const uploadUrl = `https://${host}${canonicalUri}`;
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: {
      ...headers,
      authorization,
    },
    body,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`R2 upload failed: HTTP ${response.status} ${text.slice(0, 500)}`);
  }

  const result = {
    status: "uploaded",
    bucket,
    key,
    source: normalizePath(filePath),
    url: publicUrl(publicBaseUrl, key),
    uploaded_at: new Date().toISOString(),
  };
  const out = path.join(config.paths.root, "output", "r2_upload.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n", "utf8");
  return result;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  uploadR2(process.argv[2]).then((result) => {
    console.log(JSON.stringify(result, null, 2));
  }).catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
