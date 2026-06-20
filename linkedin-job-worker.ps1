param(
    [switch]$RunOnce
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Web
Add-Type -AssemblyName System.Net.Http

$script:AppRoot           = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:SettingsPath      = Join-Path $script:AppRoot "settings.json"
$script:StatePath         = Join-Path $script:AppRoot "seen-jobs.json"
$script:LogPath           = Join-Path $script:AppRoot "worker.log"
$script:PidPath           = Join-Path $script:AppRoot "worker.pid"
$script:TelegramOffsetPath = Join-Path $script:AppRoot "telegram-offset.json"
$script:HttpClient   = [System.Net.Http.HttpClient]::new()
$script:HttpClient.Timeout = [TimeSpan]::FromSeconds(25)
$script:HttpClient.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) LinkedInJobAlertWorker/1.0")

. (Join-Path $script:AppRoot "job-database.ps1")
. (Join-Path $script:AppRoot "shared-functions.ps1")

function Write-WorkerLog {
    param([string]$Message)

    $line = "[{0}] {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8
}

$script:LogFunction          = { param($m) Write-WorkerLog $m }
$script:WorkerLastScanSummary = ""
$script:WorkerTgScanToken     = ""
$script:WorkerTgScanChatId    = ""
$script:WorkerLastScanInserted = 0   # set by Invoke-WorkerScan; read by enricher auto-trigger

function Invoke-EnricherAsync {
    <#
    Fire-and-forget launch of cloud/enricher.py as a background Python process.
    Called by the main loop after a scan that produced new jobs.
    Guarded by enricher.pid so we never run two concurrently.
    #>
    $enricherPath    = Join-Path $script:AppRoot "cloud\enricher.py"
    if (-not (Test-Path -LiteralPath $enricherPath)) {
        return
    }

    $enricherPidFile = Join-Path $script:AppRoot "enricher.pid"
    if (Test-Path -LiteralPath $enricherPidFile) {
        try {
            $oldPid = [int](Get-Content -LiteralPath $enricherPidFile -Raw)
            if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
                Write-WorkerLog "Enricher already running (PID $oldPid). Skipping this trigger."
                return
            }
            Remove-Item -LiteralPath $enricherPidFile -Force -ErrorAction SilentlyContinue
        } catch {
            Remove-Item -LiteralPath $enricherPidFile -Force -ErrorAction SilentlyContinue
        }
    }

    try {
        $s       = Load-SettingsObject
        $sUrl    = [string](Get-SettingValue -SettingsObject $s -Name "SupabaseUrl"    -DefaultValue "")
        $sKey    = [string](Get-SettingValue -SettingsObject $s -Name "SupabaseKey"    -DefaultValue "")
        $cookie  = [string](Get-SettingValue -SettingsObject $s -Name "LinkedInCookie" -DefaultValue "")
        $ollama  = [string](Get-SettingValue -SettingsObject $s -Name "OllamaUrl"      -DefaultValue "http://localhost:11434")
        $minSc   = [string](Get-SettingValue -SettingsObject $s -Name "MinAiScore"     -DefaultValue "4")

        if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) {
            Write-WorkerLog "Enricher: Supabase credentials missing - skipping auto-enrichment."
            return
        }

        # Briefly export env vars so the spawned python inherits them
        $envBackup = @{
            SUPABASE_URL    = $env:SUPABASE_URL
            SUPABASE_KEY    = $env:SUPABASE_KEY
            LINKEDIN_COOKIE = $env:LINKEDIN_COOKIE
        }
        $env:SUPABASE_URL    = $sUrl
        $env:SUPABASE_KEY    = $sKey
        $env:LINKEDIN_COOKIE = $cookie

        $stdLog = Join-Path $script:AppRoot "enricher-last-run.log"
        $errLog = Join-Path $script:AppRoot "enricher-last-run.err.log"

        try {
            $proc = Start-Process -FilePath "python" `
                -ArgumentList @($enricherPath, "--ollama", $ollama, "--min-score", $minSc, "--limit", "10") `
                -WorkingDirectory $script:AppRoot `
                -NoNewWindow `
                -RedirectStandardOutput $stdLog `
                -RedirectStandardError  $errLog `
                -PassThru
            if ($proc -and $proc.Id) {
                Set-Content -LiteralPath $enricherPidFile -Value $proc.Id -Encoding ASCII
                Write-WorkerLog "Enricher launched (PID $($proc.Id)) - last-run log: enricher-last-run.log"
            }
        } finally {
            # Restore original env (only mutated for this launch)
            if ($null -eq $envBackup.SUPABASE_URL)    { Remove-Item Env:\SUPABASE_URL    -ErrorAction SilentlyContinue } else { $env:SUPABASE_URL    = $envBackup.SUPABASE_URL }
            if ($null -eq $envBackup.SUPABASE_KEY)    { Remove-Item Env:\SUPABASE_KEY    -ErrorAction SilentlyContinue } else { $env:SUPABASE_KEY    = $envBackup.SUPABASE_KEY }
            if ($null -eq $envBackup.LINKEDIN_COOKIE) { Remove-Item Env:\LINKEDIN_COOKIE -ErrorAction SilentlyContinue } else { $env:LINKEDIN_COOKIE = $envBackup.LINKEDIN_COOKIE }
        }
    } catch {
        Write-WorkerLog "Enricher launch failed: $($_.Exception.Message)"
    }
}

