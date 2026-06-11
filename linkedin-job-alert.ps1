Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Hide the PowerShell console window immediately — works regardless of how
# the script is launched (bat, vbs, shortcut, Windows Terminal, etc.)
Add-Type -Name ConsoleWindow -Namespace "" -MemberDefinition @"
    [DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();
    [DllImport("user32.dll")]   public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
"@
[ConsoleWindow]::ShowWindow([ConsoleWindow]::GetConsoleWindow(), 0) | Out-Null

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Web
Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.Security

$script:AppRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:StatePath    = Join-Path $script:AppRoot "seen-jobs.json"
$script:SettingsPath = Join-Path $script:AppRoot "settings.json"
$script:HttpClient   = [System.Net.Http.HttpClient]::new()
$script:HttpClient.Timeout = [TimeSpan]::FromSeconds(25)
$script:HttpClient.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")

$script:SeenJobs            = @{}
$script:HasPrimedState      = $false
$script:LastNotificationUrl = $null
$script:SqliteLoaded        = $false
$script:LastScanJobs        = @()
$script:DisplayedJobsByUrl  = @{}
$script:LogFunction         = $null
$script:WorkerStartedPid    = 0
$script:TgCmdReplyToken     = ""
$script:TgCmdReplyChatId    = ""
$script:CloudWorkflowId     = 0
$script:CloudLastRunId      = 0
$script:CloudLastRunUrl     = ""
$script:CloudScheduleActive = $true

. (Join-Path $script:AppRoot "job-database.ps1")
. (Join-Path $script:AppRoot "shared-functions.ps1")

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
    $script:SeenJobs = Prune-SeenJobs -SeenJobs $script:SeenJobs
    $script:SeenJobs | ConvertTo-Json | Set-Content -LiteralPath $script:StatePath -Encoding UTF8
}

function Load-Settings {
    if (-not (Test-Path -LiteralPath $script:SettingsPath)) {
        return $null
    }

    try {
        return Get-Content -LiteralPath $script:SettingsPath -Raw | ConvertFrom-Json
    }
    catch {
        return $null
    }
}

function Save-Settings {
    $existing      = Load-Settings
    $joobleApiKey  = [string](Get-SettingValue -SettingsObject $existing -Name "JoobleApiKey"   -DefaultValue "")
    $ghToken       = [string](Get-SettingValue -SettingsObject $existing -Name "GitHubToken"    -DefaultValue "")
    $ghRepo        = [string](Get-SettingValue -SettingsObject $existing -Name "GitHubRepo"     -DefaultValue "")
    $supabaseUrl   = [string](Get-SettingValue -SettingsObject $existing -Name "SupabaseUrl"    -DefaultValue "")
    $supabaseKey   = [string](Get-SettingValue -SettingsObject $existing -Name "SupabaseKey"    -DefaultValue "")

    $settings = [ordered]@{
        Keywords         = $script:KeywordsBox.Lines
        Location         = $script:CountryBox.Text.Trim()
        IntervalMinutes  = [int]$script:IntervalBox.Value
        TimeFilter       = $script:TimeFilterBox.Text
        CustomHours      = [int]$script:CustomHoursBox.Value
        BrowserChoice    = $script:BrowserBox.Text
        LinkedInCookie   = $script:CookieBox.Text.Trim()
        HideAppliedJobs  = $script:HideAppliedCheckBox.Checked
        TelegramBotToken = $script:TelegramTokenBox.Text.Trim()
        TelegramChatId   = $script:TelegramChatIdBox.Text.Trim()
        JoobleApiKey     = $joobleApiKey
        SearchLinkedIn   = $script:LinkedInCheckBox.Checked
        SearchIndeed     = $script:IndeedCheckBox.Checked
        ExcludeKeywords  = $script:ExcludeBox.Text.Trim()
        GitHubToken      = $ghToken
        GitHubRepo       = $ghRepo
        SupabaseUrl      = $supabaseUrl
        SupabaseKey      = $supabaseKey
        UserProfile      = $script:UserProfileBox.Text.Trim()
        MinAiScore       = [int]$script:MinAiScoreBox.Value
        OllamaUrl        = $script:OllamaUrlBox.Text.Trim()
        AutoEnrich       = $script:AutoEnrichCheckBox.Checked
        SearchGmail      = $script:GmailCheckBox.Checked
        GmailEmail       = $script:GmailEmailBox.Text.Trim()
        GmailPassword    = $script:GmailPasswordBox.Text.Trim()
    }

    $settings | ConvertTo-Json | Set-Content -LiteralPath $script:SettingsPath -Encoding UTF8
}

$script:SettingsSaveTimer        = $null
$script:EnrichTimer              = $null
$script:EnrichJob                = $null
$script:CvAnalyzeTimer           = $null
$script:CvAnalyzeJob             = $null
$script:AutoEnrichLastRunId      = 0   # last GH Actions run id that triggered auto-enrich

function Sync-SettingsToSupabase {
    # Push all GUI settings to Supabase bot_state so the cloud worker respects them.
    $settings = Load-Settings
    $sUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
    $sKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) {
        return  # Supabase not configured — skip silently
    }

    $maxHours = switch ($script:TimeFilterBox.Text) {
        "Last 1 hour"   { "1" }
        "Last 2 hours"  { "2" }
        "Last 24 hours" { "24" }
        "Last week"     { "168" }
        "Last month"    { "720" }
        "Custom"        { [string]$script:CustomHoursBox.Value }
        default         { "24" }
    }
    $keywords = ($script:KeywordsBox.Lines | Where-Object { $_ -ne "" }) -join ","

    # SECURITY: credentials (LinkedIn cookie, Telegram token/chat id, Gmail
    # email/app password) are deliberately NOT synced. bot_state is readable
    # with the public anon key that ships in the mobile app, so anything
    # written here is world-readable. Cloud workers read secrets from
    # GitHub Actions Secrets; local workers read settings.json.
    $pairs = @(
        [ordered]@{ key = "setting_keywords";           value = $keywords }
        [ordered]@{ key = "setting_location";           value = $script:CountryBox.Text.Trim() }
        [ordered]@{ key = "setting_max_hours";          value = $maxHours }
        [ordered]@{ key = "setting_search_linkedin";    value = if ($script:LinkedInCheckBox.Checked) { "true" } else { "false" } }
        [ordered]@{ key = "setting_search_indeed";      value = if ($script:IndeedCheckBox.Checked) { "true" } else { "false" } }
        [ordered]@{ key = "setting_exclude_keywords";   value = $script:ExcludeBox.Text.Trim() }
        [ordered]@{ key = "setting_search_gmail";       value = if ($script:GmailCheckBox.Checked) { "true" } else { "false" } }
    )

    $headers = @{
        "apikey"        = $sKey
        "Authorization" = "Bearer $sKey"
        "Content-Type"  = "application/json"
        "Prefer"        = "resolution=merge-duplicates"
    }
    $body = $pairs | ConvertTo-Json
    $uri  = "$sUrl/rest/v1/bot_state"
    Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ErrorAction Stop | Out-Null
}

function Save-Settings-WithFeedback {
    try {
        Save-Settings
        try {
            Sync-SettingsToSupabase
        } catch {
            Add-LogLine "Warning: could not sync settings to cloud: $($_.Exception.Message)"
        }
        Add-LogLine "Settings saved."
        $script:StatusLabel.Text      = "Settings saved [OK]"
        $script:StatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 140, 0)
        if ($null -ne $script:SettingsSaveTimer) {
            $script:SettingsSaveTimer.Stop()
            $script:SettingsSaveTimer.Dispose()
        }
        $script:SettingsSaveTimer          = New-Object System.Windows.Forms.Timer
        $script:SettingsSaveTimer.Interval = 3000
        $script:SettingsSaveTimer.Add_Tick({
            if ($script:ScanRunning) {
                $script:StatusLabel.Text = "Status: monitoring"
            } else {
                $script:StatusLabel.Text = "Status: ready"
            }
            $script:StatusLabel.ForeColor = [System.Drawing.Color]::Black
            $script:SettingsSaveTimer.Stop()
        })
        $script:SettingsSaveTimer.Start()
    } catch {
        Add-LogLine "Settings save failed: $($_.Exception.Message)"
    }
}

function Initialize-Sqlite {
    if ($script:SqliteLoaded) {
        return
    }

    $candidatePaths = @(
        (Join-Path $script:AppRoot "System.Data.SQLite.dll"),
        "C:\Program Files\Google\Play Games\current\service\System.Data.SQLite.dll",
        "C:\Program Files\Google\Play Games\26.4.613.1\service\System.Data.SQLite.dll",
        "C:\Program Files\Dell\SupportAssistAgent\CDM\System.Data.SQLite.dll"
    )

    foreach ($path in $candidatePaths) {
        if (Test-Path -LiteralPath $path) {
            Add-Type -Path $path
            $script:SqliteLoaded = $true
            return
        }
    }

    throw "Could not load a SQLite provider for browser cookie import. Download System.Data.SQLite.dll from system.data.sqlite.org and place it in the app folder."
}

