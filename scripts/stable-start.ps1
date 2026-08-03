param(
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $workspace ".stable"
$envFile = Join-Path $runtimeDir "host-opener.env"
$pidFile = Join-Path $runtimeDir "host-opener.pid"
$stdoutLog = Join-Path $runtimeDir "host-opener.stdout.log"
$stderrLog = Join-Path $runtimeDir "host-opener.stderr.log"
$python = Join-Path $workspace "backend\.venv\Scripts\python.exe"
$openerSource = Join-Path $workspace "scripts\host_link_opener.py"
$openerScript = Join-Path $runtimeDir "host_link_opener.py"
$composeFile = Join-Path $workspace "docker-compose.stable.yml"

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

if (-not (Test-Path $python)) {
    throw "Backend virtual environment not found: $python"
}
if ($Build -or -not (Test-Path $openerScript)) {
    Copy-Item -LiteralPath $openerSource -Destination $openerScript -Force
}

if (-not (Test-Path $envFile)) {
    $bytes = New-Object byte[] 32
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    $token = -join ($bytes | ForEach-Object { $_.ToString("x2") })
    @(
        "LINK_OPENER_TRANSPORT=host_companion"
        "HOST_LINK_OPENER_URL=http://host.docker.internal:18765/open"
        "HOST_LINK_OPENER_TOKEN=$token"
        "HOST_LINK_OPENER_TIMEOUT_SECONDS=5"
    ) | Set-Content -LiteralPath $envFile -Encoding ascii
}

$tokenLine = Get-Content -LiteralPath $envFile |
    Where-Object { $_ -like "HOST_LINK_OPENER_TOKEN=*" } |
    Select-Object -First 1
if (-not $tokenLine) {
    throw "HOST_LINK_OPENER_TOKEN is missing from $envFile"
}
$openerToken = $tokenLine.Substring("HOST_LINK_OPENER_TOKEN=".Length)

$running = $false
if (Test-Path $pidFile) {
    $savedPid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($savedPid) {
        $existing = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
        $running = $null -ne $existing
    }
}

if (-not $running) {
    $previousToken = $env:HOST_LINK_OPENER_TOKEN
    try {
        $env:HOST_LINK_OPENER_TOKEN = $openerToken
        $process = Start-Process `
            -FilePath $python `
            -ArgumentList @($openerScript, "--host", "0.0.0.0", "--port", "18765") `
            -WorkingDirectory $workspace `
            -WindowStyle Hidden `
            -RedirectStandardOutput $stdoutLog `
            -RedirectStandardError $stderrLog `
            -PassThru
        $process.Id | Set-Content -LiteralPath $pidFile -Encoding ascii
    } finally {
        $env:HOST_LINK_OPENER_TOKEN = $previousToken
    }
}

$companionReady = $false
for ($attempt = 0; $attempt -lt 20; $attempt++) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:18765/health" -TimeoutSec 2
        if ($health.status -eq "ok") {
            $companionReady = $true
            break
        }
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $companionReady) {
    throw "Host Link Opener did not become ready. Check $stderrLog"
}

$composeArgs = @("compose", "-f", $composeFile, "up", "-d")
if ($Build) {
    $composeArgs += "--build"
}
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker Compose failed with exit code $LASTEXITCODE"
}

Write-Host "Stable app: http://localhost:8080"
Write-Host "Host Link Opener: ready"
