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

& $node ".\workflow\run_report.mjs" @args