function Copy-FileUnlocked {
    param([string]$SourcePath)

    $tempPath = Join-Path $env:TEMP ("cookie-copy-" + [guid]::NewGuid().ToString() + ".db")
    $sourceStream = $null
    try {
        $sourceStream = [System.IO.File]::Open($SourcePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete)
    }
    catch {
        throw "Could not access browser cookie database. Close the browser and try again."
    }
    try {
        $targetStream = [System.IO.File]::Open($tempPath, [System.IO.FileMode]::Create, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
        try {
            $sourceStream.CopyTo($targetStream)
        }
        finally {
            $targetStream.Dispose()
        }
    }
    finally {
        $sourceStream.Dispose()
    }

    return $tempPath
}

function Get-ChromiumMasterKey {
    param([string]$UserDataRoot)

    $localStatePath = Join-Path $UserDataRoot "Local State"
    if (-not (Test-Path -LiteralPath $localStatePath)) {
        throw "Local State was not found at $localStatePath"
    }

    $localState = Get-Content -LiteralPath $localStatePath -Raw | ConvertFrom-Json

    $encKeyB64 = [string]$localState.os_crypt.encrypted_key
    if ([string]::IsNullOrWhiteSpace($encKeyB64)) {
        throw "Browser master key not found in Local State (os_crypt.encrypted_key is empty). The browser may use a newer encryption scheme."
    }

    $encryptedKey = [Convert]::FromBase64String($encKeyB64)

    # First 5 bytes are the ASCII string "DPAPI"; strip them before calling Unprotect
    if ($encryptedKey.Length -lt 6) {
        throw "Encrypted key in Local State is too short to be valid."
    }
    $keyBytes = $encryptedKey[5..($encryptedKey.Length - 1)]

    try {
        return [System.Security.Cryptography.ProtectedData]::Unprotect($keyBytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
    }
    catch {
        throw "Could not decrypt browser master key with DPAPI: $($_.Exception.Message). Try running the app as the same Windows user who owns the browser profile."
    }
}

function Unprotect-ChromiumCookieValue {
    param(
        [byte[]]$EncryptedBytes,
        [byte[]]$MasterKey
    )

    if (-not $EncryptedBytes -or $EncryptedBytes.Length -eq 0) {
        return ""
    }

    $prefix = [System.Text.Encoding]::ASCII.GetString($EncryptedBytes, 0, [Math]::Min(3, $EncryptedBytes.Length))
    if ($prefix -eq "v10" -or $prefix -eq "v11") {
        $nonce        = $EncryptedBytes[3..14]
        $cipherAndTag = $EncryptedBytes[15..($EncryptedBytes.Length - 1)]
        $cipherText   = $cipherAndTag[0..($cipherAndTag.Length - 17)]
        $tag          = $cipherAndTag[($cipherAndTag.Length - 16)..($cipherAndTag.Length - 1)]
        $plainBytes   = New-Object byte[] ($cipherText.Length)
        $aes = [System.Security.Cryptography.AesGcm]::new($MasterKey)
        try {
            $aes.Decrypt($nonce, $cipherText, $tag, $plainBytes, $null)
        }
        finally {
            $aes.Dispose()
        }
        return [System.Text.Encoding]::UTF8.GetString($plainBytes)
    }

    # v20 = Chrome 127+ App-Bound Encryption - requires Chrome's elevation service; skip silently
    if ($prefix -eq "v20") {
        return ""
    }

    # Legacy DPAPI-encrypted cookie value
    try {
        $decrypted = [System.Security.Cryptography.ProtectedData]::Unprotect($EncryptedBytes, $null, [System.Security.Cryptography.DataProtectionScope]::CurrentUser)
        return [System.Text.Encoding]::UTF8.GetString($decrypted)
    }
    catch {
        return ""
    }
}

function Get-ChromiumProfiles {
    param([string]$UserDataRoot)

    if (-not (Test-Path -LiteralPath $UserDataRoot)) {
        return @()
    }

    return Get-ChildItem -LiteralPath $UserDataRoot -Directory |
        Where-Object { $_.Name -eq "Default" -or $_.Name -like "Profile *" }
}

function Get-BrowserUserDataRoot {
    param([string]$BrowserName)

    switch ($BrowserName) {
        "Chrome (Chromium)" { return Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data" }
        "Chrome"            { return Join-Path $env:LOCALAPPDATA "Google\Chrome\User Data" }
        "Chromium"          { return Join-Path $env:LOCALAPPDATA "Chromium\User Data" }
        default             { return Join-Path $env:LOCALAPPDATA "Microsoft\Edge\User Data" }
    }
}

function Import-LinkedInCookiesFromBrowser {
    param([string]$BrowserName)

    Initialize-Sqlite

    $userDataRoot = Get-BrowserUserDataRoot -BrowserName $BrowserName

    if (-not (Test-Path -LiteralPath $userDataRoot)) {
        throw "$BrowserName user data folder was not found."
    }

    $masterKey                   = Get-ChromiumMasterKey -UserDataRoot $userDataRoot
    $bestCookieHeader            = ""
    $bestProfileName             = ""
    $bestCookieCount             = 0
    $profilesScanned             = 0
    $profilesWithLinkedInCookies = 0
    $profilesWithLiAt            = 0
    $totalRawCookiesInDb         = 0
    $totalV20Skipped             = 0

    foreach ($profile in Get-ChromiumProfiles -UserDataRoot $userDataRoot) {
        $profilesScanned += 1
        $cookieDbPath = Join-Path $profile.FullName "Network\Cookies"
        if (-not (Test-Path -LiteralPath $cookieDbPath)) {
            continue
        }

        try {
            $tempDbPath = Copy-FileUnlocked -SourcePath $cookieDbPath
        }
        catch {
            continue
        }
        try {
            $connection = New-Object System.Data.SQLite.SQLiteConnection("Data Source=$tempDbPath;Version=3;Read Only=True;")
            try {
                $connection.Open()
                $command = $connection.CreateCommand()
                $command.CommandText = @"
select name, value, encrypted_value
from cookies
where host_key like '%linkedin.com%'
order by host_key, name
"@
                $reader    = $command.ExecuteReader()
                $cookieMap = [ordered]@{}
                while ($reader.Read()) {
                    $name       = [string]$reader["name"]
                    $plainValue = [string]$reader["value"]
                    if ([string]::IsNullOrWhiteSpace($plainValue)) {
                        $encryptedValue = [byte[]]$reader["encrypted_value"]
                        $totalRawCookiesInDb += 1
                        # Detect v20 before attempting decryption so we can count skipped ones
                        $isV20 = ($encryptedValue.Length -ge 3 -and
                            [System.Text.Encoding]::ASCII.GetString($encryptedValue, 0, 3) -eq "v20")
                        if ($isV20) {
                            $totalV20Skipped += 1
                            $plainValue = ""
                        }
                        else {
                            try {
                                $plainValue = Unprotect-ChromiumCookieValue -EncryptedBytes $encryptedValue -MasterKey $masterKey
                            }
                            catch {
                                $plainValue = ""
                            }
                        }
                    }

                    if (-not [string]::IsNullOrWhiteSpace($name) -and -not [string]::IsNullOrWhiteSpace($plainValue)) {
                        $cookieMap[$name] = $plainValue
                    }
                }

                if ($reader) { $reader.Close() }

                if ($cookieMap.Count -gt 0) {
                    $profilesWithLinkedInCookies += 1
                }

                if ($cookieMap.Contains("li_at")) {
                    $profilesWithLiAt += 1
                }

                if ($cookieMap.Count -gt $bestCookieCount -and $cookieMap.Contains("li_at")) {
                    $bestCookieHeader = (($cookieMap.GetEnumerator() | ForEach-Object { "{0}={1}" -f $_.Key, $_.Value }) -join "; ")
                    $bestProfileName  = $profile.Name
                    $bestCookieCount  = $cookieMap.Count
                }
            }
            finally {
                $connection.Close()
                $connection.Dispose()
            }
        }
        finally {
            Remove-Item -LiteralPath $tempDbPath -Force -ErrorAction SilentlyContinue
        }
    }

    if ([string]::IsNullOrWhiteSpace($bestCookieHeader)) {
        if ($profilesScanned -eq 0) {
            throw "No $BrowserName browser profiles were found."
        }

        if ($totalV20Skipped -gt 0 -and $profilesWithLinkedInCookies -eq 0) {
            throw ("$BrowserName uses v20 App-Bound Encryption (Edge/Chrome 127+). " +
                   "Cookies cannot be read from outside the browser. " +
                   "Paste your li_at cookie manually: open LinkedIn in $BrowserName, press F12, " +
                   "go to Application > Cookies > www.linkedin.com, copy the li_at value, " +
                   "then paste it into the LinkedIn Cookie field.")
        }

        if ($profilesWithLinkedInCookies -eq 0) {
            throw "No LinkedIn cookies were found in $BrowserName. Open linkedin.com in that browser, sign in, then try Import Cookies again."
        }

        throw "LinkedIn cookies were found in $BrowserName, but no signed-in session cookie (li_at) was available. Make sure you are fully signed into LinkedIn in that browser profile and try again."
    }

    return [pscustomobject]@{
        Browser                     = $BrowserName
        ProfileName                 = $bestProfileName
        CookieCount                 = $bestCookieCount
        CookieHeader                = $bestCookieHeader
        ProfilesScanned             = $profilesScanned
        ProfilesWithLinkedInCookies = $profilesWithLinkedInCookies
        ProfilesWithLiAt            = $profilesWithLiAt
    }
}

function Add-LogLine {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $script:LogBox.AppendText("[$timestamp] $Message`r`n")
    $script:LogBox.SelectionStart = $script:LogBox.TextLength
    $script:LogBox.ScrollToCaret()
}

function Get-SettingsSummary {
    $s = Load-Settings
    if ($null -eq $s) { return "No settings file found." }
    $kw      = @(Get-SettingValue -SettingsObject $s -Name "Keywords"         -DefaultValue @()) | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
    $loc     = [string](Get-SettingValue -SettingsObject $s -Name "Location"         -DefaultValue "UAE")
    $intv    = [string](Get-SettingValue -SettingsObject $s -Name "IntervalMinutes"  -DefaultValue 5)
    $filt    = [string](Get-SettingValue -SettingsObject $s -Name "TimeFilter"       -DefaultValue "Last 24 hours")
    $hrs     = [string](Get-SettingValue -SettingsObject $s -Name "CustomHours"      -DefaultValue 24)
    $li      = [string](Get-SettingValue -SettingsObject $s -Name "SearchLinkedIn"   -DefaultValue $true)
    $ind     = [string](Get-SettingValue -SettingsObject $s -Name "SearchIndeed"     -DefaultValue $true)
    $hide    = [string](Get-SettingValue -SettingsObject $s -Name "HideAppliedJobs"  -DefaultValue $true)
    $lines   = @(
        "Current settings:",
        "Keywords    : $($kw -join ', ')",
        "Location    : $loc",
        "Interval    : $intv min",
        "Filter      : $filt",
        "Custom hrs  : $hrs",
        "LinkedIn    : $li",
        "Indeed      : $ind",
        "Hide applied: $hide"
    )
    return $lines -join "`n"
}

function Apply-TelegramSetting {
    param([string]$Field, [string]$Value)
    switch ($Field.ToLower()) {
        "keyword" {
            $kws = ($Value -split ",") | ForEach-Object { $_.Trim() } | Where-Object { $_ }
            $script:KeywordsBox.Lines = $kws
            Save-Settings
            return "Keywords set to: $($kws -join ', ')"
        }
        "location" {
            $script:CountryBox.Text = $Value.Trim()
            Save-Settings
            return "Location set to: $($Value.Trim())"
        }
        "interval" {
            $n = [Math]::Max(1, [Math]::Min(60, [int]$Value))
            $script:IntervalBox.Value = [decimal]$n
            if ($script:Timer.Enabled) { $script:Timer.Interval = $n * 60000 }
            Save-Settings
            return "Interval set to: $n min"
        }
        "filter" {
            $map = @{ "1h"="Last 1 hour"; "2h"="Last 2 hours"; "24h"="Last 24 hours"; "week"="Last week"; "month"="Last month"; "custom"="Custom" }
            $mapped = if ($map.ContainsKey($Value.ToLower())) { $map[$Value.ToLower()] } else { $Value }
            if ($script:TimeFilterBox.Items.Contains($mapped)) { $script:TimeFilterBox.SelectedItem = $mapped }
            Save-Settings
            return "Time filter set to: $mapped"
        }
        "hours" {
            $script:CustomHoursBox.Value = [decimal][Math]::Max(1, [int]$Value)
            Save-Settings
            return "Custom hours set to: $Value"
        }
        "linkedin" {
            $script:LinkedInCheckBox.Checked = ($Value.ToLower() -in @("on","true","yes","1"))
            Save-Settings
            return "LinkedIn search: $($script:LinkedInCheckBox.Checked)"
        }
        "indeed" {
            $script:IndeedCheckBox.Checked = ($Value.ToLower() -in @("on","true","yes","1"))
            Save-Settings
            return "Indeed search: $($script:IndeedCheckBox.Checked)"
        }
        "hide" {
            $script:HideAppliedCheckBox.Checked = ($Value.ToLower() -in @("on","true","yes","1"))
            Save-Settings
            return "Hide applied: $($script:HideAppliedCheckBox.Checked)"
        }
        "cookie" {
            $script:CookieBox.Text = $Value.Trim()
            Save-Settings
            return "Cookie updated."
        }
        default {
            return "Unknown field '$Field'. Fields: keyword, location, interval, filter, hours, linkedin, indeed, hide, cookie"
        }
    }
}

function Send-TgReply {
    param([string]$BotToken, [string]$ChatId, [string]$Message)
    $logCb = { param($m) Add-LogLine $m }
    $ok = Send-TelegramMessage -BotToken $BotToken -ChatId $ChatId -Message $Message -LogCallback $logCb
    if (-not $ok) { Add-LogLine "Telegram reply could not be delivered." }
}

function Invoke-TelegramCommandPoll {
    $botToken = $script:TelegramTokenBox.Text.Trim()
    $chatId   = $script:TelegramChatIdBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($botToken) -or [string]::IsNullOrWhiteSpace($chatId)) { return }

    foreach ($update in @(Get-TelegramUpdates -BotToken $botToken -Offset $script:TelegramOffset)) {
        $script:TelegramOffset = $update.update_id + 1
        if (-not $update.message -or [string]::IsNullOrWhiteSpace([string]$update.message.text)) { continue }
        $fromChat = [string]$update.message.chat.id
        if ($fromChat -ne $chatId) { continue }
        $rawText  = [string]$update.message.text
        $cmd      = Get-TelegramCommandText -Raw $rawText
        Add-LogLine "Telegram: $cmd"

        try {
            switch -Wildcard ($cmd) {
                "/scan*" {
                    if ($script:ScanRunning) {
                        Send-TgReply $botToken $chatId "A scan is already in progress. Please wait."
                    } else {
                        $script:TgCmdReplyToken  = $botToken
                        $script:TgCmdReplyChatId = $chatId
                        Send-TgReply $botToken $chatId "Scanning now - you will receive the result when done."
                        Invoke-JobScan
                    }
                }
                "/start*" {
                    $pidPath = Join-Path $script:AppRoot "worker.pid"
                    $alreadyRunning = $false
                    if (Test-Path -LiteralPath $pidPath) {
                        try {
                            $ePid = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
                            Get-Process -Id $ePid -ErrorAction Stop | Out-Null
                            $alreadyRunning = $true
                            Send-TgReply $botToken $chatId "Worker is already running (PID $ePid)."
                        } catch {}
                    }
                    if (-not $alreadyRunning) {
                        Start-Monitoring
                        if ($script:WorkerStartedPid -gt 0) {
                            Send-TgReply $botToken $chatId "Worker started (PID $($script:WorkerStartedPid)). Lamp should turn green."
                        } else {
                            Send-TgReply $botToken $chatId "Worker start failed. Check the activity log for details."
                        }
                    }
                }
                "/stop*" {
                    $pidPath = Join-Path $script:AppRoot "worker.pid"
                    $wasRunning = $false
                    if (Test-Path -LiteralPath $pidPath) {
                        try {
                            $ePid = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
                            Get-Process -Id $ePid -ErrorAction Stop | Out-Null
                            $wasRunning = $true
                        } catch {}
                    } elseif ($script:WorkerStartedPid -gt 0) {
                        try { Get-Process -Id $script:WorkerStartedPid -ErrorAction Stop | Out-Null; $wasRunning = $true } catch {}
                    }
                    Stop-Monitoring
                    if ($wasRunning) {
                        Send-TgReply $botToken $chatId "Worker stopped successfully."
                    } else {
                        Send-TgReply $botToken $chatId "Worker was not running."
                    }
                }
                "/jobs*" {
                    Send-VisibleJobsToTelegram
                }
                "/status*" {
                    $pidPath  = Join-Path $script:AppRoot "worker.pid"
                    $wRunning = $false; $wPidVal = 0
                    if (Test-Path -LiteralPath $pidPath) {
                        try { $wPidVal = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim()); Get-Process -Id $wPidVal -ErrorAction Stop | Out-Null; $wRunning = $true } catch {}
                    }
                    if (-not $wRunning -and $script:WorkerStartedPid -gt 0) {
                        try { Get-Process -Id $script:WorkerStartedPid -ErrorAction Stop | Out-Null; $wRunning = $true; $wPidVal = $script:WorkerStartedPid } catch {}
                    }
                    $wStatus  = if ($wRunning) { "Running (PID $wPidVal)" } else { "Stopped" }
                    $guiTimer = if ($script:Timer.Enabled) { "every $([int]$script:IntervalBox.Value) min" } else { "off" }
                    $reply    = "Worker  : $wStatus`nGUI scan: $guiTimer`nJobs    : $($script:JobsList.Items.Count) visible`nFilter  : $($script:ScanTimeFilterLabel)"
                    Send-TgReply $botToken $chatId $reply
                }
                "/get*" {
                    Send-TgReply $botToken $chatId (Get-SettingsSummary)
                }
                "/set*" {
                    $parts = $rawText.Trim() -split '\s+', 3
                    if ($parts.Count -lt 3) {
                        Send-TgReply $botToken $chatId "Usage: /set <field> <value>`nFields: keyword, location, interval, filter, hours, linkedin, indeed, hide, cookie"
                    } else {
                        $result = Apply-TelegramSetting -Field $parts[1] -Value $parts[2]
                        Send-TgReply $botToken $chatId $result
                    }
                }
                default {
                    $help = @(
                        "Commands:",
                        "/scan              - Scan now (replies when done)",
                        "/start             - Start worker",
                        "/stop              - Stop worker",
                        "/status            - Show running status",
                        "/jobs              - Recent job listings",
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
                    Send-TgReply $botToken $chatId $help
                }
            }
        }
        catch {
            $errMsg = "Error: $($_.Exception.Message)"
            Add-LogLine "Telegram command '$cmd' failed: $($_.Exception.Message)"
            try { Send-TgReply $botToken $chatId $errMsg } catch {}
        }
    }
    Save-TelegramOffset -Path $script:TelegramOffsetPath -Offset $script:TelegramOffset
}

function Update-CloudLamp {
    $settings = Load-Settings
    $token = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubToken" -DefaultValue "")
    $repo  = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubRepo"  -DefaultValue "")

    if (-not $repo) {
        $script:CloudLamp.Tag = "grey"
        $script:CloudLamp.Invalidate()
        $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud not configured (add GitHubRepo to settings.json)")
        return
    }

    try {
        $url = "https://api.github.com/repos/$repo/actions/workflows/job-alert.yml/runs?per_page=1"
        # A PUBLIC repo's run list is readable WITHOUT a token. Try the token first
        # (higher rate limit); fall back to an unauthenticated request if the token
        # is missing or revoked — so a dead token no longer greys out the lamp.
        $run = $null
        $tokenOptions = @()
        if ($token) { $tokenOptions += $true }
        $tokenOptions += $false
        foreach ($useToken in $tokenOptions) {
            $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $url)
            if ($useToken) { $req.Headers.Add("Authorization", "Bearer $token") }
            $req.Headers.Add("Accept", "application/vnd.github+json")
            $resp = $script:HttpClient.SendAsync($req).GetAwaiter().GetResult()
            if (-not $resp.IsSuccessStatusCode) { continue }   # 401 with a dead token -> try unauthenticated
            $body = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            $data = $body | ConvertFrom-Json
            $run  = $data.workflow_runs | Select-Object -First 1
            if ($run) { break }
        }

        if ($run) {
            $script:CloudLastRunId  = [long]$run.id
            $script:CloudWorkflowId = [long]$run.workflow_id
            $script:CloudLastRunUrl = [string]$run.html_url

            # Fetch workflow enabled/disabled state
            try {
                $wfUrl  = "https://api.github.com/repos/$repo/actions/workflows/$($script:CloudWorkflowId)"
                $wfReq  = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $wfUrl)
                $wfReq.Headers.Add("Authorization", "Bearer $token")
                $wfReq.Headers.Add("Accept", "application/vnd.github+json")
                $wfResp = $script:HttpClient.SendAsync($wfReq).GetAwaiter().GetResult()
                $wfData = ($wfResp.Content.ReadAsStringAsync().GetAwaiter().GetResult()) | ConvertFrom-Json
                $script:CloudScheduleActive = ($wfData.state -eq "active")
            } catch {}
        }

        if (-not $run) {
            $script:CloudLamp.Tag = "grey"
            $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud: no runs yet (right-click for controls)")
        } elseif ($run.status -in @("in_progress","queued","waiting")) {
            $script:CloudLamp.Tag = "yellow"
            $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud: running now ($($run.created_at)) - right-click to cancel")
        } elseif ($run.conclusion -eq "success") {
            $script:CloudLamp.Tag = "green"
            $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud: last run OK - $($run.created_at) - right-click for controls")
            # Auto AI score: trigger enricher when a new run completes and auto-enrich is on
            if ($script:AutoEnrichCheckBox.Checked -and
                [long]$run.id -ne $script:AutoEnrichLastRunId) {
                $script:AutoEnrichLastRunId = [long]$run.id
                Start-Enrichment -Silent $true
            }
        } else {
            $script:CloudLamp.Tag = "red"
            $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud: FAILED ($($run.conclusion)) - $($run.created_at) - right-click to retry")
        }

        # Update menu item states if menu already created
        if ($script:CloudMenuCancel) {
            $script:CloudMenuCancel.Enabled  = ($script:CloudLamp.Tag -eq "yellow")
            $script:CloudMenuSchedule.Text   = if ($script:CloudScheduleActive) { "Pause Schedule" } else { "Resume Schedule" }
        }
    } catch {
        $script:CloudLamp.Tag = "grey"
        $script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Cloud: check error - $($_.Exception.Message.Split([char]10)[0])")
    }
    $script:CloudLamp.Invalidate()
}

function Invoke-GitHubApi {
    param([string]$Method, [string]$Url, [string]$Body = "")
    $settings = Load-Settings
    $token    = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubToken" -DefaultValue "")
    $req = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::new($Method), $Url)
    $req.Headers.Add("Authorization", "Bearer $token")
    $req.Headers.Add("Accept", "application/vnd.github+json")
    if ($Body) {
        $req.Content = [System.Net.Http.StringContent]::new($Body, [System.Text.Encoding]::UTF8, "application/json")
    }
    $resp = $script:HttpClient.SendAsync($req).GetAwaiter().GetResult()
    return $resp.StatusCode
}