function Invoke-CloudPipelineAsync {
    <#
    Fire-and-forget: worker.py (Supabase sync) → enricher.py (AI score) → user_alerts.py (Telegram).
    Runs after every scan so Telegram delivery happens within minutes, not 30+ min GitHub Actions delay.
    Guarded by cloud-pipeline.pid to prevent concurrent runs.
    #>
    $workerPath  = Join-Path $script:AppRoot "cloud\worker.py"
    $enrichPath  = Join-Path $script:AppRoot "cloud\enricher.py"
    $alertsPath  = Join-Path $script:AppRoot "cloud\user_alerts.py"
    if (-not (Test-Path -LiteralPath $workerPath)) { return }
    if (-not (Test-Path -LiteralPath $alertsPath)) { return }

    $pidFile = Join-Path $script:AppRoot "cloud-pipeline.pid"
    if (Test-Path -LiteralPath $pidFile) {
        try {
            $oldPid = [int](Get-Content -LiteralPath $pidFile -Raw)
            if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
                Write-WorkerLog "Cloud pipeline already running (PID $oldPid). Skipping."
                return
            }
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        } catch {
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        }
    }

    try {
        $s       = Load-SettingsObject
        $sUrl    = [string](Get-SettingValue -SettingsObject $s -Name "SupabaseUrl"      -DefaultValue "")
        $sKey    = [string](Get-SettingValue -SettingsObject $s -Name "SupabaseKey"      -DefaultValue "")
        $tgToken = [string](Get-SettingValue -SettingsObject $s -Name "TelegramBotToken" -DefaultValue "")
        $tgChat  = [string](Get-SettingValue -SettingsObject $s -Name "TelegramChatId"   -DefaultValue "")
        $cookie  = [string](Get-SettingValue -SettingsObject $s -Name "LinkedInCookie"   -DefaultValue "")
        $groqKey = [string](Get-SettingValue -SettingsObject $s -Name "GroqApiKey"       -DefaultValue "")
        $resend  = [string](Get-SettingValue -SettingsObject $s -Name "ResendApiKey"     -DefaultValue "")

        if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) {
            Write-WorkerLog "Cloud pipeline: Supabase credentials missing — skipping."
            return
        }

        # Set env vars so child process inherits them
        $envBackup = @{
            SUPABASE_URL       = $env:SUPABASE_URL
            SUPABASE_KEY       = $env:SUPABASE_KEY
            TELEGRAM_BOT_TOKEN = $env:TELEGRAM_BOT_TOKEN
            TELEGRAM_CHAT_ID   = $env:TELEGRAM_CHAT_ID
            LINKEDIN_COOKIE    = $env:LINKEDIN_COOKIE
            GROQ_API_KEY       = $env:GROQ_API_KEY
            RESEND_API_KEY     = $env:RESEND_API_KEY
        }
        $env:SUPABASE_URL       = $sUrl
        $env:SUPABASE_KEY       = $sKey
        $env:TELEGRAM_BOT_TOKEN = $tgToken
        $env:TELEGRAM_CHAT_ID   = $tgChat
        $env:LINKEDIN_COOKIE    = $cookie
        $env:GROQ_API_KEY       = $groqKey
        $env:RESEND_API_KEY     = $resend

        $logPath     = Join-Path $script:AppRoot "cloud-pipeline.log"
        $pidFilePath = $pidFile  # capture for launcher script

        # Launcher script runs the 3-step pipeline and removes its own PID file when done
        $launcherPath = Join-Path $script:AppRoot "cloud-pipeline-launcher.ps1"
        $enrichCmd = if (Test-Path -LiteralPath $enrichPath) {
            "python '$enrichPath' --prefer-cloud --limit 20 --min-score 4 2>&1 | Add-Content -LiteralPath '$logPath'"
        } else { "" }

        $launcher = @"
