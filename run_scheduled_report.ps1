$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$node = $env:NODE_EXE
if ([string]::IsNullOrWhiteSpace($node)) {
  $nodeCommand = Get-Command node -ErrorAction SilentlyContinue
  if (-not $nodeCommand) {
    throw "Node.js is required. Add node to PATH or set NODE_EXE."
  }
  $node = $nodeCommand.Source
}

Write-Host "=== 香河实时播报 · 定时运行 ===" -ForegroundColor Cyan
Write-Host "开始时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

$exitCode = 0
try {
  & $node ".\workflow\run_report.mjs" "--send-dingtalk" 2>&1 | Tee-Object -Variable output
  $exitCode = $LASTEXITCODE
} catch {
  Write-Host "工作流异常: $_" -ForegroundColor Red
  $exitCode = 1
}

# 读取异常报告
$anomalyPath = ".\output\anomaly_report.json"
if (Test-Path $anomalyPath) {
  try {
    $anomaly = Get-Content $anomalyPath -Raw | ConvertFrom-Json
    Write-Host ""
    Write-Host "=== 历史对比结果 ===" -ForegroundColor Yellow
    Write-Host "对比状态: $($anomaly.status)"
    Write-Host $anomaly.summary
    if ($anomaly.findings.Count -gt 0) {
      Write-Host "异常详情:" -ForegroundColor Red
      foreach ($f in $anomaly.findings) {
        Write-Host "  [$($f.severity)] $($f.reason)" -ForegroundColor $(if ($f.severity -eq 'critical') { 'Red' } else { 'Yellow' })
      }
    }
  } catch {
    Write-Host "无法解析异常报告: $_" -ForegroundColor Red
  }
}

Write-Host ""
Write-Host "结束时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "退出码: $exitCode"

exit $exitCode