function Invoke-CloudRunNow {
    $settings = Load-Settings
    $repo = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubRepo" -DefaultValue "")
    if (-not $repo -or $script:CloudWorkflowId -eq 0) { Add-LogLine "Cloud: not configured (no GitHubRepo or workflow ID)"; return }
    $url    = "https://api.github.com/repos/$repo/actions/workflows/$($script:CloudWorkflowId)/dispatches"
    $status = Invoke-GitHubApi -Method "POST" -Url $url -Body '{"ref":"main"}'
    if ([int]$status -eq 204) {
        Add-LogLine "Cloud: scan triggered - lamp will turn yellow within ~30 sec."
        Start-Sleep -Milliseconds 4000
        Update-CloudLamp
    } else {
        Add-LogLine "Cloud: trigger failed (HTTP $([int]$status)). Is the schedule paused?"
    }
}

function Invoke-CloudCancel {
    $settings = Load-Settings
    $repo = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubRepo" -DefaultValue "")
    if (-not $repo -or $script:CloudLastRunId -eq 0) { Add-LogLine "Cloud: no run ID to cancel"; return }
    $url    = "https://api.github.com/repos/$repo/actions/runs/$($script:CloudLastRunId)/cancel"
    $status = Invoke-GitHubApi -Method "POST" -Url $url
    Add-LogLine "Cloud: cancel sent (HTTP $([int]$status))."
    Start-Sleep -Milliseconds 2000
    Update-CloudLamp
}

function Open-CloudLogs {
    if ($script:CloudLastRunUrl) {
        Start-Process $script:CloudLastRunUrl
    } else {
        $settings = Load-Settings
        $repo = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubRepo" -DefaultValue "")
        if ($repo) { Start-Process "https://github.com/$repo/actions" }
    }
}

function Toggle-CloudSchedule {
    $settings = Load-Settings
    $repo = [string](Get-SettingValue -SettingsObject $settings -Name "GitHubRepo" -DefaultValue "")
    if (-not $repo -or $script:CloudWorkflowId -eq 0) { Add-LogLine "Cloud: not configured"; return }
    $action = if ($script:CloudScheduleActive) { "disable" } else { "enable" }
    $url    = "https://api.github.com/repos/$repo/actions/workflows/$($script:CloudWorkflowId)/$action"
    $status = Invoke-GitHubApi -Method "PUT" -Url $url
    Add-LogLine "Cloud: schedule ${action}d (HTTP $([int]$status))."
    Start-Sleep -Milliseconds 1000
    Update-CloudLamp
}

function Update-WorkerLamp {
    $pidPath  = Join-Path $script:AppRoot "worker.pid"
    $running  = $false
    $pidValue = 0

    # Primary: PID file written by the worker itself
    if (Test-Path -LiteralPath $pidPath) {
        try {
            $pidValue = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
            $proc     = Get-Process -Id $pidValue -ErrorAction Stop
            $running  = ($null -ne $proc)
            if ($running) { $script:WorkerStartedPid = 0 }  # PID file took over
        } catch { $running = $false }
    }

    # Fallback: process we launched before it wrote its PID file
    if (-not $running -and $script:WorkerStartedPid -gt 0) {
        try {
            Get-Process -Id $script:WorkerStartedPid -ErrorAction Stop | Out-Null
            $running  = $true
            $pidValue = $script:WorkerStartedPid
        } catch {
            # Worker died before writing PID file - surface crash log if available
            $script:WorkerStartedPid = 0
            $crashLog = Join-Path $script:AppRoot "worker-crash.log"
            if (Test-Path -LiteralPath $crashLog) {
                try {
                    $msg = (Get-Content -LiteralPath $crashLog -Raw -ErrorAction Stop).Trim()
                    if (-not [string]::IsNullOrWhiteSpace($msg)) {
                        Add-LogLine "Worker crash output:"
                        foreach ($line in ($msg -split "`r?`n")) { Add-LogLine "  $line" }
                    }
                    Remove-Item -LiteralPath $crashLog -Force -ErrorAction SilentlyContinue
                } catch {}
            }
        }
    }

    $script:WorkerLamp.Tag = if ($running) { "green" } else { "red" }
    $script:WorkerLamp.Invalidate()
    $tip = if ($running) { "Worker running (PID $pidValue)" } else { "Worker not running. Press Start to begin." }
    $script:WorkerLampTooltip.SetToolTip($script:WorkerLamp, $tip)
}

function Get-TimeFilterHours {
    $selection = [string]$script:TimeFilterBox.Text

    switch ($selection) {
        "Last 1 hour"   { return 1 }
        "Last 2 hours"  { return 2 }
        "Last 24 hours" { return 24 }
        "Last week"     { return 24 * 7 }
        "Last month"    { return 24 * 30 }
        "Custom"        { return [int]$script:CustomHoursBox.Value }
        default         { return 24 }
    }
}

function Get-TimeFilterLabel {
    $selection = [string]$script:TimeFilterBox.Text
    if ($selection -eq "Custom") {
        return "Last $([int]$script:CustomHoursBox.Value) hour(s)"
    }

    return $selection
}

function Validate-CustomHours {
    if ([string]$script:TimeFilterBox.Text -ne "Custom") {
        return $true
    }

    $hours = [int]$script:CustomHoursBox.Value
    if ($hours -lt 1 -or $hours -gt 8760) {
        Add-LogLine "Custom hours must be between 1 and 8760."
        $script:StatusLabel.Text = "Status: invalid custom time range"
        return $false
    }

    return $true
}

function Matches-TimeFilter {
    param($Job)

    $maxHours    = Get-TimeFilterHours
    $jobAgeHours = Get-PostedAgeHours -Job $Job
    return $jobAgeHours -le $maxHours
}

function Update-TimeFilterUI {
    $isCustom = ([string]$script:TimeFilterBox.Text -eq "Custom")
    $script:CustomHoursLabel.Visible = $isCustom
    $script:CustomHoursBox.Visible   = $isCustom
}

function Clear-JobList {
    $script:JobsList.Items.Clear()
    $script:DisplayedJobsByUrl = @{}
}

function Update-ScoresFromSupabase {
    $settings    = Load-Settings
    $sUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
    $sKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) { return }
    try {
        $headers = @{ "apikey" = $sKey; "Authorization" = "Bearer $sKey" }
        # Fetch scores
        $uri      = "$sUrl/rest/v1/jobs?select=url,llm_score&llm_score=not.is.null&limit=500"
        $rows     = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get -ErrorAction Stop
        $scoreMap = @{}
        foreach ($row in $rows) { $scoreMap[$row.url] = [string]$row.llm_score }
        # Fetch Telegram sent (cloud worker)
        $tgUri  = "$sUrl/rest/v1/jobs?select=url,telegram_sent_at&telegram_sent_at=not.is.null&limit=500"
        $tgRows = Invoke-RestMethod -Uri $tgUri -Headers $headers -Method Get -ErrorAction Stop
        $tgMap  = @{}
        foreach ($row in $tgRows) { $tgMap[$row.url] = $true }
        $updated = 0
        foreach ($item in $script:JobsList.Items) {
            $url = [string]$item.Tag
            if ($item.SubItems.Count -ge 9) {
                if ($scoreMap.ContainsKey($url)) {
                    $item.SubItems[8].Text = $scoreMap[$url]
                    $updated++
                }
                if ($tgMap.ContainsKey($url)) {
                    $cur = $item.SubItems[7].Text
                    $item.SubItems[7].Text = if ($cur -eq "GUI") { "Both" } else { "Cloud" }
                }
            }
        }
        if ($updated -gt 0) { Add-LogLine "Scores refreshed: $updated job(s) updated from Supabase." }
    } catch {
        Add-LogLine "Score refresh error: $($_.Exception.Message)"
    }
}

function Refresh-ResultsForCurrentFilter {
    if (-not (Validate-CustomHours)) {
        return
    }

    if ($script:Timer.Enabled) {
        try {
            Clear-JobList
            Invoke-JobScan
        }
        catch {
            $script:StatusLabel.Text = "Status: error"
            Add-LogLine "Refresh failed: $($_.Exception.Message)"
        }
    }
}

function Apply-JobRowStyle {
    param(
        [System.Windows.Forms.ListViewItem]$Item,
        $Job
    )

    $hours = Get-PostedAgeHours -Job $Job
    $item.UseItemStyleForSubItems = $true
    $item.ForeColor = [System.Drawing.Color]::Black

    if ($hours -le 3) {
        $item.BackColor = [System.Drawing.Color]::FromArgb(198, 239, 206)
    }
    elseif ($hours -le 24) {
        $item.BackColor = [System.Drawing.Color]::FromArgb(255, 235, 156)
    }
    else {
        $item.BackColor = [System.Drawing.Color]::White
    }
}

function Add-RecentJobToList {
    param($Job)

    $existing = $script:JobsList.Items | Where-Object { $_.Tag -eq $Job.Url } | Select-Object -First 1
    if ($existing) {
        return
    }

    $source = if ($Job.PSObject.Properties["Source"] -and -not [string]::IsNullOrWhiteSpace([string]$Job.Source)) { [string]$Job.Source } else { "LinkedIn" }
    $item = New-Object System.Windows.Forms.ListViewItem($source)
    [void]$item.SubItems.Add($Job.Keyword)
    [void]$item.SubItems.Add($Job.Title)
    [void]$item.SubItems.Add($Job.Company)
    [void]$item.SubItems.Add($Job.Location)
    [void]$item.SubItems.Add($(if ([string]::IsNullOrWhiteSpace($Job.PostedText)) { "-" } else { $Job.PostedText }))
    [void]$item.SubItems.Add($(if ($Job.IsApplied) { "Yes" } else { "No" }))
    [void]$item.SubItems.Add("")   # Tg — filled in by Update-ScoresFromSupabase or after GUI send
    $score = if ($Job.PSObject.Properties["llm_score"] -and $null -ne $Job.llm_score) { [string]$Job.llm_score } else { "" }
    [void]$item.SubItems.Add($score)
    $item.Tag = $Job.Url
    $script:DisplayedJobsByUrl[$Job.Url] = $Job
    Apply-JobRowStyle -Item $item -Job $Job

    [void]$script:JobsList.Items.Insert(0, $item)

    while ($script:JobsList.Items.Count -gt 100) {
        $script:JobsList.Items.RemoveAt($script:JobsList.Items.Count - 1)
    }
}

function Show-JobNotification {
    param($Job)

    $source = if ($Job.PSObject.Properties["Source"] -and -not [string]::IsNullOrWhiteSpace([string]$Job.Source)) { [string]$Job.Source } else { "LinkedIn" }
    $script:LastNotificationUrl          = $Job.Url
    $script:NotifyIcon.BalloonTipTitle   = "New $source job"
    $script:NotifyIcon.BalloonTipText    = "{0}`n{1} | {2}" -f $Job.Title, $Job.Company, $Job.Location
    $script:NotifyIcon.ShowBalloonTip(10000)
}

