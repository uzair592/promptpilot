[CmdletBinding()]
param(
    [ValidateRange(1, 65535)]
    [int]$BackendPort = 8000,

    [ValidateRange(1, 65535)]
    [int]$FrontendPort = 3000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$backendRoot = Join-Path $repositoryRoot "apps\backend"
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
$pnpm = (Get-Command "pnpm.cmd" -ErrorAction Stop).Source
$runDirectory = Join-Path $repositoryRoot ".local\run"
$stateFile = Join-Path $runDirectory "processes.json"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Missing .venv. Follow the one-time setup in README.md first."
}
if ($BackendPort -eq $FrontendPort) {
    throw "BackendPort and FrontendPort must be different."
}

foreach ($port in @($BackendPort, $FrontendPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing listener before starting PromptPilot."
    }
}

New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$backendOutput = Join-Path $runDirectory "backend.out.log"
$backendError = Join-Path $runDirectory "backend.err.log"
$frontendOutput = Join-Path $runDirectory "frontend.out.log"
$frontendError = Join-Path $runDirectory "frontend.err.log"
foreach ($log in @($backendOutput, $backendError, $frontendOutput, $frontendError)) {
    Remove-Item -LiteralPath $log -Force -ErrorAction SilentlyContinue
}

function Wait-ForEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][string]$ErrorLog
    )

    for ($attempt = 0; $attempt -lt 120; $attempt += 1) {
        if ($Process.HasExited) {
            throw "A local server exited during startup. Check $ErrorLog"
        }
        try {
            $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) { return }
        }
        catch {
            Start-Sleep -Milliseconds 500
        }
    }
    throw "Timed out waiting for $Uri. Check $ErrorLog"
}

function Stop-ProcessTree {
    param([System.Diagnostics.Process]$Process)

    if ($null -ne $Process -and -not $Process.HasExited) {
        & taskkill.exe /PID $Process.Id /T /F 2>$null | Out-Null
    }
}

$backendProcess = $null
$frontendProcess = $null
$startupCompleted = $false
$previousPythonPath = $env:PYTHONPATH
$previousBackendOrigin = $env:BACKEND_ORIGIN
$previousProgressPreference = $ProgressPreference

try {
    $ProgressPreference = "SilentlyContinue"
    $env:PYTHONPATH = "src"
    $backendProcess = Start-Process `
        -FilePath $python `
        -ArgumentList @("-m", "uvicorn", "promptpilot_backend.main:app", "--host", "127.0.0.1", "--port", $BackendPort) `
        -WorkingDirectory $backendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $backendOutput `
        -RedirectStandardError $backendError `
        -PassThru

    $env:BACKEND_ORIGIN = "http://127.0.0.1:$BackendPort"
    $frontendProcess = Start-Process `
        -FilePath $pnpm `
        -ArgumentList @("--filter", "@promptpilot/frontend", "exec", "next", "dev", "--hostname", "127.0.0.1", "--port", $FrontendPort) `
        -WorkingDirectory $repositoryRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOutput `
        -RedirectStandardError $frontendError `
        -PassThru

    Wait-ForEndpoint -Uri "http://127.0.0.1:$BackendPort/healthz" -Process $backendProcess -ErrorLog $backendError
    Wait-ForEndpoint -Uri "http://127.0.0.1:$FrontendPort/login" -Process $frontendProcess -ErrorLog $frontendError

    @{
        backend_pid = $backendProcess.Id
        backend_port = $BackendPort
        frontend_pid = $frontendProcess.Id
        frontend_port = $FrontendPort
    } | ConvertTo-Json | Set-Content -LiteralPath $stateFile -Encoding UTF8
    $startupCompleted = $true

    Write-Host "PromptPilot is running at http://localhost:$FrontendPort/"
    Write-Host "Backend health: http://localhost:$BackendPort/healthz"
    Write-Host "Logs: $runDirectory"
    Write-Host "Stop both servers with .\scripts\stop-local.ps1"
}
finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:BACKEND_ORIGIN = $previousBackendOrigin
    $ProgressPreference = $previousProgressPreference
    if (-not $startupCompleted) {
        Stop-ProcessTree -Process $frontendProcess
        Stop-ProcessTree -Process $backendProcess
    }
}
