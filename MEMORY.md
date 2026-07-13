# Project Memory

## Project Facts
- Project name: xuanyuan-web-collector.
- Primary workflow command: `node workflow/run_report.mjs --send-dingtalk`.
- Dry-run workflow command: `node workflow/run_report.mjs --no-send-dingtalk`.
- Runtime context for reports and automation records uses Asia/Shanghai (UTC+08:00, no daylight saving time).
- Web collection must verify logistics selection and key logistics rates before downstream export or sending.
- Report image upload must complete and the public image URL must be accessible before DingTalk sending.
- DingTalk report delivery should remain image-only unless project rules explicitly change.

## Security Notes
- Do not store credential values in this file.
- R2, Blob, DingTalk, and other integration credentials are environment-managed.

## Verification Records
- 2026-07-06: `MEMORY.md` created because the repository had `AGENTS.md` but no project memory file.
- 2026-07-06 23:35:32 +08:00: `node workflow/run_report.mjs --send-dingtalk` failed during `collect_web_logistics`; `browser-harness` timed out after 120 seconds. No PNG upload or DingTalk send occurred.
- 2026-07-07 00:13:23 +08:00: `node workflow/run_report.mjs --send-dingtalk` failed during `collect_web_logistics`; `browser-harness` timed out after 120 seconds. OCR validation, PNG rendering, upload URL validation, and DingTalk sending were not executed.
- 2026-07-07 10:41:21 +08:00: `node workflow/run_report.mjs --no-send-dingtalk` succeeded and archived run `202607070235`; DingTalk sending was skipped for human review. ADB trade output used all business lines minus new retail: transaction amount `80607.81`, effective orders `2373`.
- 2026-07-07 10:44:28 +08:00: After human approval, `node send_dingtalk_report.mjs` succeeded with Vercel Blob image upload and URL validation. First attempt failed during upload because Node fetch used proxy; retry succeeded after clearing proxy environment variables. No webhook URL or token values recorded.
- 2026-07-07 13:55:36 +08:00: ADB rerun succeeded with `--skip-web --no-send-dingtalk` after full web reruns timed out in `browser-harness`. Rendered preview uses fresh ADB data collected at `2026-07-07T13:49:42+08:00` and restored web data from successful archive `202607070235` (`updated_at` `2026-07-07 10:35:56`), so quality status is warning due stale web data. No DingTalk send occurred.
- 2026-07-07 15:08:49 +08:00: `node workflow/run_report.mjs --no-send-dingtalk` succeeded and archived run `202607070704`; DingTalk sending was skipped. ADB trade collection was corrected to avoid relying on UIAutomator WebView text, use fixed coordinate business-line selection plus screenshot vision extraction for 毛GMV/有效订单量, and block invalid all-minus-new-retail negative results. Current ADB trade output: transaction amount `313377.01`, effective orders `8552`. Quality validation passed; history comparison is critical only because the prior archived comparison sample contained invalid negative ADB trade values.
- 2026-07-07 15:33:37 +08:00: `node workflow/run_report.mjs --no-send-dingtalk` succeeded and archived run `202607070729`; DingTalk sending was skipped. Web big-board collection now verifies that the 盯大盘 业务线 form displays 大网 before reading logistics metrics, and refuses to continue if 大网 is not verified. Current web big-board logistics output: 妥投率 `98.53%`, 用户T准时率（通用）`87.98%`, 平均预测T `37.63`. Quality validation and history comparison both passed.

- 2026-07-13: `config.json` is local-only and ignored. GitHub publication uses `config.example.json`, generated with credential, user-path, email, phone, ID, and sensitive URL values sanitized.
- 2026-07-13: PowerShell launchers use `$PSScriptRoot` plus `NODE_EXE` or `node` from PATH; user-specific Codex runtime paths are not publishable.
- 2026-07-13: A redacted Gitleaks history scan found two legacy generic API key detections in `config.json`. The existing local history must never be pushed; publish only a sanitized snapshot history.

## Known Collection Constraints
- MuMu/轩辕 ADB WebView card and dropdown contents are not reliably exposed through UIAutomator XML. Trade business-line selection should use fixed coordinates from `config.json`, then verify by screenshot/vision and sanity checks.