function Test-JobExcluded {
    param($Job)
    $raw = [string](Get-SettingValue -SettingsObject (Load-Settings) -Name "ExcludeKeywords" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($raw)) { return $false }
    $terms = @($raw -split '[,\r\n]+' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($terms.Count -eq 0) { return $false }
    $haystack = "$($Job.Title) $($Job.Company)".ToLowerInvariant()
    foreach ($term in $terms) {
        if ($haystack.Contains($term.ToLowerInvariant())) { return $true }
    }
    return $false
}

function Set-JobStatusInList {
    param([System.Windows.Forms.ListViewItem]$Item, [string]$Status)
    $url = [string]$Item.Tag
    if ([string]::IsNullOrWhiteSpace($url)) { return }
    if ($Status -eq "dismissed") {
        $Item.ForeColor = [System.Drawing.Color]::FromArgb(180, 180, 180)
    } elseif ($Status -eq "applied") {
        $Item.SubItems[6].Text = "Yes"
        $Item.ForeColor = [System.Drawing.Color]::FromArgb(100, 160, 100)
    } elseif ($Status -eq "saved") {
        $Item.ForeColor = [System.Drawing.Color]::FromArgb(0, 120, 215)
    }
    try {
        $conn = Open-JobDatabaseConnection
        try {
            $cmd = $conn.CreateCommand()
            $cmd.CommandText = "update jobs set status = @s where url = @u"
            [void]$cmd.Parameters.AddWithValue("@s", $Status)
            [void]$cmd.Parameters.AddWithValue("@u", (Get-CanonicalJobUrl -Url $url))
            [void]$cmd.ExecuteNonQuery()
            $cmd.Dispose()
        } finally { $conn.Dispose() }
    } catch {}
}

function Export-JobsToCSV {
    $saveDialog = New-Object System.Windows.Forms.SaveFileDialog
    $saveDialog.Filter   = "CSV files (*.csv)|*.csv"
    $saveDialog.FileName = "jobs-export-$(Get-Date -Format 'yyyy-MM-dd').csv"
    if ($saveDialog.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { return }

    $rows = @()
    foreach ($item in $script:JobsList.Items) {
        $rows += [pscustomobject]@{
            Source   = $item.SubItems[0].Text
            Keyword  = $item.SubItems[1].Text
            Title    = $item.SubItems[2].Text
            Company  = $item.SubItems[3].Text
            Location = $item.SubItems[4].Text
            Posted   = $item.SubItems[5].Text
            Applied  = $item.SubItems[6].Text
            URL      = [string]$item.Tag
        }
    }
    if ($rows.Count -eq 0) { Add-LogLine "No jobs to export."; return }
    $rows | Export-Csv -LiteralPath $saveDialog.FileName -NoTypeInformation -Encoding UTF8
    Add-LogLine "Exported $($rows.Count) job(s) to $($saveDialog.FileName)"
}

function Open-SelectedJob {
    $selected = $script:JobsList.SelectedItems | Select-Object -First 1
    if (-not $selected) {
        return
    }

    Start-Process $selected.Tag
}

function Send-VisibleJobsToTelegram {
    $telegramBotToken = $script:TelegramTokenBox.Text.Trim()
    $telegramChatId   = $script:TelegramChatIdBox.Text.Trim()

    if ([string]::IsNullOrWhiteSpace($telegramBotToken) -or [string]::IsNullOrWhiteSpace($telegramChatId)) {
        Add-LogLine "Telegram bot token or chat ID is missing."
        return
    }

    $jobsToSend = @()
    foreach ($item in $script:JobsList.Items) {
        $jobUrl = [string]$item.Tag
        if (-not [string]::IsNullOrWhiteSpace($jobUrl) -and $script:DisplayedJobsByUrl.ContainsKey($jobUrl)) {
            $jobsToSend += $script:DisplayedJobsByUrl[$jobUrl]
        }
    }

    if ($jobsToSend.Count -eq 0) {
        $jobsToSend = @($script:LastScanJobs)
    }

    if ($jobsToSend.Count -eq 0) {
        Add-LogLine "No visible jobs are available to send right now."
        return
    }

    $logCb     = { param($m) Add-LogLine $m }
    $sentCount = 0
    foreach ($job in $jobsToSend | Select-Object -First 20) {
        $sent = Send-TelegramMessage -BotToken $telegramBotToken -ChatId $telegramChatId -Message (Format-TelegramMessage -Job $job) -LogCallback $logCb
        if ($sent) {
            $sentCount += 1
        }
    }

    Add-LogLine "Sent $sentCount visible job(s) to Telegram."
}

function Has-TelegramConfig {
    return (-not [string]::IsNullOrWhiteSpace($script:TelegramTokenBox.Text.Trim()) -and -not [string]::IsNullOrWhiteSpace($script:TelegramChatIdBox.Text.Trim()))
}

$script:ScanRunning          = $false
$script:ScanState            = $null
$script:ScanPS               = $null
$script:ScanPollTimer        = $null
$script:ScanTimeFilterLabel  = ""
$script:ScanTelegramToken    = ""
$script:ScanTelegramChatId   = ""
$script:TelegramOffsetPath   = Join-Path $script:AppRoot "telegram-offset.json"
$script:TelegramOffset       = Read-TelegramOffset -Path $script:TelegramOffsetPath

function Invoke-JobScan {
    if ($script:ScanRunning) {
        Add-LogLine "Scan already in progress, please wait..."
        return
    }

    # ── Read all UI values immediately on the UI thread ──────────────────
    $keywords = @($script:KeywordsBox.Lines |
        ForEach-Object { $_.Trim() } |
        Where-Object   { -not [string]::IsNullOrWhiteSpace($_) } |
        Select-Object  -Unique)

    $location         = $script:CountryBox.Text.Trim()
    $cookieHeader     = $script:CookieBox.Text.Trim()
    $hideApplied      = $script:HideAppliedCheckBox.Checked
    $telegramBotToken = $script:TelegramTokenBox.Text.Trim()
    $telegramChatId   = $script:TelegramChatIdBox.Text.Trim()
    $timeFilterLabel  = Get-TimeFilterLabel
    $maxHours         = Get-TimeFilterHours
    $seenJobIds       = [string[]]@($script:SeenJobs.Keys)
    $appRoot          = $script:AppRoot
    $searchLinkedIn   = $script:LinkedInCheckBox.Checked
    $searchIndeed     = $script:IndeedCheckBox.Checked
    $excludeKeywords  = [string](Get-SettingValue -SettingsObject (Load-Settings) -Name "ExcludeKeywords" -DefaultValue "")

    if ($keywords.Count -eq 0) {
        Add-LogLine "Add at least one job keyword before starting."
        return
    }
    if ([string]::IsNullOrWhiteSpace($location)) {
        Add-LogLine "Country/location cannot be empty."
        return
    }
    if (-not $searchLinkedIn -and -not $searchIndeed) {
        Add-LogLine "Select at least one source (LinkedIn or Indeed)."
        return
    }
    if (-not (Validate-CustomHours)) { return }

    Save-Settings

    $script:StatusLabel.Text = "Status: checking LinkedIn & Indeed ($timeFilterLabel)..."
    $script:Form.Refresh()
    Clear-JobList
    $script:ScanRunning = $true

    # ── Synchronized state shared between runspaces ───────────────────────
    $syncState = [hashtable]::Synchronized(@{
        LogQueue    = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()
        VisibleJobs = $null
        NewJobIds   = $null
        Done        = $false
        Error       = $null
    })
    $script:ScanState = $syncState

    # ── Script that runs in the background runspace ───────────────────────
    $scanScript = {
        param(
            [hashtable]$state,
            [string]   $appRoot,
            [string[]] $keywords,
            [string]   $location,
            [string]   $cookieHeader,
            [bool]     $hideApplied,
            [int]      $maxHours,
            [string[]] $seenJobIds,
            [bool]     $searchLinkedIn,
            [bool]     $searchIndeed,
            [string]   $excludeKeywords
        )
        try {
            Add-Type -AssemblyName System.Web
            Add-Type -AssemblyName System.Net.Http

            $sqliteCandidates = @(
                "C:\Program Files\Google\Play Games\current\service\System.Data.SQLite.dll",
                "C:\Program Files\Google\Play Games\26.4.613.1\service\System.Data.SQLite.dll",
                "C:\Program Files\Dell\SupportAssistAgent\CDM\System.Data.SQLite.dll"
            )
            foreach ($dll in $sqliteCandidates) {
                if (Test-Path -LiteralPath $dll) {
                    Add-Type -Path $dll -ErrorAction SilentlyContinue
                    $script:JobDatabaseSqliteLoaded = $true
                    break
                }
            }

            $script:AppRoot    = $appRoot
            $script:HttpClient = [System.Net.Http.HttpClient]::new()
            $script:HttpClient.Timeout = [TimeSpan]::FromSeconds(25)
            $script:HttpClient.DefaultRequestHeaders.UserAgent.ParseAdd(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
            $script:LogFunction = { param($m) $state.LogQueue.Enqueue($m) }

            . (Join-Path $appRoot "job-database.ps1")
            . (Join-Path $appRoot "shared-functions.ps1")

            Initialize-JobDatabase

            $seenSet    = [System.Collections.Generic.HashSet[string]]::new(
                            [string[]]$seenJobIds,
                            [System.StringComparer]::OrdinalIgnoreCase)
            $allVisible = [System.Collections.Generic.List[object]]::new()
            $newIds     = [System.Collections.Generic.List[string]]::new()

            # Multiple locations: $location may be comma-separated (e.g.
            # "United Arab Emirates, Egypt"). Scan every location x keyword.
            $locations = @($location -split ',' | ForEach-Object { $_.Trim() } |
                Where-Object { $_ })
            if ($locations.Count -eq 0) { $locations = @($location) }

            $scanIndex = 0
            foreach ($loc in $locations) {
            foreach ($keyword in $keywords) {
                if ($scanIndex -gt 0) {
                    $jitter = [Math]::Min(3000 + ($scanIndex * 500), 8000)
                    Start-Sleep -Milliseconds $jitter
                }
                $scanIndex++
                $liJobs     = @()
                $indeedJobs = @()

                if ($searchLinkedIn) {
                    $state.LogQueue.Enqueue("Checking LinkedIn '$keyword'...")
                    $liJobs = @(Get-LinkedInJobs -Keyword $keyword -Location $loc `
                                -CookieHeader $cookieHeader -HideAppliedJobs:$hideApplied `
                                -MaxHours $maxHours)
                    $dbSync = Sync-JobsToDatabase -Jobs $liJobs -Source "LinkedIn"
                    $state.LogQueue.Enqueue("LinkedIn '$keyword': +$($dbSync.inserted) new, $($dbSync.seen) known.")
                }

                if ($searchIndeed) {
                    $state.LogQueue.Enqueue("Checking Indeed '$keyword'...")
                    $indeedJobs = @(Get-IndeedJobs -Keyword $keyword -Location $loc -MaxHours $maxHours)
                    $dbSyncI    = Sync-JobsToDatabase -Jobs $indeedJobs -Source "Indeed"
                    $state.LogQueue.Enqueue("Indeed '$keyword': +$($dbSyncI.inserted) new, $($dbSyncI.seen) known.")
                }

                $excludeTerms = @($excludeKeywords -split '[,\r\n]+' |
                    ForEach-Object { $_.Trim() } | Where-Object { $_ })

                foreach ($job in (@($liJobs) + @($indeedJobs))) {
                    $haystack = "$($job.Title) $($job.Company)".ToLowerInvariant()
                    $excluded = $false
                    foreach ($term in $excludeTerms) {
                        if ($haystack.Contains($term.ToLowerInvariant())) { $excluded = $true; break }
                    }
                    if ((Get-PostedAgeHours -Job $job) -le $maxHours -and -not $excluded) {
                        $allVisible.Add($job)
                        if (-not $seenSet.Contains($job.Id)) { $newIds.Add($job.Id) }
                    }
                }
            }
            }   # end foreach location

            $deduped = @($allVisible | Group-Object Id | ForEach-Object { $_.Group[0] })
            $sorted  = @($deduped | Sort-Object `
                @{ Expression = { Get-PostedAgeHours -Job $_ }; Ascending = $true }, `
                @{ Expression = { $_.Title }; Ascending = $true })

            $state.VisibleJobs = $sorted
            $state.NewJobIds   = [string[]]@($newIds | Select-Object -Unique)
            $state.Done        = $true
        }
        catch {
            $state.Error = $_.Exception.Message
            $state.Done  = $true
        }
        finally {
            if ($script:HttpClient) { $script:HttpClient.Dispose() }
        }
    }

    # ── Launch background runspace ────────────────────────────────────────
    $runspace = [runspacefactory]::CreateRunspace(
        [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault())
    $runspace.Open()

    $ps = [powershell]::Create()
    $ps.Runspace = $runspace
    [void]$ps.AddScript($scanScript)
    [void]$ps.AddArgument($syncState)
    [void]$ps.AddArgument($appRoot)
    [void]$ps.AddArgument([string[]]$keywords)
    [void]$ps.AddArgument($location)
    [void]$ps.AddArgument($cookieHeader)
    [void]$ps.AddArgument([bool]$hideApplied)
    [void]$ps.AddArgument([int]$maxHours)
    [void]$ps.AddArgument([string[]]$seenJobIds)
    [void]$ps.AddArgument([bool]$searchLinkedIn)
    [void]$ps.AddArgument([bool]$searchIndeed)
    [void]$ps.AddArgument([string]$excludeKeywords)

    $script:ScanPS              = $ps
    $script:ScanHandle          = $ps.BeginInvoke()
    $script:ScanTimeFilterLabel = $timeFilterLabel
    $script:ScanTelegramToken   = $telegramBotToken
    $script:ScanTelegramChatId  = $telegramChatId

    # ── Polling timer - fires on the UI thread every 250 ms ───────────────
    $script:ScanPollTimer = New-Object System.Windows.Forms.Timer
    $script:ScanPollTimer.Interval = 250
    $script:ScanPollTimer.Add_Tick({
        try {
            # Drain log messages produced by the background runspace
            $msg = $null
            while ($script:ScanState.LogQueue.TryDequeue([ref]$msg)) {
                Add-LogLine $msg
            }

            if (-not $script:ScanState.Done) { return }

            # Scan finished - stop polling and clean up
            $script:ScanPollTimer.Stop()
            $script:ScanPollTimer.Dispose()
            $script:ScanRunning = $false
            try { $script:ScanPS.Dispose()           } catch {}
            try { $script:ScanPS.Runspace.Dispose()  } catch {}

            if ($script:ScanState.Error) {
                Add-LogLine "Scan error: $($script:ScanState.Error)"
                $script:StatusLabel.Text = "Status: scan error"
                if (-not [string]::IsNullOrWhiteSpace($script:TgCmdReplyToken)) {
                    try { Send-TgReply $script:TgCmdReplyToken $script:TgCmdReplyChatId "Scan failed: $($script:ScanState.Error)" } catch {}
                    $script:TgCmdReplyToken = ""; $script:TgCmdReplyChatId = ""
                }
                return
            }

            # ── Apply results on the UI thread ────────────────────────────
            $visibleJobs = @($script:ScanState.VisibleJobs)
            $newJobIds   = @($script:ScanState.NewJobIds)
            $newJobs     = @($visibleJobs | Where-Object { $newJobIds -contains $_.Id })

            Clear-JobList
            foreach ($job in $visibleJobs) { Add-RecentJobToList -Job $job }
            $script:LastScanJobs = $visibleJobs
            try { Update-ScoresFromSupabase } catch {}

            if (-not $script:HasPrimedState) {
                foreach ($job in $newJobs) {
                    $script:SeenJobs[$job.Id] = (Get-Date).ToString("o")
                }
                Save-SeenJobs
                $script:HasPrimedState = $true
                if ($visibleJobs.Count -eq 0) { Add-LogLine "No jobs found for $($script:ScanTimeFilterLabel)." }
                Add-LogLine "Initial sync complete. Seeded $($newJobs.Count) existing jobs without notifying."
                if (Has-TelegramConfig) {
                    Add-LogLine "Sending the current visible jobs to Telegram for the first sync."
                    Send-VisibleJobsToTelegram
                } else {
                    Add-LogLine "Telegram alerts are sent only for newly detected jobs."
                }
                $script:StatusLabel.Text = "Status: monitoring"
                if (-not [string]::IsNullOrWhiteSpace($script:TgCmdReplyToken)) {
                    try { Send-TgReply $script:TgCmdReplyToken $script:TgCmdReplyChatId "Initial sync done. Seeded $($visibleJobs.Count) job(s) - no alerts sent for existing listings." } catch {}
                    $script:TgCmdReplyToken = ""; $script:TgCmdReplyChatId = ""
                }
                return
            }

            $tgScanSummary = ""
            if ($visibleJobs.Count -eq 0) {
                Add-LogLine "No jobs found for $($script:ScanTimeFilterLabel)."
                $tgScanSummary = "Scan done. No jobs found for $($script:ScanTimeFilterLabel)."
            } elseif ($newJobs.Count -eq 0) {
                Add-LogLine "No new jobs. Showing $($visibleJobs.Count) listing(s) for $($script:ScanTimeFilterLabel)."
                $tgScanSummary = "Scan done. No new jobs. $($visibleJobs.Count) listing(s) visible."
            } else {
                $guiSentUrls = [System.Collections.Generic.HashSet[string]]::new(
                    [System.StringComparer]::OrdinalIgnoreCase)
                try {
                    foreach ($u in (Get-TelegramSentUrls)) {
                        [void]$guiSentUrls.Add((Get-CanonicalJobUrl -Url $u))
                    }
                } catch {}

                foreach ($job in $newJobs) {
                    $script:SeenJobs[$job.Id] = (Get-Date).ToString("o")
                    $cu = Get-CanonicalJobUrl -Url $job.Url
                    if (-not [string]::IsNullOrWhiteSpace($cu) -and $guiSentUrls.Contains($cu)) { continue }
                    Add-LogLine ("New job: {0} | {1} | {2}" -f $job.Title, $job.Company, $job.Location)
                    Show-JobNotification -Job $job
                    if (-not [string]::IsNullOrWhiteSpace($script:ScanTelegramToken) -and
                        -not [string]::IsNullOrWhiteSpace($script:ScanTelegramChatId)) {
                        $sent = Send-TelegramMessage -BotToken $script:ScanTelegramToken -ChatId $script:ScanTelegramChatId `
                                    -Message (Format-TelegramMessage -Job $job) `
                                    -LogCallback { param($m) Add-LogLine $m }
                        if ($sent) {
                            Add-LogLine "Telegram alert sent for '$($job.Title)'."
                            try { Set-JobTelegramSent -Url $job.Url } catch {}
                            [void]$guiSentUrls.Add($cu)
                            # Mark Tg column in the list
                            $listItem = $script:JobsList.Items | Where-Object { $_.Tag -eq $job.Url } | Select-Object -First 1
                            if ($listItem -and $listItem.SubItems.Count -ge 9) {
                                $listItem.SubItems[7].Text = if ($listItem.SubItems[7].Text -eq "Cloud") { "Both" } else { "GUI" }
                            }
                        }
                    }
                }
                Save-SeenJobs
                Add-LogLine "Alerted on $($newJobs.Count) new job(s). Showing $($visibleJobs.Count) for $($script:ScanTimeFilterLabel)."
                $tgScanSummary = "Scan done. Found $($newJobs.Count) new job(s). $($visibleJobs.Count) visible total."
            }
            $script:StatusLabel.Text = "Status: monitoring"
            if (-not [string]::IsNullOrWhiteSpace($script:TgCmdReplyToken)) {
                try { Send-TgReply $script:TgCmdReplyToken $script:TgCmdReplyChatId $tgScanSummary } catch {}
                $script:TgCmdReplyToken = ""; $script:TgCmdReplyChatId = ""
            }
        }
        catch {
            Add-LogLine "Poll timer error: $($_.Exception.Message)"
            $script:ScanPollTimer.Stop()
            $script:ScanRunning = $false
            $script:StatusLabel.Text = "Status: scan error"
            if (-not [string]::IsNullOrWhiteSpace($script:TgCmdReplyToken)) {
                try { Send-TgReply $script:TgCmdReplyToken $script:TgCmdReplyChatId "Scan failed: $($_.Exception.Message)" } catch {}
                $script:TgCmdReplyToken = ""; $script:TgCmdReplyChatId = ""
            }
        }
    })
    $script:ScanPollTimer.Start()
}

function Start-Monitoring {
    try {
        Save-Settings

        $pidPath = Join-Path $script:AppRoot "worker.pid"
        if (Test-Path -LiteralPath $pidPath) {
            try {
                $existingPid = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
                Get-Process -Id $existingPid -ErrorAction Stop | Out-Null
                Add-LogLine "Worker already running (PID $existingPid)."
                $script:StatusLabel.Text = "Status: worker already running (PID $existingPid)"
                return
            }
            catch {
                Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
            }
        }

        $workerScript = Join-Path $script:AppRoot "linkedin-job-worker.ps1"
        if (-not (Test-Path -LiteralPath $workerScript)) {
            Add-LogLine "Worker script not found: $workerScript"
            return
        }

        # Launch the worker. Redirect stderr so any parse or init crash is captured.
        $crashLog  = Join-Path $script:AppRoot "worker-crash.log"
        $argString = "-NoProfile -ExecutionPolicy Bypass -File `"$workerScript`""
        $proc = Start-Process -FilePath "powershell.exe" -ArgumentList $argString -WindowStyle Hidden -RedirectStandardError $crashLog -PassThru

        $script:WorkerStartedPid = $proc.Id   # lamp uses this until worker.pid is written

        $minutes = [int]$script:IntervalBox.Value
        $script:Timer.Interval = [Math]::Max(1, $minutes) * 60000
        $script:Timer.Start()

        $script:StatusLabel.Text = "Status: worker starting (PID $($proc.Id))..."
        Add-LogLine "Worker started (PID $($proc.Id)). GUI timer: every $minutes min."
        Update-WorkerLamp   # lamp turns green immediately via WorkerStartedPid
    }
    catch {
        $script:StatusLabel.Text = "Status: error"
        Add-LogLine "Start failed: $($_.Exception.Message)"
    }
}

function Stop-Monitoring {
    $script:Timer.Stop()

    $pidPath = Join-Path $script:AppRoot "worker.pid"
    if (Test-Path -LiteralPath $pidPath) {
        try {
            $workerPid = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
            $proc = Get-Process -Id $workerPid -ErrorAction Stop
            $proc.Kill()
            Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
            Add-LogLine "Worker stopped (PID $workerPid)."
        }
        catch {
            Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
            Add-LogLine "Worker process was already gone."
        }
    }
    else {
        Add-LogLine "Worker was not running."
    }

    $script:WorkerStartedPid = 0
    $script:StatusLabel.Text = "Status: stopped"
    Update-WorkerLamp
}

function Send-TelegramTest {
    try {
        Save-Settings
        $logCb = { param($m) Add-LogLine $m }
        $ok = Send-TelegramMessage `
            -BotToken  $script:TelegramTokenBox.Text.Trim() `
            -ChatId    $script:TelegramChatIdBox.Text.Trim() `
            -Message   "LinkedIn UAE Job Alert test message. Telegram is connected." `
            -LogCallback $logCb

        if ($ok) {
            Add-LogLine "Telegram test message sent."
        }
        else {
            Add-LogLine "Telegram test message was not sent. Check bot token and chat ID."
        }
    }
    catch {
        Add-LogLine "Telegram test failed: $($_.Exception.Message)"
    }
}

function Import-CookiesToForm {
    try {
        $browserName = $script:BrowserBox.Text
        if ([string]::IsNullOrWhiteSpace($browserName)) {
            $browserName = "Edge"
        }

        $result = Import-LinkedInCookiesFromBrowser -BrowserName $browserName
        $script:CookieBox.Text = $result.CookieHeader
        Save-Settings
        Add-LogLine "Imported LinkedIn cookies from $($result.Browser) profile '$($result.ProfileName)' ($($result.CookieCount) cookies, scanned $($result.ProfilesScanned) profile(s))."
    }
    catch {
        Add-LogLine "Cookie import failed: $($_.Exception.Message)"
    }
}

$script:SeenJobs       = Load-SeenJobs
$script:HasPrimedState = $script:SeenJobs.Count -gt 0
$savedSettings         = Load-Settings

# ── Design tokens ────────────────────────────────────────────────────────────
$clrBg     = [System.Drawing.Color]::FromArgb(243, 243, 243)
$clrCard   = [System.Drawing.Color]::White
$clrHeader = [System.Drawing.Color]::FromArgb(0, 102, 204)
$clrAccent = [System.Drawing.Color]::FromArgb(0, 102, 204)
$clrGreen  = [System.Drawing.Color]::FromArgb(39, 174, 96)
$clrRed    = [System.Drawing.Color]::FromArgb(192, 57, 43)
$clrText   = [System.Drawing.Color]::FromArgb(32, 33, 36)
$clrMuted  = [System.Drawing.Color]::FromArgb(100, 104, 110)
$fntUi     = New-Object System.Drawing.Font("Segoe UI", 9)
$fntSm     = New-Object System.Drawing.Font("Segoe UI", 8)
$fntHdr    = New-Object System.Drawing.Font("Segoe UI", 12, [System.Drawing.FontStyle]::Bold)
$fntSec    = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Bold)

# ── UI helper functions ───────────────────────────────────────────────────────
function New-Card {
    param([int]$X, [int]$Y, [int]$W, [int]$H, [string]$Title = "")
    $p = New-Object System.Windows.Forms.Panel
    $p.Location  = New-Object System.Drawing.Point($X, $Y)
    $p.Size      = New-Object System.Drawing.Size($W, $H)
    $p.BackColor = [System.Drawing.Color]::White
    $p.Add_Paint({
        param($s, $ev)
        $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(210, 212, 216), 1)
        $ev.Graphics.DrawRectangle($pen, 0, 0, $s.Width - 1, $s.Height - 1)
        $shadowPen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(230, 230, 230), 2)
        $ev.Graphics.DrawLine($shadowPen, 1, $s.Height, $s.Width, $s.Height)
        $ev.Graphics.DrawLine($shadowPen, $s.Width, 1, $s.Width, $s.Height)
        $shadowPen.Dispose()
        $pen.Dispose()
    })
    if ($Title) {
        $lbl           = New-Object System.Windows.Forms.Label
        $lbl.Text      = $Title
        $lbl.Font      = New-Object System.Drawing.Font("Segoe UI", 8, [System.Drawing.FontStyle]::Bold)
        $lbl.ForeColor = [System.Drawing.Color]::FromArgb(0, 102, 204)
        $lbl.Location  = New-Object System.Drawing.Point(12, 9)
        $lbl.AutoSize  = $true
        [void]$p.Controls.Add($lbl)
    }
    return $p
}

function New-Btn {
    param([string]$Text, [int]$X, [int]$Y, [int]$W = 110, [int]$H = 32, [string]$Style = "accent")
    $b            = New-Object System.Windows.Forms.Button
    $b.Text       = $Text
    $b.Location   = New-Object System.Drawing.Point($X, $Y)
    $b.Size       = New-Object System.Drawing.Size($W, $H)
    $b.FlatStyle  = "Flat"
    $b.Font       = New-Object System.Drawing.Font("Segoe UI", 9)
    $b.Cursor     = [System.Windows.Forms.Cursors]::Hand
    switch ($Style) {
        "green"   {
            $b.BackColor = [System.Drawing.Color]::FromArgb(39, 174, 96)
            $b.ForeColor = [System.Drawing.Color]::White
            $b.FlatAppearance.BorderSize  = 0
        }
        "red"     {
            $b.BackColor = [System.Drawing.Color]::FromArgb(192, 57, 43)
            $b.ForeColor = [System.Drawing.Color]::White
            $b.FlatAppearance.BorderSize  = 0
        }
        "accent"  {
            $b.BackColor = [System.Drawing.Color]::FromArgb(0, 102, 204)
            $b.ForeColor = [System.Drawing.Color]::White
            $b.FlatAppearance.BorderSize  = 0
        }
        "outline" {
            $b.BackColor = [System.Drawing.Color]::White
            $b.ForeColor = [System.Drawing.Color]::FromArgb(0, 102, 204)
            $b.FlatAppearance.BorderColor = [System.Drawing.Color]::FromArgb(0, 102, 204)
            $b.FlatAppearance.BorderSize  = 1
        }
    }
    return $b
}

function New-Lbl {
    param([string]$Text, [int]$X, [int]$Y)
    $l           = New-Object System.Windows.Forms.Label
    $l.Text      = $Text
    $l.Location  = New-Object System.Drawing.Point($X, $Y)
    $l.Font      = New-Object System.Drawing.Font("Segoe UI", 8)
    $l.ForeColor = [System.Drawing.Color]::FromArgb(100, 104, 110)
    $l.AutoSize  = $true
    return $l
}

function New-Tb {
    param([int]$X, [int]$Y, [int]$W, [int]$H = 26)
    $t              = New-Object System.Windows.Forms.TextBox
    $t.Location     = New-Object System.Drawing.Point($X, $Y)
    $t.Size         = New-Object System.Drawing.Size($W, $H)
    $t.Font         = New-Object System.Drawing.Font("Segoe UI", 9)
    $t.BorderStyle  = "FixedSingle"
    $t.ForeColor    = [System.Drawing.Color]::FromArgb(32, 33, 36)
    $t.BackColor    = [System.Drawing.Color]::White
    return $t
}

# ── Form ──────────────────────────────────────────────────────────────────────
$script:Form               = New-Object System.Windows.Forms.Form
$script:Form.Text          = "LinkedIn UAE Job Alert"
$script:Form.ClientSize    = New-Object System.Drawing.Size(1160, 1030)
$script:Form.StartPosition = "CenterScreen"
$script:Form.MinimumSize   = New-Object System.Drawing.Size(1160, 1070)
$script:Form.BackColor     = $clrBg
$script:Form.Font          = $fntUi

# ── Header ────────────────────────────────────────────────────────────────────
$headerPanel           = New-Object System.Windows.Forms.Panel
$headerPanel.Location  = New-Object System.Drawing.Point(0, 0)
$headerPanel.Size      = New-Object System.Drawing.Size(1160, 52)
$headerPanel.BackColor = $clrHeader
$headerTitle           = New-Object System.Windows.Forms.Label
$headerTitle.Text      = "LinkedIn UAE Job Alert"
$headerTitle.Font      = $fntHdr
$headerTitle.ForeColor = [System.Drawing.Color]::White
$headerTitle.Location  = New-Object System.Drawing.Point(18, 13)
$headerTitle.AutoSize  = $true
[void]$headerPanel.Controls.Add($headerTitle)

# ── Monitoring dashboard launcher (real-time logs + full control in browser) ──
$dashButton = New-Btn "Monitoring Dashboard" 940 11 200 30 "accent"
$dashButton.Add_Click({
    $dashPath = Join-Path $script:AppRoot "cloud\dashboard.py"
    if (-not (Test-Path -LiteralPath $dashPath)) {
        [System.Windows.Forms.MessageBox]::Show("dashboard.py not found at:`n$dashPath",
            "Monitoring Dashboard") | Out-Null
        return
    }
    # Re-use the server if it's already listening; otherwise start it hidden.
    $running = $false
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", 8765)
        $running = $true
        $tcp.Close()
    } catch { }
    if (-not $running) {
        Start-Process -FilePath "python" `
            -ArgumentList @($dashPath, "--no-browser") `
            -WorkingDirectory $script:AppRoot -WindowStyle Hidden
        Start-Sleep -Milliseconds 1300
    }
    Start-Process "http://127.0.0.1:8765"
})
[void]$headerPanel.Controls.Add($dashButton)

# ── Search Settings card ──────────────────────────────────────────────────────
$searchCard = New-Card -X 10 -Y 60 -W 555 -H 220 -Title "SEARCH SETTINGS"

[void]$searchCard.Controls.Add((New-Lbl "Job roles / keywords (one per line)" 12 31))

$script:KeywordsBox             = New-Object System.Windows.Forms.TextBox
$script:KeywordsBox.Multiline   = $true
$script:KeywordsBox.ScrollBars  = "Vertical"
$script:KeywordsBox.Location    = New-Object System.Drawing.Point(12, 49)
$script:KeywordsBox.Size        = New-Object System.Drawing.Size(238, 110)
$script:KeywordsBox.Font        = $fntUi
$script:KeywordsBox.BorderStyle = "FixedSingle"
$savedKeywords = Get-SettingValue -SettingsObject $savedSettings -Name "Keywords"
$script:KeywordsBox.Text = if ($savedKeywords) {
    ($savedKeywords -join "`r`n")
} else {
@"
IT Systems administrator
Senior IT Support
IT support
IT HelpDesk
"@.Trim()
}
[void]$searchCard.Controls.Add($script:KeywordsBox)

[void]$searchCard.Controls.Add((New-Lbl "Exclude keywords (comma-separated)" 12 167))
$script:ExcludeBox             = New-Tb -X 12 -Y 183 -W 238 -H 26
$script:ExcludeBox.Text        = [string](Get-SettingValue -SettingsObject $savedSettings -Name "ExcludeKeywords" -DefaultValue "")
[void]$searchCard.Controls.Add($script:ExcludeBox)

[void]$searchCard.Controls.Add((New-Lbl "Countries / locations (comma-separated)" 260 31))
$script:CountryBox      = New-Tb -X 260 -Y 49 -W 280
$script:CountryBox.Text = [string](Get-SettingValue -SettingsObject $savedSettings -Name "Location" -DefaultValue "United Arab Emirates")
# Multiple locations: enter several comma-separated, e.g. "United Arab Emirates, Egypt".
# Each location is searched for every keyword (the cloud worker splits on commas too).
[void]$searchCard.Controls.Add($script:CountryBox)

[void]$searchCard.Controls.Add((New-Lbl "Posted time filter" 260 88))
$script:TimeFilterBox              = New-Object System.Windows.Forms.ComboBox
$script:TimeFilterBox.Location     = New-Object System.Drawing.Point(260, 105)
$script:TimeFilterBox.Size         = New-Object System.Drawing.Size(155, 28)
$script:TimeFilterBox.DropDownStyle = "DropDownList"
$script:TimeFilterBox.Font         = $fntUi
[void]$script:TimeFilterBox.Items.Add("Last 1 hour")
[void]$script:TimeFilterBox.Items.Add("Last 2 hours")
[void]$script:TimeFilterBox.Items.Add("Last 24 hours")
[void]$script:TimeFilterBox.Items.Add("Last week")
[void]$script:TimeFilterBox.Items.Add("Last month")
[void]$script:TimeFilterBox.Items.Add("Custom")
$savedTimeFilter = [string](Get-SettingValue -SettingsObject $savedSettings -Name "TimeFilter" -DefaultValue "Last 24 hours")
$script:TimeFilterBox.SelectedItem = if ($script:TimeFilterBox.Items.Contains($savedTimeFilter)) { $savedTimeFilter } else { "Last 24 hours" }
[void]$searchCard.Controls.Add($script:TimeFilterBox)

$script:CustomHoursLabel          = New-Lbl "Custom hours" 424 88
[void]$searchCard.Controls.Add($script:CustomHoursLabel)
$script:CustomHoursBox            = New-Object System.Windows.Forms.NumericUpDown
$script:CustomHoursBox.Location   = New-Object System.Drawing.Point(424, 105)
$script:CustomHoursBox.Size       = New-Object System.Drawing.Size(88, 28)
$script:CustomHoursBox.Minimum    = 1
$script:CustomHoursBox.Maximum    = 8760
$script:CustomHoursBox.Font       = $fntUi
$savedCustomHours = Get-SettingValue -SettingsObject $savedSettings -Name "CustomHours" -DefaultValue 24
$script:CustomHoursBox.Value      = [decimal]$savedCustomHours
[void]$searchCard.Controls.Add($script:CustomHoursBox)

[void]$searchCard.Controls.Add((New-Lbl "Search sources" 260 148))
$script:LinkedInCheckBox          = New-Object System.Windows.Forms.CheckBox
$script:LinkedInCheckBox.Text     = "LinkedIn"
$script:LinkedInCheckBox.Location = New-Object System.Drawing.Point(260, 166)
$script:LinkedInCheckBox.Size     = New-Object System.Drawing.Size(90, 24)
$script:LinkedInCheckBox.Font     = $fntUi
$script:LinkedInCheckBox.Checked  = [bool](Get-SettingValue -SettingsObject $savedSettings -Name "SearchLinkedIn" -DefaultValue $true)
[void]$searchCard.Controls.Add($script:LinkedInCheckBox)

$script:IndeedCheckBox            = New-Object System.Windows.Forms.CheckBox
$script:IndeedCheckBox.Text       = "Indeed"
$script:IndeedCheckBox.Location   = New-Object System.Drawing.Point(358, 166)
$script:IndeedCheckBox.Size       = New-Object System.Drawing.Size(80, 24)
$script:IndeedCheckBox.Font       = $fntUi
$script:IndeedCheckBox.Checked    = [bool](Get-SettingValue -SettingsObject $savedSettings -Name "SearchIndeed" -DefaultValue $true)
[void]$searchCard.Controls.Add($script:IndeedCheckBox)

# ── Automation card ───────────────────────────────────────────────────────────
$autoCard = New-Card -X 573 -Y 60 -W 577 -H 430 -Title "AUTOMATION"

$startButton    = New-Btn "Start"       12  34  100 34 "green"
$stopButton     = New-Btn "Stop"       118  34  100 34 "red"
$scanNowButton  = New-Btn "Scan Now"   224  34  110 34 "accent"
$enrichAiButton = New-Btn "Enrich AI"  340  34  110 34 "outline"
$openJobButton  = New-Btn "Open Job"   456  34  110 34 "outline"
[void]$autoCard.Controls.Add($startButton)
[void]$autoCard.Controls.Add($stopButton)
[void]$autoCard.Controls.Add($scanNowButton)
[void]$autoCard.Controls.Add($enrichAiButton)
[void]$autoCard.Controls.Add($openJobButton)

[void]$autoCard.Controls.Add((New-Lbl "Interval (min)" 12 84))
$script:IntervalBox          = New-Object System.Windows.Forms.NumericUpDown
$script:IntervalBox.Location = New-Object System.Drawing.Point(12, 101)
$script:IntervalBox.Size     = New-Object System.Drawing.Size(75, 26)
$script:IntervalBox.Minimum  = 1
$script:IntervalBox.Maximum  = 60
$script:IntervalBox.Font     = $fntUi
$savedInterval = Get-SettingValue -SettingsObject $savedSettings -Name "IntervalMinutes" -DefaultValue 5
$script:IntervalBox.Value    = [decimal]$savedInterval
[void]$autoCard.Controls.Add($script:IntervalBox)

[void]$autoCard.Controls.Add((New-Lbl "Browser" 100 84))
$script:BrowserBox              = New-Object System.Windows.Forms.ComboBox
$script:BrowserBox.Location     = New-Object System.Drawing.Point(100, 101)
$script:BrowserBox.Size         = New-Object System.Drawing.Size(148, 28)
$script:BrowserBox.DropDownStyle = "DropDownList"
$script:BrowserBox.Font         = $fntUi
[void]$script:BrowserBox.Items.Add("Edge")
[void]$script:BrowserBox.Items.Add("Chrome (Chromium)")
[void]$script:BrowserBox.Items.Add("Chromium")
$savedBrowserChoice = [string](Get-SettingValue -SettingsObject $savedSettings -Name "BrowserChoice" -DefaultValue "Edge")
if ($savedBrowserChoice -eq "Chrome") { $savedBrowserChoice = "Chrome (Chromium)" }
$script:BrowserBox.SelectedItem = if ($script:BrowserBox.Items.Contains($savedBrowserChoice)) { $savedBrowserChoice } else { "Edge" }
[void]$autoCard.Controls.Add($script:BrowserBox)

$script:HideAppliedCheckBox          = New-Object System.Windows.Forms.CheckBox
$script:HideAppliedCheckBox.Text     = "Hide already-applied jobs"
$script:HideAppliedCheckBox.Location = New-Object System.Drawing.Point(262, 102)
$script:HideAppliedCheckBox.Size     = New-Object System.Drawing.Size(295, 24)
$script:HideAppliedCheckBox.Font     = $fntUi
$script:HideAppliedCheckBox.Checked  = [bool](Get-SettingValue -SettingsObject $savedSettings -Name "HideAppliedJobs" -DefaultValue $true)
[void]$autoCard.Controls.Add($script:HideAppliedCheckBox)

[void]$autoCard.Controls.Add((New-Lbl "Ollama URL" 12 136))
$script:OllamaUrlBox      = New-Tb -X 12 -Y 152 -W 200 -H 26
$script:OllamaUrlBox.Text = [string](Get-SettingValue -SettingsObject $savedSettings -Name "OllamaUrl" -DefaultValue "http://localhost:11434")
[void]$autoCard.Controls.Add($script:OllamaUrlBox)

[void]$autoCard.Controls.Add((New-Lbl "Min AI Score (0-10)" 222 136))
$script:MinAiScoreBox          = New-Object System.Windows.Forms.NumericUpDown
$script:MinAiScoreBox.Location = New-Object System.Drawing.Point(222, 152)
$script:MinAiScoreBox.Size     = New-Object System.Drawing.Size(60, 26)
$script:MinAiScoreBox.Minimum  = 0
$script:MinAiScoreBox.Maximum  = 10
$script:MinAiScoreBox.Font     = $fntUi
$script:MinAiScoreBox.Value    = [decimal](Get-SettingValue -SettingsObject $savedSettings -Name "MinAiScore" -DefaultValue 4)
[void]$autoCard.Controls.Add($script:MinAiScoreBox)

$script:AutoEnrichCheckBox          = New-Object System.Windows.Forms.CheckBox
$script:AutoEnrichCheckBox.Text     = "Auto AI score after each cloud scan"
$script:AutoEnrichCheckBox.Location = New-Object System.Drawing.Point(297, 152)
$script:AutoEnrichCheckBox.Size     = New-Object System.Drawing.Size(268, 24)
$script:AutoEnrichCheckBox.Font     = $fntUi
$script:AutoEnrichCheckBox.Checked  = [bool](Get-SettingValue -SettingsObject $savedSettings -Name "AutoEnrich" -DefaultValue $false)
[void]$autoCard.Controls.Add($script:AutoEnrichCheckBox)

[void]$autoCard.Controls.Add((New-Lbl "CV / Profile  (paste path, LinkedIn URL, or type a description)" 12 186))
$script:UserProfileBox           = New-Tb -X 12 -Y 202 -W 322 -H 24
$script:UserProfileBox.Text      = [string](Get-SettingValue -SettingsObject $savedSettings -Name "UserProfile" -DefaultValue "")
[void]$autoCard.Controls.Add($script:UserProfileBox)

$browseCvButton  = New-Btn "Browse PDF..."  338 201 108 26 "outline"
$analyzeCvButton = New-Btn "Analyze CV"     452 201 112 26 "accent"
[void]$autoCard.Controls.Add($browseCvButton)
[void]$autoCard.Controls.Add($analyzeCvButton)

# CV status label -- updated after analysis
$script:CvStatusLabel           = New-Object System.Windows.Forms.Label
$script:CvStatusLabel.Location  = New-Object System.Drawing.Point(12, 234)
$script:CvStatusLabel.Size      = New-Object System.Drawing.Size(553, 18)
$script:CvStatusLabel.Font      = $fntUi
$script:CvStatusLabel.Text      = "CV: not analyzed yet -- click Analyze CV to extract skills"
$script:CvStatusLabel.ForeColor = [System.Drawing.Color]::Gray
[void]$autoCard.Controls.Add($script:CvStatusLabel)

# Skills preview box -- read-only, shows extracted skills after analysis
$script:CvSkillsBox              = New-Object System.Windows.Forms.TextBox
$script:CvSkillsBox.Location     = New-Object System.Drawing.Point(12, 256)
$script:CvSkillsBox.Size         = New-Object System.Drawing.Size(553, 44)
$script:CvSkillsBox.Multiline    = $true
$script:CvSkillsBox.ReadOnly     = $true
$script:CvSkillsBox.ScrollBars   = "Vertical"
$script:CvSkillsBox.Font         = $fntUi
$script:CvSkillsBox.BackColor    = [System.Drawing.Color]::FromArgb(245, 247, 250)
$script:CvSkillsBox.Text         = "(skills will appear here after analysis)"
$script:CvSkillsBox.ForeColor    = [System.Drawing.Color]::Gray
[void]$autoCard.Controls.Add($script:CvSkillsBox)

# Gmail alerts checkbox
$script:GmailCheckBox               = New-Object System.Windows.Forms.CheckBox
$script:GmailCheckBox.Text          = "Search Gmail for job alerts"
$script:GmailCheckBox.Location      = New-Object System.Drawing.Point(12, 310)
$script:GmailCheckBox.Size          = New-Object System.Drawing.Size(290, 24)
$script:GmailCheckBox.Font          = $fntUi
$script:GmailCheckBox.Checked       = [bool](Get-SettingValue -SettingsObject $savedSettings -Name "SearchGmail" -DefaultValue $false)
$script:GmailCheckBox.Add_CheckedChanged({
    $script:GmailEmailBox.Enabled = $script:GmailCheckBox.Checked
    $script:GmailPasswordBox.Enabled = $script:GmailCheckBox.Checked
})
[void]$autoCard.Controls.Add($script:GmailCheckBox)

[void]$autoCard.Controls.Add((New-Lbl "Gmail Email" 12 340))
$script:GmailEmailBox           = New-Tb -X 12 -Y 358 -W 250 -H 26
$script:GmailEmailBox.Text      = [string](Get-SettingValue -SettingsObject $savedSettings -Name "GmailEmail" -DefaultValue "")
$script:GmailEmailBox.Enabled   = $script:GmailCheckBox.Checked
[void]$autoCard.Controls.Add($script:GmailEmailBox)

[void]$autoCard.Controls.Add((New-Lbl "Gmail App Password" 280 340))
$script:GmailPasswordBox           = New-Tb -X 280 -Y 358 -W 285 -H 26
$script:GmailPasswordBox.Text      = [string](Get-SettingValue -SettingsObject $savedSettings -Name "GmailPassword" -DefaultValue "")
$script:GmailPasswordBox.UseSystemPasswordChar = $true
$script:GmailPasswordBox.Enabled   = $script:GmailCheckBox.Checked
[void]$autoCard.Controls.Add($script:GmailPasswordBox)

$gmailInfoLbl          = New-Lbl "Get app password: myaccount.google.com/apppasswords (requires 2FA)" 12 393
$gmailInfoLbl.AutoSize = $false
$gmailInfoLbl.Size     = New-Object System.Drawing.Size(553, 18)
[void]$autoCard.Controls.Add($gmailInfoLbl)

# ── LinkedIn Session card ─────────────────────────────────────────────────────
$cookieCard = New-Card -X 10 -Y 498 -W 555 -H 116 -Title "LINKEDIN SESSION"

$script:CookieBox      = New-Tb -X 12 -Y 32 -W 395 -H 26
$script:CookieBox.Text = [string](Get-SettingValue -SettingsObject $savedSettings -Name "LinkedInCookie" -DefaultValue "")
[void]$cookieCard.Controls.Add($script:CookieBox)

$importCookiesButton = New-Btn "Import Cookies" 415 30 128 30 "outline"
[void]$cookieCard.Controls.Add($importCookiesButton)

$cookieHintLbl          = New-Lbl "Paste li_at=...; JSESSIONID=... or use Import Cookies from Edge / Chrome." 12 66
$cookieHintLbl.AutoSize = $false
$cookieHintLbl.Size     = New-Object System.Drawing.Size(530, 18)
[void]$cookieCard.Controls.Add($cookieHintLbl)

# ── Telegram Alerts card ──────────────────────────────────────────────────────
$telegramCard = New-Card -X 573 -Y 498 -W 577 -H 116 -Title "TELEGRAM ALERTS"

[void]$telegramCard.Controls.Add((New-Lbl "Bot token" 12 31))
$script:TelegramTokenBox      = New-Tb -X 12 -Y 49 -W 262 -H 26
$script:TelegramTokenBox.Text = [string](Get-SettingValue -SettingsObject $savedSettings -Name "TelegramBotToken" -DefaultValue "")
[void]$telegramCard.Controls.Add($script:TelegramTokenBox)

[void]$telegramCard.Controls.Add((New-Lbl "Chat ID" 284 31))
$script:TelegramChatIdBox      = New-Tb -X 284 -Y 49 -W 118 -H 26
$script:TelegramChatIdBox.Text = [string](Get-SettingValue -SettingsObject $savedSettings -Name "TelegramChatId" -DefaultValue "")
[void]$telegramCard.Controls.Add($script:TelegramChatIdBox)

$telegramTestButton = New-Btn "Test"         412 47  74 30 "outline"
$sendVisibleButton  = New-Btn "Send Visible"  494 47  76 30 "outline"
[void]$telegramCard.Controls.Add($telegramTestButton)
[void]$telegramCard.Controls.Add($sendVisibleButton)

$tgHintLbl          = New-Lbl "Get your bot token from @BotFather and chat ID from @userinfobot." 12 84
$tgHintLbl.AutoSize = $false
$tgHintLbl.Size     = New-Object System.Drawing.Size(550, 18)
[void]$telegramCard.Controls.Add($tgHintLbl)

# ── Status bar ────────────────────────────────────────────────────────────────
$statusPanel           = New-Object System.Windows.Forms.Panel
$statusPanel.Location  = New-Object System.Drawing.Point(10, 622)
$statusPanel.Size      = New-Object System.Drawing.Size(1140, 30)
$statusPanel.BackColor = $clrBg

$script:StatusLabel           = New-Object System.Windows.Forms.Label
$script:StatusLabel.Text      = if ($script:HasPrimedState) { "Status: ready (existing cache loaded)" } else { "Status: ready" }
$script:StatusLabel.Location  = New-Object System.Drawing.Point(0, 6)
$script:StatusLabel.Size      = New-Object System.Drawing.Size(900, 20)
$script:StatusLabel.Font      = $fntUi
$script:StatusLabel.ForeColor = $clrText
[void]$statusPanel.Controls.Add($script:StatusLabel)

$workerLampLabel           = New-Object System.Windows.Forms.Label
$workerLampLabel.Text      = "Worker:"
$workerLampLabel.Location  = New-Object System.Drawing.Point(908, 7)
$workerLampLabel.Font      = $fntUi
$workerLampLabel.ForeColor = $clrMuted
$workerLampLabel.AutoSize  = $true
[void]$statusPanel.Controls.Add($workerLampLabel)

$script:WorkerLamp           = New-Object System.Windows.Forms.Panel
$script:WorkerLamp.Location  = New-Object System.Drawing.Point(962, 4)
$script:WorkerLamp.Size      = New-Object System.Drawing.Size(22, 22)
$script:WorkerLamp.BackColor = [System.Drawing.Color]::Transparent
$script:WorkerLamp.Tag       = "red"
$script:WorkerLamp.Add_Paint({
    param($sender, $e)
    $g = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $isGreen   = ($sender.Tag -eq "green")
    $mainRgb   = if ($isGreen) { @(50, 205, 50) } else { @(220, 50, 50) }
    $mainColor = [System.Drawing.Color]::FromArgb($mainRgb[0], $mainRgb[1], $mainRgb[2])
    $w = $sender.Width - 1
    $h = $sender.Height - 1
    $glowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(70, $mainColor.R, $mainColor.G, $mainColor.B))
    $g.FillEllipse($glowBrush, 0, 0, $w, $h)
    $glowBrush.Dispose()
    $mainBrush = New-Object System.Drawing.SolidBrush($mainColor)
    $g.FillEllipse($mainBrush, 2, 2, $w - 4, $h - 4)
    $mainBrush.Dispose()
    $hlBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(110, 255, 255, 255))
    $g.FillEllipse($hlBrush, 5, 5, [int](($w - 4) / 2.5), [int](($h - 4) / 2.5))
    $hlBrush.Dispose()
})
$script:WorkerLampTooltip = New-Object System.Windows.Forms.ToolTip
$script:WorkerLampTooltip.SetToolTip($script:WorkerLamp, "Worker status unknown")
[void]$statusPanel.Controls.Add($script:WorkerLamp)

