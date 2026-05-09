Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$appRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$pidPath = Join-Path $appRoot "worker.pid"
$workerScriptPath = Join-Path $appRoot "linkedin-job-worker.ps1"

function Stop-WorkerProcessesByCommandLine {
    $processes = Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.Name -match 'powershell' -and
            $_.CommandLine -and
            $_.CommandLine -match [regex]::Escape($workerScriptPath) -and
            $_.CommandLine -match '(?i)-File'
        }

    if (-not $processes) {
        return 0
    }

    $stopped = 0
    foreach ($process in $processes) {
        try {
            Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
            $stopped += 1
        }
        catch {
        }
    }

    return $stopped
}

if (-not (Test-Path -LiteralPath $pidPath)) {
    $stopped = Stop-WorkerProcessesByCommandLine
    if ($stopped -gt 0) {
        Write-Output "Worker stopped by process scan ($stopped process(es))."
    }
    else {
        Write-Output "Worker is not running."
    }
    exit 0
}

try {
    $pidValue = [int](Get-Content -LiteralPath $pidPath -Raw)
    Stop-Process -Id $pidValue -Force -ErrorAction Stop
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    Write-Output "Worker stopped."
}
catch {
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
    $stopped = Stop-WorkerProcessesByCommandLine
    if ($stopped -gt 0) {
        Write-Output "Worker stopped by process scan ($stopped process(es))."
        exit 0
    }
    throw
}
