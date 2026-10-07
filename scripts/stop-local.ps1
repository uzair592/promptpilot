[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $repositoryRoot ".local\run\processes.json"
if (-not (Test-Path -LiteralPath $stateFile -PathType Leaf)) {
    throw "No PromptPilot local process record was found."
}

$state = Get-Content -Raw -LiteralPath $stateFile | ConvertFrom-Json
$targets = @(
    @{
        Name = "frontend"
        Id = [int]$state.frontend_pid
        Marker = "@promptpilot/frontend"
    },
    @{
        Name = "backend"
        Id = [int]$state.backend_pid
        Marker = "promptpilot_backend.main:app"
    }
)

foreach ($target in $targets) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($target.Id)" -ErrorAction SilentlyContinue
    if ($null -eq $process) { continue }
    if ($process.CommandLine -notlike "*$($target.Marker)*") {
        throw "Refusing to stop PID $($target.Id): it is not the recorded PromptPilot $($target.Name) process."
    }
    & taskkill.exe /PID $target.Id /T /F 2>$null | Out-Null
}

Remove-Item -LiteralPath $stateFile -Force
Write-Host "PromptPilot local servers stopped."