$cloudLampLabel           = New-Object System.Windows.Forms.Label
$cloudLampLabel.Text      = "Cloud:"
$cloudLampLabel.Location  = New-Object System.Drawing.Point(994, 7)
$cloudLampLabel.Font      = $fntUi
$cloudLampLabel.ForeColor = $clrMuted
$cloudLampLabel.AutoSize  = $true
[void]$statusPanel.Controls.Add($cloudLampLabel)

$script:CloudLamp           = New-Object System.Windows.Forms.Panel
$script:CloudLamp.Location  = New-Object System.Drawing.Point(1046, 4)
$script:CloudLamp.Size      = New-Object System.Drawing.Size(22, 22)
$script:CloudLamp.BackColor = [System.Drawing.Color]::Transparent
$script:CloudLamp.Tag       = "grey"
$script:CloudLamp.Add_Paint({
    param($sender, $e)
    $g   = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $rgb = switch ($sender.Tag) {
        "green"  { @(50, 205, 50) }
        "red"    { @(220, 50, 50) }
        "yellow" { @(240, 180, 0) }
        default  { @(160, 160, 160) }
    }
    $mainColor = [System.Drawing.Color]::FromArgb($rgb[0], $rgb[1], $rgb[2])
    $w = $sender.Width - 1
    $h = $sender.Height - 1
    $glowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(70, $mainColor.R, $mainColor.G, $mainColor.B))
    $g.FillEllipse($glowBrush, 0, 0, $w, $h)
    $glowBrush.Dispose()
    $mainBrush = New-Object System.Drawing.SolidBrush($mainColor)
    $g.FillEllipse($mainBrush, 2, 2, $w - 4, $h - 4)
    $mainBrush.Dispose()
    $hlBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(110, 255, 255, 255))
    $g.FillEllipse($hlBrush, 5, 5, [int](($w - 4) / 2.5), [int](($h - 4) / 2.5))
    $hlBrush.Dispose()
})
$script:CloudLampTooltip = New-Object System.Windows.Forms.ToolTip
$script:CloudLampTooltip.SetToolTip($script:CloudLamp, "Left-click: refresh  |  Right-click: controls")
[void]$statusPanel.Controls.Add($script:CloudLamp)