`$ErrorActionPreference = 'Continue'
Set-Location '$($script:AppRoot)'
python '$workerPath' 2>&1 | Add-Content -LiteralPath '$logPath'
$enrichCmd
python '$alertsPath' --mode instant 2>&1 | Add-Content -LiteralPath '$logPath'
Remove-Item -LiteralPath '$pidFilePath' -Force -ErrorAction SilentlyContinue
"@
        Set-Content -LiteralPath $launcherPath -Value $launcher -Encoding UTF8

        try {
            $proc = Start-Process -FilePath "powershell.exe" `
                -ArgumentList @("-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $launcherPath) `
                -WorkingDirectory $script:AppRoot `
                -WindowStyle Hidden `
                -PassThru
            if ($proc -and $proc.Id) {
                Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
                Write-WorkerLog "Cloud pipeline launched (PID $($proc.Id)): worker → enricher → user_alerts"
            }
        } catch {
            Write-WorkerLog "Cloud pipeline Start-Process failed: $($_.Exception.Message)"
        }
    } catch {
        Write-WorkerLog "Cloud pipeline launch failed: $($_.Exception.Message)"
    } finally {
        foreach ($k in $envBackup.Keys) {
            if ($null -eq $envBackup[$k]) { Remove-Item "Env:\$k" -ErrorAction SilentlyContinue }
            else { Set-Item "Env:\$k" $envBackup[$k] }
        }
    }
}

function Get-WorkerSettingsSummary {
    try {
        $s = Load-SettingsObject
    }
    catch {
        return "Could not load settings: $($_.Exception.Message)"
    }
    $kw   = @(Get-SettingValue -SettingsObject $s -Name "Keywords"        -DefaultValue @()) | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
    $loc  = [string](Get-SettingValue -SettingsObject $s -Name "Location"        -DefaultValue "UAE")
    $intv = [string](Get-SettingValue -SettingsObject $s -Name "IntervalMinutes" -DefaultValue 5)
    $filt = [string](Get-SettingValue -SettingsObject $s -Name "TimeFilter"      -DefaultValue "Last 24 hours")
    $hrs  = [string](Get-SettingValue -SettingsObject $s -Name "CustomHours"     -DefaultValue 24)
    $li   = [string](Get-SettingValue -SettingsObject $s -Name "SearchLinkedIn"  -DefaultValue $true)
    $ind  = [string](Get-SettingValue -SettingsObject $s -Name "SearchIndeed"    -DefaultValue $true)
    $hide = [string](Get-SettingValue -SettingsObject $s -Name "HideAppliedJobs" -DefaultValue $true)
    return (@(
        "Current settings:",
        "Keywords    : $($kw -join ', ')",
        "Location    : $loc",
        "Interval    : $intv min",
        "Filter      : $filt",
        "Custom hrs  : $hrs",
        "LinkedIn    : $li",
        "Indeed      : $ind",
        "Hide applied: $hide"
    ) -join "`n")
}

