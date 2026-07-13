# Xianghe realtime report workflow

This project generates the Xianghe realtime report from three sources:

1. Web data through `browser-harness`: attendance, delivery rate, user T8 on-time rate, and daily deltas.
2. Android screen data through ADB: transaction amount, effective orders, order day/week deltas, agent subsidy, merchant subsidy, and subsidy deltas.
3. Excel template export through `@oai/artifact-tool`: filled `.xlsx` plus matching `.png` preview.
4. DingTalk delivery: send only the latest PNG report to the configured group.

DingTalk sending is enabled by default. The workflow sends the PNG only. It does not send the xlsx file or a text report.

## Run

```powershell
cd D:\AI-Workspace\Projects\xuanyuan-web-collector
.\run_xianghe_report.ps1
```

Default flow:

```text
collect_web_logistics
collect_adb_trade_marketing
validate_input_data
export_xlsx_png
post_export_review
send_dingtalk_message (PNG only)
```

## Common commands

```powershell
# Reuse existing collected JSON and only validate/export.
.\run_xianghe_report.ps1 --skip-web --skip-adb

# Validate current JSON only.
.\run_xianghe_report.ps1 --validate-only

# Full run and send DingTalk group PNG.
.\run_xianghe_report.ps1 --send-dingtalk

# Run without sending DingTalk.
.\run_xianghe_report.ps1 --no-send-dingtalk
```

## Configuration

All workflow settings are in `config.json`.

- `paths.template_xlsx`: Excel template path.
- `paths.output_dir`: report output folder.
- `excel.order_target`: order target used in completion rate.
- `progress_curve`: reference curve used for estimated completion rate.
- `checks`: required metrics, allowed ranges, and cross-checks.
- `dingtalk.enabled_by_default`: default DingTalk send switch.
- `dingtalk.group_query`: DingTalk group search keyword.
- `dingtalk.send_artifact`: `png`.
- `presentation.render_range`: compact PNG render range.

Chinese values in `config.json` are stored as JSON Unicode escapes so the workflow survives terminals that do not preserve UTF-8 source text.

## Outputs

- `outputs/xuanyuan-template/<report-name>-YYYYMMDDHHMM.xlsx`
- `outputs/xuanyuan-template/<report-name>-YYYYMMDDHHMM.png`
- `output/quality_report.json`
- `output/workflow_summary.json`

## Business rules

- Transaction amount comes from the ADB trade screen.
- Orders come from ADB effective orders, not web push orders.
- Trade day/week deltas come from the ADB trade screen.
- Agent subsidy and merchant subsidy come from the ADB marketing screen.
- Logistics on-time rate comes from web `user T8 on-time rate`.
