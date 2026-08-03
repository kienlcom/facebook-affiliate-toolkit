$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $workspace ".stable"
$pidFile = Join-Path $runtimeDir "host-opener.pid"
$composeFile = Join-Path $workspace "docker-compose.stable.yml"

& docker compose -f $composeFile ps

$companion = "stopped"
if (Test-Path $pidFile) {
    $savedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($savedPid -and (Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue)) {
        $companion = "running (PID $savedPid)"
    }
}
Write-Host "Host Link Opener: $companion"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 3
    Write-Host "App health: $($health.status)"
} catch {
    Write-Host "App health: unavailable"
}