function Apply-WorkerSetting {
    param([string]$Field, [string]$Value)
    try {
        $raw = Get-Content -LiteralPath $script:SettingsPath -Raw | ConvertFrom-Json
        $obj = [ordered]@{}
        foreach ($p in $raw.PSObject.Properties) { $obj[$p.Name] = $p.Value }
    }
    catch {
        return "Error loading settings: $($_.Exception.Message)"
    }
    switch ($Field.ToLower()) {
        "keyword"  {
            $kws = ($Value -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
            $obj["Keywords"] = $kws
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Keywords set to: $($kws -join ', '). Takes effect next scan."
        }
        "location" {
            $obj["Location"] = $Value.Trim()
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Location set to: $($Value.Trim()). Takes effect next scan."
        }
        "interval" {
            $n = [Math]::Max(1, [int]$Value)
            $obj["IntervalMinutes"] = $n
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Interval set to: $n min. Takes effect next sleep cycle."
        }
        "filter"   {
            $map = @{ "1h"="Last 1 hour"; "2h"="Last 2 hours"; "24h"="Last 24 hours"; "week"="Last week"; "month"="Last month"; "custom"="Custom" }
            $mapped = if ($map.ContainsKey($Value.ToLower())) { $map[$Value.ToLower()] } else { $Value }
            $obj["TimeFilter"] = $mapped
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Filter set to: $mapped. Takes effect next scan."
        }
        "hours"    {
            $obj["CustomHours"] = [Math]::Max(1, [int]$Value)
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Custom hours set to: $Value. Takes effect next scan."
        }
        "linkedin" {
            $obj["SearchLinkedIn"] = ($Value.ToLower() -in @("on","true","yes","1"))
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "LinkedIn search: $($obj['SearchLinkedIn']). Takes effect next scan."
        }
        "indeed"   {
            $obj["SearchIndeed"] = ($Value.ToLower() -in @("on","true","yes","1"))
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Indeed search: $($obj['SearchIndeed']). Takes effect next scan."
        }
        "hide"     {
            $obj["HideAppliedJobs"] = ($Value.ToLower() -in @("on","true","yes","1"))
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Hide applied jobs: $($obj['HideAppliedJobs']). Takes effect next scan."
        }
        "cookie"   {
            $obj["LinkedInCookie"] = $Value.Trim()
            $obj | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
            return "Cookie updated. Takes effect next scan."
        }
        default    {
            return "Unknown field '$Field'. Fields: keyword, location, interval, filter, hours, linkedin, indeed, hide, cookie"
        }
    }
}

function Load-SettingsObject {
    if (-not (Test-Path -LiteralPath $script:SettingsPath)) {
        throw "settings.json was not found."
    }

    return Get-Content -LiteralPath $script:SettingsPath -Raw | ConvertFrom-Json
}

function Load-SeenJobs {
    if (-not (Test-Path -LiteralPath $script:StatePath)) {
        return @{}
    }

    try {
        $raw = Get-Content -LiteralPath $script:StatePath -Raw | ConvertFrom-Json
        $map = @{}
        foreach ($entry in $raw.PSObject.Properties) {
            $map[$entry.Name] = [string]$entry.Value
        }
        return $map
    }
    catch {
        return @{}
    }
}

function Save-SeenJobs {
    param($SeenJobs)
    $pruned = Prune-SeenJobs -SeenJobs $SeenJobs
    $pruned | ConvertTo-Json | Set-Content -LiteralPath $script:StatePath -Encoding UTF8
}

function Get-TimeFilterHours {
    param($Settings)

    $selection = [string](Get-SettingValue -SettingsObject $Settings -Name "TimeFilter" -DefaultValue "Last 24 hours")
    switch ($selection) {
        "Last 1 hour"   { return 1 }
        "Last 2 hours"  { return 2 }
        "Last 24 hours" { return 24 }
        "Last week"     { return 24 * 7 }
        "Last month"    { return 24 * 30 }
        "Custom"        { return [int](Get-SettingValue -SettingsObject $Settings -Name "CustomHours" -DefaultValue 24) }
        default         { return 24 }
    }
}

function Invoke-WorkerScan {
    $settings         = Load-SettingsObject
    $seenJobs         = Load-SeenJobs
    $keywords         = @((Get-SettingValue -SettingsObject $settings -Name "Keywords" -DefaultValue @()) | ForEach-Object { "$_".Trim() } | Where-Object { $_ })
    $location         = [string](Get-SettingValue -SettingsObject $settings -Name "Location"         -DefaultValue "United Arab Emirates")
    $cookieHeader     = [string](Get-SettingValue -SettingsObject $settings -Name "LinkedInCookie"   -DefaultValue "")
    $hideAppliedJobs  = [bool](Get-SettingValue   -SettingsObject $settings -Name "HideAppliedJobs"  -DefaultValue $false)
    $maxHours         = Get-TimeFilterHours -Settings $settings
    $telegramBotToken = [string](Get-SettingValue -SettingsObject $settings -Name "TelegramBotToken" -DefaultValue "")
    $telegramChatId   = [string](Get-SettingValue -SettingsObject $settings -Name "TelegramChatId"   -DefaultValue "")
    $logCb            = { param($m) Write-WorkerLog $m }

    if ($keywords.Count -eq 0) {
        Write-WorkerLog "No keywords configured."
        $script:WorkerLastScanSummary = "Scan skipped: no keywords configured."
        return
    }

    # ── Parallel keyword fetch (RunspacePool) ─────────────────────────────────────
    # Each keyword gets its own thread; DB sync stays on the main thread (SQLite safety).
    $fetchScript = {
        param($Keyword, $Location, $CookieHeader, $HideAppliedJobs, $MaxHours, $AppRoot, $HttpClient, $StartJitterMs)
        $ErrorActionPreference = "Stop"
        $script:HttpClient  = $HttpClient
        $script:AppRoot     = $AppRoot
        $script:LogFunction = $null                   # will be set to null; LogFunction checks guard $null
        . (Join-Path $AppRoot "shared-functions.ps1") # defines Get-LinkedInJobs, Get-IndeedJobs, etc.
        if ($StartJitterMs -gt 0) { Start-Sleep -Milliseconds $StartJitterMs }

        $liJobs     = @()
        $indeedJobs = @()
        $log        = [System.Collections.Generic.List[string]]::new()
        try {
            $liJobs     = @(Get-LinkedInJobs -Keyword $Keyword -Location $Location -CookieHeader $CookieHeader -HideAppliedJobs:$HideAppliedJobs -MaxHours $MaxHours)
            $indeedJobs = @(Get-IndeedJobs   -Keyword $Keyword -Location $Location -MaxHours $MaxHours)
        } catch {
            $log.Add("Fetch error for '$Keyword': $($_.Exception.Message)")
        }
        [pscustomobject]@{ Keyword = $Keyword; LI = $liJobs; Indeed = $indeedJobs; Log = $log }
    }

    $maxThreads = 1  # LinkedIn rate-limits parallel requests from the same session; keep strictly sequential
    $pool = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspacePool(1, $maxThreads)
    $pool.Open()

    $pending = [System.Collections.Generic.List[object]]::new()
    $kwIndex  = 0
    foreach ($kw in $keywords) {
        $jitterMs = if ($kwIndex -eq 0) { 0 } else { 2000 + (Get-Random -Minimum 0 -Maximum 1000) }  # 2-3s gap between keywords
        $ps = [System.Management.Automation.PowerShell]::Create()
        $ps.RunspacePool = $pool
        [void]$ps.AddScript($fetchScript)
        [void]$ps.AddParameters(@{
            Keyword         = $kw
            Location        = $location
            CookieHeader    = $cookieHeader
            HideAppliedJobs = $hideAppliedJobs
            MaxHours        = $maxHours
            AppRoot         = $script:AppRoot
            HttpClient      = $script:HttpClient
            StartJitterMs   = $jitterMs
        })
        $pending.Add([pscustomobject]@{ PS = $ps; Result = $ps.BeginInvoke(); Keyword = $kw })
        $kwIndex++
    }

    $allLiJobs     = [System.Collections.Generic.List[object]]::new()
    $allIndeedJobs = [System.Collections.Generic.List[object]]::new()
    foreach ($item in $pending) {
        try {
            $out = $item.PS.EndInvoke($item.Result)
            if ($out.Count -gt 0) {
                $r = $out[0]
                foreach ($line in @($r.Log))   { Write-WorkerLog $line }
                foreach ($j   in @($r.LI))     { $allLiJobs.Add($j) }
                foreach ($j   in @($r.Indeed)) { $allIndeedJobs.Add($j) }
            }
        } catch {
            Write-WorkerLog "Parallel fetch failed for '$($item.Keyword)': $($_.Exception.Message)"
        } finally {
            $item.PS.Dispose()
        }
    }
    $pool.Close()
    $pool.Dispose()

    # ── Database sync (sequential - SQLite requires single-writer) ─────────────────
    $dbSyncLi = Sync-JobsToDatabase -Jobs @($allLiJobs) -Source "LinkedIn"
    Write-WorkerLog "LinkedIn total: inserted $($dbSyncLi.inserted), updated $($dbSyncLi.updated), seen $($dbSyncLi.seen), invalid $($dbSyncLi.invalid)."
    $dbSyncIndeed = Sync-JobsToDatabase -Jobs @($allIndeedJobs) -Source "Indeed"
    Write-WorkerLog "Indeed total: inserted $($dbSyncIndeed.inserted), updated $($dbSyncIndeed.updated), seen $($dbSyncIndeed.seen), invalid $($dbSyncIndeed.invalid)."
    $script:WorkerLastScanInserted = [int]$dbSyncLi.inserted + [int]$dbSyncIndeed.inserted

    $visibleJobs = @((@($allLiJobs) + @($allIndeedJobs)) |
        Where-Object { (Get-PostedAgeHours -Job $_) -le $maxHours } |
        Group-Object Id | ForEach-Object { $_.Group[0] })
    $newJobs     = @($visibleJobs | Where-Object { -not $seenJobs.ContainsKey($_.Id) })

    foreach ($job in $visibleJobs) {
        if (-not $seenJobs.ContainsKey($job.Id)) {
            $seenJobs[$job.Id] = (Get-Date).ToString("o")
        }
    }
    Save-SeenJobs -SeenJobs $seenJobs

    if ($newJobs.Count -eq 0) {
        Write-WorkerLog "No new jobs. Visible jobs in current time window: $($visibleJobs.Count)."
        $script:WorkerLastScanSummary = "Scan done. No new jobs. $($visibleJobs.Count) visible."
        return
    }

    # Secondary dedup: skip any URL already recorded as sent in the database
    $sentUrls = $null
    try {
        Initialize-JobDatabase
        $sentUrls = Get-TelegramSentUrls
    }
    catch {
        Write-WorkerLog "Warning: could not load sent-URL list from DB: $($_.Exception.Message)"
        $sentUrls = [System.Collections.Generic.HashSet[string]]::new()
    }

    $canonicalSentUrls = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($u in $sentUrls) { [void]$canonicalSentUrls.Add((Get-CanonicalJobUrl -Url $u)) }

    $newJobs = @($newJobs | Where-Object {
        $cu = Get-CanonicalJobUrl -Url $_.Url
        [string]::IsNullOrWhiteSpace($cu) -or -not $canonicalSentUrls.Contains($cu)
    })

    if ($newJobs.Count -eq 0) {
        Write-WorkerLog "All new jobs already sent to Telegram (URL dedup). Visible: $($visibleJobs.Count)."
        $script:WorkerLastScanSummary = "Scan done. No new jobs (all already sent). $($visibleJobs.Count) visible."
        return
    }

    $sentCount = 0
    foreach ($job in $newJobs) {
        if (Send-TelegramMessage -BotToken $telegramBotToken -ChatId $telegramChatId -Message (Format-TelegramMessage -Job $job) -LogCallback $logCb) {
            $sentCount += 1
            try { Set-JobTelegramSent -Url $job.Url } catch {}
        }
    }

    Write-WorkerLog "New jobs found: $($newJobs.Count). Telegram sent: $sentCount."
    $script:WorkerLastScanSummary = "Scan done. Found $($newJobs.Count) new job(s). Sent $sentCount alert(s)."
}

function Test-ExistingWorker {
    if (-not (Test-Path -LiteralPath $script:PidPath)) {
        return $false
    }

    try {
        $pidValue = [int](Get-Content -LiteralPath $script:PidPath -Raw)
        $process  = Get-Process -Id $pidValue -ErrorAction Stop
        return ($null -ne $process)
    }
    catch {
        Remove-Item -LiteralPath $script:PidPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

# Catch any unhandled crash that occurs outside the main try block (e.g. during init)
trap {
    $ts      = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    $logFile = if ($script:LogPath) { $script:LogPath } else { Join-Path (if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }) "worker.log" }
    try { Add-Content -LiteralPath $logFile -Value "[$ts] FATAL TRAP: $($_.Exception.Message)" -Encoding UTF8 } catch {}
    try { Add-Content -LiteralPath $logFile -Value "[$ts] Stack: $($_.ScriptStackTrace)"        -Encoding UTF8 } catch {}
    break
}

if (-not $RunOnce) {
    if (Test-ExistingWorker) {
        Write-WorkerLog "Worker is already running."
        exit 0
    }

    Set-Content -LiteralPath $script:PidPath -Value $PID -Encoding ASCII
    Write-WorkerLog "Worker process started (PID $PID)."
}

try {
    do {
        # Capture any pending Telegram scan-reply tokens BEFORE running the scan
        $tgScanToken  = $script:WorkerTgScanToken
        $tgScanChatId = $script:WorkerTgScanChatId
        $script:WorkerTgScanToken  = ""
        $script:WorkerTgScanChatId = ""
        $script:WorkerLastScanSummary  = ""
        $script:WorkerLastScanInserted = 0

        try {
            Invoke-WorkerScan
        }
        catch {
            $script:WorkerLastScanSummary = "Scan failed: $($_.Exception.Message)"
            Write-WorkerLog $script:WorkerLastScanSummary
        }

        # Auto-trigger local LLM enrichment after scans that produced new jobs.
        # Fire-and-forget: enricher writes its own log; we don't block the loop.
        if ($script:WorkerLastScanInserted -gt 0) {
            Invoke-EnricherAsync
        }

        # Always run cloud pipeline: syncs to Supabase, scores with Groq, sends Telegram immediately.
        # This eliminates the 10-30 min GitHub Actions scheduling delay.
        Invoke-CloudPipelineAsync

        # Send scan result to Telegram if this iteration was triggered by /scan command
        if (-not [string]::IsNullOrWhiteSpace($tgScanToken) -and -not [string]::IsNullOrWhiteSpace($script:WorkerLastScanSummary)) {
            try {
                [void](Send-TelegramMessage -BotToken $tgScanToken -ChatId $tgScanChatId `
                    -Message $script:WorkerLastScanSummary -LogCallback { param($m) Write-WorkerLog $m })
            } catch { Write-WorkerLog "Could not send scan result to Telegram: $($_.Exception.Message)" }
        }

        if ($RunOnce) {
            break
        }

        $settings        = Load-SettingsObject
        $intervalMinutes = [int](Get-SettingValue -SettingsObject $settings -Name "IntervalMinutes" -DefaultValue 5)
        $botToken        = [string](Get-SettingValue -SettingsObject $settings -Name "TelegramBotToken" -DefaultValue "")
        $chatId          = [string](Get-SettingValue -SettingsObject $settings -Name "TelegramChatId"   -DefaultValue "")
        $sleepUntil      = (Get-Date).AddSeconds([Math]::Max(1, $intervalMinutes) * 60)
        $tgOffset        = Read-TelegramOffset -Path $script:TelegramOffsetPath
        $triggerRescan   = $false
        $triggerStop     = $false

        while ((Get-Date) -lt $sleepUntil -and -not $triggerRescan -and -not $triggerStop) {
            if (-not [string]::IsNullOrWhiteSpace($botToken)) {
                foreach ($update in @(Get-TelegramUpdates -BotToken $botToken -Offset $tgOffset)) {
                    $tgOffset = $update.update_id + 1
                    if (-not $update.message -or [string]::IsNullOrWhiteSpace([string]$update.message.text)) { continue }
                    $fromChat = [string]$update.message.chat.id
                    if ($fromChat -ne $chatId) { continue }
                    $rawText  = [string]$update.message.text
                    $cmd      = Get-TelegramCommandText -Raw $rawText
                    Write-WorkerLog "Telegram: $cmd"
                    try {
                        switch -Wildcard ($cmd) {
                            "/scan*" {
                                $script:WorkerTgScanToken  = $botToken
                                $script:WorkerTgScanChatId = $chatId
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message "Scanning now - you will receive the result when done." -LogCallback { param($m) Write-WorkerLog $m })
                                $triggerRescan = $true
                            }
                            "/start*" {
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message "Worker is already running (PID $PID)." -LogCallback { param($m) Write-WorkerLog $m })
                            }
                            "/stop*" {
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message "Worker stopping now..." -LogCallback { param($m) Write-WorkerLog $m })
                                Write-WorkerLog "Telegram: /stop received. Shutting down."
                                $triggerStop   = $true
                                $triggerRescan = $true
                            }
                            "/jobs*" {
                                $reply = Get-RecentJobsSummary
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message $reply -LogCallback { param($m) Write-WorkerLog $m })
                            }
                            "/status*" {
                                $minsLeft = [Math]::Max(0, [int]($sleepUntil - (Get-Date)).TotalMinutes)
                                $reply    = "Worker  : Running (PID $PID)`nNext scan: $minsLeft min`nInterval : $intervalMinutes min"
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message $reply -LogCallback { param($m) Write-WorkerLog $m })
                            }
                            "/get*" {
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message (Get-WorkerSettingsSummary) -LogCallback { param($m) Write-WorkerLog $m })
                            }
                            "/set*" {
                                $parts = $rawText.Trim() -split '\s+', 3
                                if ($parts.Count -lt 3) {
                                    $reply = "Usage: /set <field> <value>`nFields: keyword, location, interval, filter, hours, linkedin, indeed, hide, cookie"
                                } else {
                                    $reply = Apply-WorkerSetting -Field $parts[1] -Value $parts[2]
                                    if ($parts[1].ToLower() -eq "interval") {
                                        $intervalMinutes = [Math]::Max(1, [int]$parts[2])
                                        $sleepUntil      = (Get-Date).AddSeconds($intervalMinutes * 60)
                                    }
                                }
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message $reply -LogCallback { param($m) Write-WorkerLog $m })
                            }
                            default {
                                $help = @(
                                    "Commands:",
                                    "/scan              - Scan now (replies when done)",
                                    "/stop              - Stop worker",
                                    "/status            - Show status",
                                    "/jobs              - Recent jobs",
                                    "/get               - Show all settings",
                                    "/set keyword <val> - Keywords (comma-separated)",
                                    "/set location <val>- Location",
                                    "/set interval <n>  - Interval in minutes",
                                    "/set filter <val>  - 1h|2h|24h|week|month|custom",
                                    "/set hours <n>     - Custom hours",
                                    "/set linkedin on|off",
                                    "/set indeed on|off",
                                    "/set hide on|off   - Hide applied jobs",
                                    "/set cookie <val>  - LinkedIn cookie"
                                ) -join "`n"
                                [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message $help -LogCallback { param($m) Write-WorkerLog $m })
                            }
                        }
                    }
                    catch {
                        $errMsg = "Error: $($_.Exception.Message)"
                        Write-WorkerLog "Telegram command '$cmd' failed: $($_.Exception.Message)"
                        try { [void](Send-TelegramMessage -BotToken $botToken -ChatId $chatId -Message $errMsg) } catch {}
                    }
                }
                Save-TelegramOffset -Path $script:TelegramOffsetPath -Offset $tgOffset
            }
            if (-not $triggerRescan -and -not $triggerStop) { Start-Sleep -Seconds 10 }
        }

        if ($triggerStop) { break }
    } while ($true)
}
catch {
    Write-WorkerLog "Worker do-while crashed: $($_.Exception.Message)"
    try { Write-WorkerLog $_.ScriptStackTrace } catch {}
}
finally {
    if (-not $RunOnce) {
        Remove-Item -LiteralPath $script:PidPath -Force -ErrorAction SilentlyContinue
    }
    # Best-effort: leave enricher.pid alone (the python process owns it and may still be running)
    $script:HttpClient.Dispose()
}