# Cloud lamp context menu
$script:CloudMenuCancel   = $null
$script:CloudMenuSchedule = $null
$script:CloudMenu         = New-Object System.Windows.Forms.ContextMenuStrip

$cloudMenuRun = New-Object System.Windows.Forms.ToolStripMenuItem("Run Cloud Now")
$cloudMenuRun.Add_Click({ try { Invoke-CloudRunNow } catch { Add-LogLine "Cloud run error: $_" } })

$script:CloudMenuCancel         = New-Object System.Windows.Forms.ToolStripMenuItem("Cancel Running Scan")
$script:CloudMenuCancel.Enabled = $false
$script:CloudMenuCancel.Add_Click({ try { Invoke-CloudCancel } catch { Add-LogLine "Cloud cancel error: $_" } })

$cloudMenuLogs = New-Object System.Windows.Forms.ToolStripMenuItem("Open GitHub Logs")
$cloudMenuLogs.Add_Click({ Open-CloudLogs })

[void]$script:CloudMenu.Items.Add($cloudMenuRun)
[void]$script:CloudMenu.Items.Add($script:CloudMenuCancel)
[void]$script:CloudMenu.Items.Add($cloudMenuLogs)
[void]$script:CloudMenu.Items.Add((New-Object System.Windows.Forms.ToolStripSeparator))

