# Run-Worker.ps1 — launches cloud/worker.py with settings from settings.json
# Scheduled via Task Scheduler to run every 5 minutes
param([switch]$Once)

$AppRoot    = Split-Path -Parent $PSScriptRoot
$Settings   = Get-Content (Join-Path $AppRoot "settings.json") | ConvertFrom-Json
$EnvFile    = Join-Path $PSScriptRoot ".env.local"   # service_role key lives here
$LogFile    = Join-Path $PSScriptRoot "worker-local.log"
$PidFile    = Join-Path $PSScriptRoot "worker-local.pid"
$WorkerPy   = Join-Path $PSScriptRoot "worker.py"

# Guard: don't run two at once
if (Test-Path $PidFile) {
    $oldPid = [int](Get-Content $PidFile -Raw -ErrorAction SilentlyContinue)
    if ($oldPid -and (Get-Process -Id $oldPid -ErrorAction SilentlyContinue)) {
        Write-Host "Worker already running (PID $oldPid). Exiting."
        exit 0
    }
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
$PID | Out-File $PidFile -Encoding ascii

function Write-Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Add-Content -LiteralPath $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

# Load .env.local for service_role key (if it exists)
$serviceRoleKey = ""
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match "^SUPABASE_KEY=(.+)$") { $serviceRoleKey = $Matches[1].Trim() }
    }
}

if (-not $serviceRoleKey) {
    Write-Log "ERROR: No SUPABASE_KEY found in cloud\.env.local"
    Write-Log "Create cloud\.env.local with: SUPABASE_KEY=<your_service_role_key>"
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    exit 1
}

# Set environment variables from settings.json
$env:SUPABASE_URL        = $Settings.SupabaseUrl
$env:SUPABASE_KEY        = $serviceRoleKey
$env:KEYWORDS            = ($Settings.Keywords -join ",")
$env:LOCATION            = $Settings.Location
$env:TELEGRAM_BOT_TOKEN  = $Settings.TelegramBotToken
$env:TELEGRAM_CHAT_ID    = $Settings.TelegramChatId
$env:MAX_HOURS           = $Settings.CustomHours
$env:LINKEDIN_COOKIE     = $Settings.LinkedInCookie
$env:HIDE_APPLIED        = $Settings.HideAppliedJobs.ToString().ToLower()
$env:SEARCH_LINKEDIN     = $Settings.SearchLinkedIn.ToString().ToLower()
$env:SEARCH_INDEED       = $Settings.SearchIndeed.ToString().ToLower()
$env:SEARCH_ADZUNA       = "false"
$env:SEARCH_WEB          = "false"
$env:SEARCH_GMAIL        = $Settings.SearchGmail.ToString().ToLower()

Write-Log "Starting cloud/worker.py..."

try {
    $proc = Start-Process -FilePath "python" -ArgumentList "`"$WorkerPy`"" `
        -WorkingDirectory $AppRoot -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput "$LogFile.stdout" -RedirectStandardError "$LogFile.stderr"

    Get-Content "$LogFile.stdout" -ErrorAction SilentlyContinue | ForEach-Object { Add-Content $LogFile $_ -Encoding UTF8 }
    Get-Content "$LogFile.stderr" -ErrorAction SilentlyContinue | ForEach-Object { Add-Content $LogFile "ERR: $_" -Encoding UTF8 }

    Write-Log "Worker finished (exit code $($proc.ExitCode))"
} catch {
    Write-Log "ERROR: $_"
} finally {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
