$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $workspace ".stable"
$pidFile = Join-Path $runtimeDir "host-opener.pid"
$composeFile = Join-Path $workspace "docker-compose.stable.yml"

& docker compose -f $composeFile down
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE"
}

if (Test-Path $pidFile) {
    $savedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($savedPid) {
        Stop-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force
}

Write-Host "Stable stack stopped. Database volume was preserved."