$script:CloudMenuSchedule = New-Object System.Windows.Forms.ToolStripMenuItem("Pause Schedule")
$script:CloudMenuSchedule.Add_Click({ try { Toggle-CloudSchedule } catch { Add-LogLine "Schedule toggle error: $_" } })
[void]$script:CloudMenu.Items.Add($script:CloudMenuSchedule)

$script:CloudLamp.ContextMenuStrip = $script:CloudMenu

# ── AI enrichment lamp (Phase 1.5) ────────────────────────────────────────────
$aiLampLabel           = New-Object System.Windows.Forms.Label
$aiLampLabel.Text      = "AI:"
$aiLampLabel.Location  = New-Object System.Drawing.Point(1078, 7)
$aiLampLabel.Font      = $fntUi
$aiLampLabel.ForeColor = $clrMuted
$aiLampLabel.AutoSize  = $true
[void]$statusPanel.Controls.Add($aiLampLabel)

$script:AiLamp           = New-Object System.Windows.Forms.Panel
$script:AiLamp.Location  = New-Object System.Drawing.Point(1106, 4)
$script:AiLamp.Size      = New-Object System.Drawing.Size(22, 22)
$script:AiLamp.BackColor = [System.Drawing.Color]::Transparent
$script:AiLamp.Tag       = "grey"
$script:AiLamp.Add_Paint({
    param($sender, $e)
    $g   = $e.Graphics
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $rgb = switch ($sender.Tag) {
        "green"  { @(50, 205, 50) }
        "red"    { @(220, 50, 50) }
        "yellow" { @(240, 180, 0) }
        default  { @(160, 160, 160) }
    }
    $mainColor = [System.Drawing.Color]::FromArgb($rgb[0], $rgb[1], $rgb[2])
    $w = $sender.Width - 1
    $h = $sender.Height - 1
    $glowBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(70, $mainColor.R, $mainColor.G, $mainColor.B))
    $g.FillEllipse($glowBrush, 0, 0, $w, $h)
    $glowBrush.Dispose()
    $mainBrush = New-Object System.Drawing.SolidBrush($mainColor)
    $g.FillEllipse($mainBrush, 2, 2, $w - 4, $h - 4)
    $mainBrush.Dispose()
    $hlBrush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(110, 255, 255, 255))
    $g.FillEllipse($hlBrush, 5, 5, [int](($w - 4) / 2.5), [int](($h - 4) / 2.5))
    $hlBrush.Dispose()
})
$script:AiLampTooltip = New-Object System.Windows.Forms.ToolTip
$script:AiLampTooltip.SetToolTip($script:AiLamp, "AI scoring: not yet polled")
[void]$statusPanel.Controls.Add($script:AiLamp)

function Update-AiLamp {
    <#
    Polls the enricher last-run logs and the persistent enricher.log to decide
    whether AI scoring is healthy. Tag values: green | yellow | red | grey.
    Tooltip lines: status + last-run summary.
    #>
    try {
        $stdLog = Join-Path $script:AppRoot "enricher-last-run.log"
        $errLog = Join-Path $script:AppRoot "enricher-last-run.err.log"

        $tag     = "grey"
        $tooltip = "AI scoring: never run yet on this machine"

        if (Test-Path -LiteralPath $stdLog) {
            $stdInfo = Get-Item -LiteralPath $stdLog
            $ageMin  = [int]((Get-Date) - $stdInfo.LastWriteTime).TotalMinutes

            $tail = (Get-Content -LiteralPath $stdLog -Tail 5 -ErrorAction SilentlyContinue) -join "`n"

            if ($tail -match "Cannot reach Ollama|Ollama error") {
                $tag     = "red"
                $tooltip = "AI: Ollama unreachable ($ageMin min ago)`n$tail"
            } elseif ($tail -match "Done\. Scored=") {
                if ($ageMin -le 15) {
                    $tag     = "green"
                    $tooltip = "AI: last run $ageMin min ago - OK`n$tail"
                } else {
                    $tag     = "yellow"
                    $tooltip = "AI: idle ($ageMin min since last run)`n$tail"
                }
            } elseif ($tail -match "No unscored jobs found") {
                $tag     = "yellow"
                $tooltip = "AI: no unscored jobs (last run $ageMin min ago)"
            } else {
                $tag     = "yellow"
                $tooltip = "AI: last run incomplete ($ageMin min ago)`n$tail"
            }
        }

        if (Test-Path -LiteralPath $errLog) {
            $errSize = (Get-Item -LiteralPath $errLog).Length
            if ($errSize -gt 0) {
                $errTail = (Get-Content -LiteralPath $errLog -Tail 3 -ErrorAction SilentlyContinue) -join "`n"
                if ($errTail.Trim()) {
                    $tag     = "red"
                    $tooltip = "AI: stderr non-empty`n$errTail"
                }
            }
        }

        if ($script:AiLamp.Tag -ne $tag) {
            $script:AiLamp.Tag = $tag
            $script:AiLamp.Invalidate()
        }
        $script:AiLampTooltip.SetToolTip($script:AiLamp, $tooltip)
    } catch {
        # Silent: this is a status indicator, not a critical path
    }
}

$script:AiLampTimer          = New-Object System.Windows.Forms.Timer
$script:AiLampTimer.Interval = 30000   # 30 seconds
$script:AiLampTimer.Add_Tick({ Update-AiLamp })
$script:AiLampTimer.Start()
Update-AiLamp   # initial paint

function Update-CvStatusLabel {
    <#
    Reads cv_skills and cv_analyzed_at from Supabase bot_state and refreshes
    the CV status label and skills preview TextBox in the Automation card.
    Safe to call at any time -- all errors are swallowed.
    #>
    try {
        $settings = Load-Settings
        $sUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
        $sKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
        if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) {
            $script:CvStatusLabel.Text      = "CV: configure Supabase to enable CV analysis"
            $script:CvStatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 160)
            return
        }
        $headers = @{ "apikey" = $sKey; "Authorization" = "Bearer $sKey" }
        $uri  = "$sUrl/rest/v1/bot_state?key=in.(cv_skills,cv_analyzed_at)&select=key,value"
        $rows = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get -ErrorAction Stop -TimeoutSec 8

        $cvMap = @{}
        foreach ($row in $rows) { $cvMap[$row.key] = $row.value }

        $analyzedAt = $cvMap["cv_analyzed_at"]
        $cvSkills   = $cvMap["cv_skills"]

        if ([string]::IsNullOrWhiteSpace($analyzedAt)) {
            $script:CvStatusLabel.Text      = "CV: not analyzed yet -- click Analyze CV to extract skills"
            $script:CvStatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 160)
            $script:CvSkillsBox.Text        = ""
            return
        }

        # Count non-empty skills
        $skillCount = if ($cvSkills) {
            ($cvSkills.Split(",") | Where-Object { $_.Trim() }).Count
        } else { 0 }

        # Human-readable age string
        $ageStr = "analyzed"
        try {
            $ts   = [datetime]::Parse($analyzedAt, $null, [System.Globalization.DateTimeStyles]::RoundtripKind)
            $ageH = [int]([datetime]::UtcNow - $ts).TotalHours
            $ageStr = if     ($ageH -lt 1)   { "just now" }
                      elseif ($ageH -lt 24)  { "${ageH}h ago" }
                      elseif ($ageH -lt 48)  { "yesterday" }
                      else                   { "$([int]($ageH/24)) days ago" }
        } catch {}

        $script:CvStatusLabel.Text      = "CV: $skillCount skills extracted  |  Analyzed $ageStr"
        $script:CvStatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(0, 160, 100)
        $script:CvSkillsBox.Text        = if ($cvSkills) { $cvSkills } else { "" }
    } catch {
        $script:CvStatusLabel.Text      = "CV: could not read profile -- check Supabase settings"
        $script:CvStatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(180, 60, 60)
    }
}

# ── Job Listings card ─────────────────────────────────────────────────────────
$jobsCard = New-Card -X 10 -Y 660 -W 1140 -H 244 -Title "JOB LISTINGS   (green: <= 3 h, yellow: 4-24 h)"

$exportCsvButton = New-Btn "Export CSV" 990 4 120 22 "outline"
$exportCsvButton.Font = [System.Drawing.Font]::new("Segoe UI", 8)
[void]$jobsCard.Controls.Add($exportCsvButton)

$script:JobsList              = New-Object System.Windows.Forms.ListView
$script:JobsList.Location     = New-Object System.Drawing.Point(12, 30)
$script:JobsList.Size         = New-Object System.Drawing.Size(1116, 202)
$script:JobsList.View         = "Details"
$script:JobsList.FullRowSelect = $true
$script:JobsList.GridLines    = $true
$script:JobsList.HideSelection = $false
$script:JobsList.Font         = $fntUi
[void]$script:JobsList.Columns.Add("Source",   80)
[void]$script:JobsList.Columns.Add("Keyword", 130)
[void]$script:JobsList.Columns.Add("Title",   265)
[void]$script:JobsList.Columns.Add("Company", 185)
[void]$script:JobsList.Columns.Add("Location",165)
[void]$script:JobsList.Columns.Add("Posted",   95)
[void]$script:JobsList.Columns.Add("Applied",  65)
[void]$script:JobsList.Columns.Add("Tg",       40)
[void]$script:JobsList.Columns.Add("Score",    55)

$jobContextMenu = New-Object System.Windows.Forms.ContextMenuStrip
$menuOpen        = $jobContextMenu.Items.Add("Open in browser")
$menuApplied     = $jobContextMenu.Items.Add("Mark as Applied")
$menuDismiss     = $jobContextMenu.Items.Add("Dismiss")
$menuSave        = $jobContextMenu.Items.Add("Save / Star")
$menuShowAi      = $jobContextMenu.Items.Add("Show AI breakdown")
$menuCopyCover   = $jobContextMenu.Items.Add("Copy cover letter")
$script:JobsList.ContextMenuStrip = $jobContextMenu
[void]$jobsCard.Controls.Add($script:JobsList)

# ── Activity Log card ─────────────────────────────────────────────────────────
$logCard = New-Card -X 10 -Y 912 -W 1140 -H 110 -Title "ACTIVITY LOG"

$script:LogBox              = New-Object System.Windows.Forms.TextBox
$script:LogBox.Location     = New-Object System.Drawing.Point(12, 30)
$script:LogBox.Size         = New-Object System.Drawing.Size(1116, 68)
$script:LogBox.Multiline    = $true
$script:LogBox.ScrollBars   = "Vertical"
$script:LogBox.ReadOnly     = $true
$script:LogBox.Font         = $fntUi
$script:LogBox.BackColor    = [System.Drawing.Color]::FromArgb(250, 250, 252)
$script:LogBox.BorderStyle  = "None"
[void]$logCard.Controls.Add($script:LogBox)

# ── Notify icon / Timers ──────────────────────────────────────────────────────
$script:NotifyIcon        = New-Object System.Windows.Forms.NotifyIcon
$script:NotifyIcon.Icon   = [System.Drawing.SystemIcons]::Information
$script:NotifyIcon.Visible = $true
$script:NotifyIcon.Text   = "LinkedIn UAE Job Alert"

$script:Timer          = New-Object System.Windows.Forms.Timer
$script:Timer.Interval = 300000
$script:Timer.Add_Tick({
    try { Invoke-JobScan }
    catch {
        $script:StatusLabel.Text = "Status: error"
        Add-LogLine "Scheduled scan failed: $($_.Exception.Message)"
    }
})

$script:WorkerCheckTimer          = New-Object System.Windows.Forms.Timer
$script:WorkerCheckTimer.Interval = 10000
$script:WorkerCheckTimer.Add_Tick({ Update-WorkerLamp })

$script:CloudCheckTimer          = New-Object System.Windows.Forms.Timer
$script:CloudCheckTimer.Interval = 300000   # every 5 minutes
$script:CloudCheckTimer.Add_Tick({ try { Update-CloudLamp } catch {} })

$script:TelegramPollTimer          = New-Object System.Windows.Forms.Timer
$script:TelegramPollTimer.Interval = 5000
$script:TelegramPollTimer.Add_Tick({
    try {
        $pidPath = Join-Path $script:AppRoot "worker.pid"
        if (Test-Path -LiteralPath $pidPath) {
            try {
                $wPid = [int]((Get-Content -LiteralPath $pidPath -Raw).Trim())
                Get-Process -Id $wPid -ErrorAction Stop | Out-Null
                return
            } catch {}
        }
        Invoke-TelegramCommandPoll
    }
    catch {
        Add-LogLine "Telegram poll error: $($_.Exception.Message)"
    }
})

# ── Event handlers ────────────────────────────────────────────────────────────
$script:NotifyIcon.Add_BalloonTipClicked({
    if ($script:LastNotificationUrl) { Start-Process $script:LastNotificationUrl }
})

$script:JobsList.Add_DoubleClick({ Open-SelectedJob })
$script:CloudLamp.Add_Click({ try { Update-CloudLamp } catch {} })

$menuOpen.Add_Click({
    $sel = $script:JobsList.SelectedItems | Select-Object -First 1
    if ($sel) { Start-Process ([string]$sel.Tag) }
})
$menuApplied.Add_Click({
    foreach ($sel in @($script:JobsList.SelectedItems)) { Set-JobStatusInList -Item $sel -Status "applied" }
})
$menuDismiss.Add_Click({
    foreach ($sel in @($script:JobsList.SelectedItems)) { Set-JobStatusInList -Item $sel -Status "dismissed" }
})
$menuSave.Add_Click({
    foreach ($sel in @($script:JobsList.SelectedItems)) { Set-JobStatusInList -Item $sel -Status "saved" }
})

function Get-JobEnrichment {
    <#
    Fetches the full Phase 2-5 enrichment for the selected job by URL.
    Returns $null if Supabase creds are missing, fetch fails, or no row found.
    #>
    param([string]$JobUrl)
    if ([string]::IsNullOrWhiteSpace($JobUrl)) { return $null }
    try {
        $settings = Load-Settings
        $sUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
        $sKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
        if ([string]::IsNullOrWhiteSpace($sUrl) -or [string]::IsNullOrWhiteSpace($sKey)) { return $null }
        $headers = @{ "apikey" = $sKey; "Authorization" = "Bearer $sKey" }
        $cols = "title,company,llm_score,llm_summary,skills_match,experience_match,location_match,seniority_match,matched_skills,missing_skills,red_flags,cover_letter_draft"
        $uri  = "$sUrl/rest/v1/jobs?select=$cols&url=eq.$([System.Web.HttpUtility]::UrlEncode($JobUrl))&limit=1"
        $rows = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get -ErrorAction Stop -TimeoutSec 10
        if ($rows -and $rows.Count -gt 0) { return $rows[0] }
    } catch {
        Add-LogLine "AI fetch error: $($_.Exception.Message)"
    }
    return $null
}

$menuShowAi.Add_Click({
    $sel = $script:JobsList.SelectedItems | Select-Object -First 1
    if (-not $sel) { return }
    $row = Get-JobEnrichment -JobUrl ([string]$sel.Tag)
    if ($null -eq $row) {
        [System.Windows.Forms.MessageBox]::Show(
            "No AI enrichment found for this job (Supabase missing or not yet scored).",
            "AI breakdown", "OK", "Information") | Out-Null
        return
    }
    $matched = if ($row.matched_skills) { ($row.matched_skills | ForEach-Object { [string]$_ }) -join ", " } else { "(none)" }
    $missing = if ($row.missing_skills) { ($row.missing_skills | ForEach-Object { [string]$_ }) -join ", " } else { "(none)" }
    $flags   = if ($row.red_flags)      { ($row.red_flags      | ForEach-Object { [string]$_ }) -join " | " } else { "(none)" }
    $msg = @(
        "$($row.title)  @  $($row.company)",
        "",
        "Overall:    $($row.llm_score)/10",
        "Skills:     $($row.skills_match)/10",
        "Experience: $($row.experience_match)/10",
        "Location:   $($row.location_match)/10",
        "Seniority:  $($row.seniority_match)/10",
        "",
        "Matched: $matched",
        "Missing: $missing",
        "Flags  : $flags",
        "",
        "Reasoning: $($row.llm_summary)"
    ) -join "`r`n"
    [System.Windows.Forms.MessageBox]::Show($msg, "AI breakdown", "OK", "Information") | Out-Null
})

$menuCopyCover.Add_Click({
    $sel = $script:JobsList.SelectedItems | Select-Object -First 1
    if (-not $sel) { return }
    $row = Get-JobEnrichment -JobUrl ([string]$sel.Tag)
    if ($null -eq $row -or [string]::IsNullOrWhiteSpace([string]$row.cover_letter_draft)) {
        [System.Windows.Forms.MessageBox]::Show(
            "No cover letter draft yet for this job. Drafts are auto-generated for jobs scoring >= 7.",
            "Copy cover letter", "OK", "Information") | Out-Null
        return
    }
    [System.Windows.Forms.Clipboard]::SetText([string]$row.cover_letter_draft)
    Add-LogLine "Cover letter copied to clipboard for: $($row.title)"
    $script:StatusLabel.Text = "Cover letter copied to clipboard."
})

$exportCsvButton.Add_Click({ Export-JobsToCSV })

$script:ExcludeBox.Add_Leave({ Save-Settings-WithFeedback })

$script:TimeFilterBox.Add_SelectedIndexChanged({
    Update-TimeFilterUI
    Save-Settings-WithFeedback
    Refresh-ResultsForCurrentFilter
})

$script:CustomHoursBox.Add_ValueChanged({
    Save-Settings-WithFeedback
    Refresh-ResultsForCurrentFilter
})

# ── Auto-save all remaining settings fields ───────────────────────────────────
$script:KeywordsBox.Add_Leave(             { Save-Settings-WithFeedback })
$script:CountryBox.Add_Leave(              { Save-Settings-WithFeedback })
$script:LinkedInCheckBox.Add_CheckedChanged({ Save-Settings-WithFeedback })
$script:IndeedCheckBox.Add_CheckedChanged(  { Save-Settings-WithFeedback })
$script:HideAppliedCheckBox.Add_CheckedChanged({ Save-Settings-WithFeedback })
$script:IntervalBox.Add_ValueChanged(      { Save-Settings-WithFeedback })
$script:BrowserBox.Add_SelectedIndexChanged({ Save-Settings-WithFeedback })
$script:CookieBox.Add_Leave(               { Save-Settings-WithFeedback })
$script:TelegramTokenBox.Add_Leave(        { Save-Settings-WithFeedback })
$script:TelegramChatIdBox.Add_Leave(       { Save-Settings-WithFeedback })
$script:OllamaUrlBox.Add_Leave(            { Save-Settings-WithFeedback })
$script:MinAiScoreBox.Add_ValueChanged(    { Save-Settings-WithFeedback })
$script:UserProfileBox.Add_Leave(          { Save-Settings-WithFeedback })

$startButton.Add_Click({ Start-Monitoring })
$stopButton.Add_Click({ Stop-Monitoring })
$scanNowButton.Add_Click({
    try { Invoke-JobScan }
    catch {
        $script:StatusLabel.Text = "Status: error"
        Add-LogLine "Manual scan failed: $($_.Exception.Message)"
    }
})
$openJobButton.Add_Click({ Open-SelectedJob })

$browseCvButton.Add_Click({
    $dlg = New-Object System.Windows.Forms.OpenFileDialog
    $dlg.Title  = "Select your CV (PDF)"
    $dlg.Filter = "PDF files (*.pdf)|*.pdf|All files (*.*)|*.*"
    if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        $script:UserProfileBox.Text = $dlg.FileName
        Save-Settings
        Add-LogLine "CV set: $($dlg.FileName)"
        # Auto-start CV analysis whenever a new file is chosen
        $analyzeCvButton.PerformClick()
    }
})

$analyzeCvButton.Add_Click({
    $cvPath = $script:UserProfileBox.Text.Trim()
    if ([string]::IsNullOrWhiteSpace($cvPath)) {
        Add-LogLine "ERROR: No CV path set. Click 'Browse PDF...' first."
        return
    }
    if (-not $cvPath.ToLower().EndsWith(".pdf")) {
        Add-LogLine "ERROR: CV path must be a PDF file (got: $cvPath)"
        return
    }
    if (-not (Test-Path -LiteralPath $cvPath)) {
        Add-LogLine "ERROR: CV file not found: $cvPath"
        return
    }
    $analyzerPath = Join-Path $script:AppRoot "cloud\cv_analyzer.py"
    if (-not (Test-Path -LiteralPath $analyzerPath)) {
        Add-LogLine "ERROR: cloud\cv_analyzer.py not found at $analyzerPath"
        return
    }
    $settings    = Load-Settings
    $supabaseUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
    $supabaseKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($supabaseKey)) {
        Add-LogLine "ERROR: SupabaseUrl / SupabaseKey not set in settings.json"
        return
    }
    Add-LogLine "Analyzing CV: $(Split-Path $cvPath -Leaf) ..."
    $script:CvStatusLabel.Text      = "CV: analyzing..."
    $script:CvStatusLabel.ForeColor = [System.Drawing.Color]::FromArgb(240, 160, 0)
    $analyzeCvButton.Enabled        = $false
    $script:Form.Cursor             = [System.Windows.Forms.Cursors]::WaitCursor

    $script:CvAnalyzeJob = Start-Job -ScriptBlock {
        param($analyzer, $sUrl, $sKey, $cv)
        $env:SUPABASE_URL = $sUrl
        $env:SUPABASE_KEY = $sKey
        & python $analyzer --cv $cv 2>&1
    } -ArgumentList $analyzerPath, $supabaseUrl, $supabaseKey, $cvPath

    $script:CvAnalyzeTimer          = New-Object System.Windows.Forms.Timer
    $script:CvAnalyzeTimer.Interval = 1500
    $script:CvAnalyzeTimer.Add_Tick({
        $state = $script:CvAnalyzeJob.State
        $out   = Receive-Job -Job $script:CvAnalyzeJob
        foreach ($line in ($out -split "`n")) {
            $line = $line.Trim()
            if ($line -match "^CV_SKILL_COUNT=\d+$") {
                # Informational line handled by Update-CvStatusLabel — skip it
            } elseif ($line) {
                Add-LogLine $line
            }
        }
        if ($state -in @("Completed","Failed","Stopped")) {
            $script:CvAnalyzeTimer.Stop()
            $script:CvAnalyzeTimer.Dispose()
            Remove-Job -Job $script:CvAnalyzeJob -Force
            $analyzeCvButton.Enabled = $true
            $script:Form.Cursor      = [System.Windows.Forms.Cursors]::Default
            Add-LogLine "CV analysis complete."
            Update-CvStatusLabel
        }
    })
    $script:CvAnalyzeTimer.Start()
})

function Start-Enrichment {
    param([bool]$Silent = $false)
    if ($script:EnrichJob -and $script:EnrichJob.State -eq "Running") {
        if (-not $Silent) { Add-LogLine "AI enrichment is already running." }
        return
    }
    $enricherPath = Join-Path $script:AppRoot "cloud\enricher.py"
    if (-not (Test-Path -LiteralPath $enricherPath)) {
        Add-LogLine "ERROR: cloud\enricher.py not found at $enricherPath"
        return
    }
    $settings = Load-Settings
    $supabaseUrl = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseUrl" -DefaultValue "")
    $supabaseKey = [string](Get-SettingValue -SettingsObject $settings -Name "SupabaseKey" -DefaultValue "")
    if ([string]::IsNullOrWhiteSpace($supabaseUrl) -or [string]::IsNullOrWhiteSpace($supabaseKey)) {
        if (-not $Silent) { Add-LogLine "ERROR: SupabaseUrl / SupabaseKey not set in settings.json" }
        return
    }
    $ollamaUrl      = [string](Get-SettingValue -SettingsObject $settings -Name "OllamaUrl"       -DefaultValue "http://localhost:11434")
    $minScore       = [string](Get-SettingValue -SettingsObject $settings -Name "MinAiScore"      -DefaultValue "4")
    $linkedInCookie = [string](Get-SettingValue -SettingsObject $settings -Name "LinkedInCookie"  -DefaultValue "")
    $cvOrProfile    = [string](Get-SettingValue -SettingsObject $settings -Name "UserProfile"     -DefaultValue "")

    if (-not $Silent) {
        $cvLabel = "default profile"
        if (-not [string]::IsNullOrWhiteSpace($cvOrProfile)) {
            if ($cvOrProfile.ToLower().EndsWith(".pdf")) {
                $cvLabel = "CV: $(Split-Path $cvOrProfile -Leaf)"
            } elseif ($cvOrProfile.ToLower().Contains("linkedin.com/in/")) {
                $cvLabel = "LinkedIn profile"
            } else {
                $cvLabel = "text profile"
            }
        }
        Add-LogLine "Starting AI enrichment - profile source: $cvLabel"
    } else {
        Add-LogLine "Auto AI score: running enricher after cloud scan..."
    }

    $enrichAiButton.Enabled = $false
    $script:Form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
    $script:EnrichJob = Start-Job -ScriptBlock {
        param($enricher, $sUrl, $sKey, $ollama, $min, $cv, $cookie)
        $env:SUPABASE_URL    = $sUrl
        $env:SUPABASE_KEY    = $sKey
        $env:LINKEDIN_COOKIE = $cookie
        if ($cv) {
            & python $enricher --ollama $ollama --min-score $min --cv $cv 2>&1
        } else {
            & python $enricher --ollama $ollama --min-score $min 2>&1
        }
    } -ArgumentList $enricherPath, $supabaseUrl, $supabaseKey, $ollamaUrl, $minScore, $cvOrProfile, $linkedInCookie

    $script:EnrichTimer = New-Object System.Windows.Forms.Timer
    $script:EnrichTimer.Interval = 1500
    $script:EnrichTimer.Add_Tick({
        $state = $script:EnrichJob.State
        $out   = Receive-Job -Job $script:EnrichJob
        foreach ($line in ($out -split "`n")) {
            if ($line.Trim()) { Add-LogLine $line.Trim() }
        }
        if ($state -in @("Completed","Failed","Stopped")) {
            $script:EnrichTimer.Stop()
            $script:EnrichTimer.Dispose()
            Remove-Job -Job $script:EnrichJob -Force
            $enrichAiButton.Enabled = $true
            $script:Form.Cursor = [System.Windows.Forms.Cursors]::Default
            Add-LogLine "AI enrichment finished."
            Update-ScoresFromSupabase
        }
    })
    $script:EnrichTimer.Start()
}

$enrichAiButton.Add_Click({
    Save-Settings
    Start-Enrichment -Silent $false
})

$telegramTestButton.Add_Click({ Send-TelegramTest })
$sendVisibleButton.Add_Click({ Send-VisibleJobsToTelegram })
$importCookiesButton.Add_Click({ Import-CookiesToForm })

$script:Form.Add_FormClosing({
    Save-Settings

    # Stop every timer so none fires against disposed controls
    foreach ($t in @(
        $script:Timer,
        $script:WorkerCheckTimer,
        $script:TelegramPollTimer,
        $script:CloudCheckTimer,
        $script:AiLampTimer,
        $script:SettingsSaveTimer,
        $script:ScanPollTimer,
        $script:EnrichTimer,
        $script:CvAnalyzeTimer
    )) {
        if ($null -ne $t) { try { $t.Stop(); $t.Dispose() } catch {} }
    }

    # Stop any running background jobs
    foreach ($job in @($script:EnrichJob, $script:CvAnalyzeJob)) {
        if ($null -ne $job) { try { Stop-Job $job -ErrorAction SilentlyContinue; Remove-Job $job -Force -ErrorAction SilentlyContinue } catch {} }
    }

    # Stop the scan runspace if a scan is in progress
    if ($null -ne $script:ScanPS) {
        try { $script:ScanPS.Stop() }         catch {}
        try { $script:ScanPS.Dispose() }      catch {}
    }
    if ($null -ne $script:ScanHandle) {
        try { $script:ScanHandle.AsyncWaitHandle.Close() } catch {}
    }

    $script:NotifyIcon.Visible = $false
    try { $script:NotifyIcon.Dispose() } catch {}
    try { $script:HttpClient.Dispose()  } catch {}
})

$script:Form.Add_Shown({
    $script:WorkerCheckTimer.Start()
    $script:TelegramPollTimer.Start()
    $script:CloudCheckTimer.Start()
    Update-WorkerLamp
    try { Update-CloudLamp } catch {}
    # Load CV analysis status into the Automation card on startup
    try { Update-CvStatusLabel } catch {}
    # Auto-scan on startup so jobs appear without pressing Scan Now
    try { Invoke-JobScan } catch {}
})

Update-TimeFilterUI

# ── Resize anchoring ──────────────────────────────────────────────────────────
# Controls are anchored so the window fills properly when maximised.
# Left-column cards keep a fixed width; right-column cards grow rightward.
# jobsCard fills all remaining vertical space; logCard stays pinned to the bottom.
$_TL   = [System.Windows.Forms.AnchorStyles]::Top    -bor [System.Windows.Forms.AnchorStyles]::Left
$_TLR  = [System.Windows.Forms.AnchorStyles]::Top    -bor [System.Windows.Forms.AnchorStyles]::Left  -bor [System.Windows.Forms.AnchorStyles]::Right
$_BLR  = [System.Windows.Forms.AnchorStyles]::Bottom -bor [System.Windows.Forms.AnchorStyles]::Left  -bor [System.Windows.Forms.AnchorStyles]::Right
$_ALL  = [System.Windows.Forms.AnchorStyles]::Top    -bor [System.Windows.Forms.AnchorStyles]::Left  -bor [System.Windows.Forms.AnchorStyles]::Right -bor [System.Windows.Forms.AnchorStyles]::Bottom
$_TR   = [System.Windows.Forms.AnchorStyles]::Top    -bor [System.Windows.Forms.AnchorStyles]::Right

$headerPanel.Anchor  = $_TLR   # full-width header
$searchCard.Anchor   = $_TL    # left column — fixed width
$autoCard.Anchor     = $_TLR   # right column — grows with window
$cookieCard.Anchor   = $_TL    # left column — fixed width
$telegramCard.Anchor = $_TLR   # right column — grows with window
$statusPanel.Anchor  = $_TLR   # status bar — full width, stays at fixed Y
$jobsCard.Anchor     = $_ALL   # job list — grows to fill all available space
$logCard.Anchor      = $_BLR   # activity log — pinned to bottom, full width

# Inner controls that must resize with their parent cards
$script:JobsList.Anchor  = $_ALL   # job table fills the jobs card
$script:LogBox.Anchor    = $_ALL   # log text fills the log card
$exportCsvButton.Anchor  = $_TR    # Export CSV stays top-right of jobs card

# ── Assemble form ─────────────────────────────────────────────────────────────
$script:Form.Controls.AddRange(@(
    $headerPanel,
    $searchCard,
    $autoCard,
    $cookieCard,
    $telegramCard,
    $statusPanel,
    $jobsCard,
    $logCard
))

# Wire up the log callback used by shared scanning functions
$script:LogFunction = { param($m) Add-LogLine $m }

Add-LogLine "App ready. Click Start to begin monitoring LinkedIn and Indeed jobs."
$indeedScraperPath = Join-Path $script:AppRoot "indeed_scraper.py"
if (Test-Path -LiteralPath $indeedScraperPath) {
    Add-LogLine "Indeed scraper found. LinkedIn + Indeed scanning enabled."
} else {
    Add-LogLine "Indeed scraper not found. Run: pip install playwright && playwright install chromium"
}
if ($script:HasPrimedState) {
    Add-LogLine "Loaded $($script:SeenJobs.Count) seen job(s) from cache."
}
if (-not [string]::IsNullOrWhiteSpace([string](Get-SettingValue -SettingsObject $savedSettings -Name "LinkedInCookie" -DefaultValue ""))) {
    Add-LogLine "Saved LinkedIn signed-in cookie detected. Applied-job filtering can be used."
}

[void]$script:Form.ShowDialog()
