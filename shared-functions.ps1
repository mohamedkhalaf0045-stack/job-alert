Set-StrictMode -Version Latest

# Shared functions dot-sourced by both linkedin-job-alert.ps1 and linkedin-job-worker.ps1.
# Each calling script must set $script:HttpClient before any network calls, and
# $script:LogFunction (a scriptblock accepting a single string) before any job scanning.

function Convert-ToPlainText {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }

    $decoded = [System.Web.HttpUtility]::HtmlDecode($Value)
    $stripped = [regex]::Replace($decoded, "<.*?>", " ")
    return ([regex]::Replace($stripped, "\s+", " ")).Trim()
}

function Get-SettingValue {
    param(
        $SettingsObject,
        [string]$Name,
        $DefaultValue = $null
    )

    if (-not $SettingsObject) {
        return $DefaultValue
    }

    $property = $SettingsObject.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $DefaultValue
    }

    return $property.Value
}

function New-SearchUrl {
    param(
        [string]$Keyword,
        [string]$Location,
        [int]$Start,
        [int]$MaxHours = 72,
        [bool]$UseAuthenticatedSearch = $false  # kept for signature compat; ignored
    )

    $encodedKeyword  = [System.Uri]::EscapeDataString($Keyword)
    $encodedLocation = [System.Uri]::EscapeDataString($Location)
    $tpr = [Math]::Max($MaxHours, 1) * 3600   # LinkedIn uses seconds; f_TPR=r<secs>

    # Always use the guest API endpoint — it returns HTML fragments that
    # Parse-JobCards understands. The cookie (if present) is still sent by
    # Invoke-GetStringWithRetry, which lets LinkedIn mark applied jobs.
    # f_TPR restricts results to jobs posted within MaxHours — matching what
    # LinkedIn's own job-alert algorithm uses, and reducing bot-detection risk.
    return "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=$encodedKeyword&location=$encodedLocation&start=$Start&f_TPR=r$tpr"
}

function Invoke-GetStringWithRetry {
    param(
        [string]$Url,
        [string]$CookieHeader = "",
        [string]$Referer = ""
    )

    $lastError = $null
    foreach ($attempt in 1..3) {
        try {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
            $request.Headers.TryAddWithoutValidation("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8") | Out-Null
            $request.Headers.TryAddWithoutValidation("Accept-Language", "en-US,en;q=0.9") | Out-Null
            $request.Headers.TryAddWithoutValidation("Accept-Encoding", "gzip, deflate, br") | Out-Null
            $request.Headers.TryAddWithoutValidation("Connection", "keep-alive") | Out-Null
            $request.Headers.TryAddWithoutValidation("Upgrade-Insecure-Requests", "1") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Fetch-Dest", "document") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Fetch-Mode", "navigate") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Fetch-Site", "none") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Fetch-User", "?1") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Ch-Ua", '"Chromium";v="128", "Google Chrome";v="128", "Not-A.Brand";v="99"') | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Ch-Ua-Mobile", "?0") | Out-Null
            $request.Headers.TryAddWithoutValidation("Sec-Ch-Ua-Platform", '"Windows"') | Out-Null
            if (-not [string]::IsNullOrWhiteSpace($Referer)) {
                $request.Headers.TryAddWithoutValidation("Referer", $Referer) | Out-Null
            }
            if (-not [string]::IsNullOrWhiteSpace($CookieHeader)) {
                $request.Headers.TryAddWithoutValidation("Cookie", $CookieHeader) | Out-Null
            }

            $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode) {
                throw "LinkedIn returned HTTP $([int]$response.StatusCode)."
            }

            return $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
        catch {
            $lastError = $_
            if ($_.Exception.Message -match 'HTTP 429') { break }  # rate-limited — retrying immediately makes it worse
            if ($attempt -lt 3) {
                Start-Sleep -Seconds (1 * $attempt)
            }
        }
    }

    if ($lastError.Exception.Message -match 'HTTP 429') {
        throw "HTTP 429 rate-limited. Will retry on next scan interval."
    }
    throw "Request failed after 3 attempts. $($lastError.Exception.Message)"
}

function Parse-JobCards {
    param(
        [string]$Html,
        [string]$Keyword
    )

    $cards = [regex]::Matches(
        $Html,
        "<li\b.*?</li>",
        [System.Text.RegularExpressions.RegexOptions]::Singleline
    )

    $items = @()

    foreach ($card in $cards) {
        $chunk = $card.Value

        # URL — try old class name first, then newer variant, then any LI job URL
        $urlMatch = [regex]::Match($chunk, 'base-card__full-link[^>]+href="([^"]+)"')
        if (-not $urlMatch.Success) { $urlMatch = [regex]::Match($chunk, 'job-card-container__link[^>]+href="([^"]+)"') }
        if (-not $urlMatch.Success) { $urlMatch = [regex]::Match($chunk, 'href="(https://[^"]*linkedin\.com/jobs/view/[^"]+)"') }
        if (-not $urlMatch.Success) { continue }
        $rawUrl = [System.Web.HttpUtility]::HtmlDecode($urlMatch.Groups[1].Value)

        # Job ID — URN attribute, data attribute, or last number in the job URL path
        $idMatch = [regex]::Match($chunk, "jobPosting:(\d+)")
        if (-not $idMatch.Success) { $idMatch = [regex]::Match($chunk, 'data-job-id="(\d+)"') }
        if (-not $idMatch.Success) { $idMatch = [regex]::Match($rawUrl, '/jobs/view/[^/?#]*?-(\d+)(?:[/?#]|$)') }
        if (-not $idMatch.Success) { continue }

        # Title — try old class, then newer variant, then any <h3>
        $titleMatch = [regex]::Match($chunk, 'base-search-card__title">\s*(.*?)\s*</h3>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
        if (-not $titleMatch.Success) { $titleMatch = [regex]::Match($chunk, 'job-card-list__title[^"]*"[^>]*>\s*(.*?)\s*</a>', [System.Text.RegularExpressions.RegexOptions]::Singleline) }
        if (-not $titleMatch.Success) { $titleMatch = [regex]::Match($chunk, '<h3[^>]*>\s*(.*?)\s*</h3>', [System.Text.RegularExpressions.RegexOptions]::Singleline) }
        if (-not $titleMatch.Success) { continue }

        $companyMatch  = [regex]::Match($chunk, 'base-search-card__subtitle">\s*(.*?)\s*</h4>',  [System.Text.RegularExpressions.RegexOptions]::Singleline)
        if (-not $companyMatch.Success) { $companyMatch = [regex]::Match($chunk, 'job-card-container__company-name[^"]*"[^>]*>\s*(.*?)\s*</', [System.Text.RegularExpressions.RegexOptions]::Singleline) }
        $locationMatch = [regex]::Match($chunk, 'job-search-card__location">\s*(.*?)\s*</span>', [System.Text.RegularExpressions.RegexOptions]::Singleline)
        if (-not $locationMatch.Success) { $locationMatch = [regex]::Match($chunk, 'job-card-container__metadata-item[^"]*"[^>]*>\s*(.*?)\s*</', [System.Text.RegularExpressions.RegexOptions]::Singleline) }
        $timeMatch     = [regex]::Match($chunk, '<time[^>]*datetime="([^"]+)"[^>]*>(.*?)</time>',[System.Text.RegularExpressions.RegexOptions]::Singleline)

        $normalizedChunk = Convert-ToPlainText $chunk
        $applied = $normalizedChunk -match '(?i)\b(applied|application submitted|submitted|already applied)\b'

        # Extract posting age from <time> element; fall back to plain-text age string
        # ("1 week ago", "3 days ago") when the element is absent.  This prevents
        # LinkedIn's f_TPR-leaked old jobs from slipping through the age filter.
        $postedDateVal = ""
        $postedTextVal = ""
        if ($timeMatch.Success) {
            $postedDateVal = Convert-ToPlainText $timeMatch.Groups[1].Value
            $postedTextVal = Convert-ToPlainText $timeMatch.Groups[2].Value
        } else {
            $ageTextMatch = [regex]::Match(
                $normalizedChunk,
                '\b(\d+)\s+(second|minute|hour|day|week|month)s?\s+ago\b',
                [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
            )
            if ($ageTextMatch.Success) {
                $postedTextVal = $ageTextMatch.Value  # e.g. "1 week ago"
            }
        }

        $items += [pscustomobject]@{
            Id         = $idMatch.Groups[1].Value
            Keyword    = $Keyword
            Title      = Convert-ToPlainText $titleMatch.Groups[1].Value
            Company    = if ($companyMatch.Success) { Convert-ToPlainText $companyMatch.Groups[1].Value } else { "" }
            Location   = if ($locationMatch.Success) { Convert-ToPlainText $locationMatch.Groups[1].Value } else { "" }
            Url        = $rawUrl
            PostedDate = $postedDateVal
            PostedText = $postedTextVal
            IsApplied  = $applied
            Source     = "LinkedIn"
        }
    }

    return $items
}

function Get-PostedAgeHours {
    param($Job)

    $postedText = [string]$Job.PostedText
    $postedDate = [string]$Job.PostedDate

    if (-not [string]::IsNullOrWhiteSpace($postedText)) {
        if ($postedText -match '(?i)(\d+)\s*hour')   { return [double]$matches[1] }
        if ($postedText -match '(?i)(\d+)\s*minute') { return 0 }
        if ($postedText -match '(?i)(\d+)\s*second') { return 0 }
        if ($postedText -match '(?i)(\d+)\s*day')    { return ([double]$matches[1]) * 24 }
        if ($postedText -match '(?i)(\d+)\s*week')   { return ([double]$matches[1]) * 24 * 7 }
        if ($postedText -match '(?i)(\d+)\s*month')  { return ([double]$matches[1]) * 24 * 30 }
        if ($postedText -match '(?i)just now|just posted|today') { return 0 }
    }

    if (-not [string]::IsNullOrWhiteSpace($postedDate)) {
        try {
            $parsed = [DateTimeOffset]::Parse($postedDate, [System.Globalization.CultureInfo]::InvariantCulture)
            return [Math]::Max(0, ((Get-Date).ToUniversalTime() - $parsed.UtcDateTime).TotalHours)
        }
        catch {}
        try {
            $posted = [datetime]::Parse($postedDate)
            return [Math]::Max(0, ((Get-Date) - $posted).TotalHours)
        }
        catch {}
    }

    return 0  # timestamp unknown — include the job rather than silently drop it
}

function Get-LinkedInJobs {
    param(
        [string]$Keyword,
        [string]$Location,
        [string]$CookieHeader = "",
        [bool]$HideAppliedJobs = $false,
        [int]$MaxHours = 72
    )

    $allJobs = @()
    $useAuthenticatedSearch = -not [string]::IsNullOrWhiteSpace($CookieHeader)
    $sawPublicWrapper = $false

    $pageNum = 0
    foreach ($offset in @(0, 25)) {
        $pageNum++
        if ($script:LogFunction) {
            & $script:LogFunction "  LinkedIn '$Keyword' page $pageNum - fetching..."
        }
        $url  = New-SearchUrl -Keyword $Keyword -Location $Location -Start $offset -MaxHours $MaxHours -UseAuthenticatedSearch:$useAuthenticatedSearch
        $html = Invoke-GetStringWithRetry -Url $url -CookieHeader $CookieHeader -Referer "https://www.linkedin.com/jobs/"

        if ($useAuthenticatedSearch -and $html -match 'sign-in-modal' -and $html -match 'public_jobs') {
            $sawPublicWrapper = $true
        }

        $jobs = @(Parse-JobCards -Html $html -Keyword $Keyword)
        if ($script:LogFunction) {
            $liCount = ([regex]::Matches($html, '<li\b', [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)).Count
            & $script:LogFunction "  LinkedIn '$Keyword' page $pageNum - $(@($jobs).Count) listing(s) parsed (HTML: $($html.Length) chars, $liCount <li> elements)."
        }
        if (@($jobs).Count -eq 0) {
            break
        }

        if ($HideAppliedJobs) {
            $jobs = @($jobs | Where-Object { -not $_.IsApplied })
        }

        $allJobs += $jobs
        if ($pageNum -lt 2 -and @($jobs).Count -gt 0) {
            if ($script:LogFunction) {
                & $script:LogFunction "  LinkedIn '$Keyword' page $pageNum - waiting 2.5s before next page..."
            }
            Start-Sleep -Milliseconds 2500  # pace requests to avoid LinkedIn 429 rate-limiting
        }
    }

    if ($useAuthenticatedSearch -and $sawPublicWrapper -and $script:LogFunction) {
        & $script:LogFunction "LinkedIn returned the public jobs page even with the saved cookie. Applied-job filtering may not work reliably for this scan."
    }

    return @($allJobs | Group-Object Id | ForEach-Object { $_.Group[0] })
}

function Format-TelegramMessage {
    param($Job)

    $source = if ($Job.PSObject.Properties["Source"] -and -not [string]::IsNullOrWhiteSpace([string]$Job.Source)) {
        [string]$Job.Source
    } else {
        "LinkedIn"
    }

    $parts = @(
        "New $source job",
        $Job.Title,
        $Job.Company,
        $Job.Location
    )

    if (-not [string]::IsNullOrWhiteSpace($Job.PostedText)) {
        $parts += "Posted: $($Job.PostedText)"
    }
    elseif (-not [string]::IsNullOrWhiteSpace($Job.PostedDate)) {
        $parts += "Posted: $($Job.PostedDate)"
    }

    $parts += $Job.Url
    return ($parts -join "`n")
}

function Send-TelegramMessage {
    param(
        [string]$BotToken,
        [string]$ChatId,
        [string]$Message,
        [scriptblock]$LogCallback = $null
    )

    if ([string]::IsNullOrWhiteSpace($BotToken) -or [string]::IsNullOrWhiteSpace($ChatId)) {
        return $false
    }

    $url = "https://api.telegram.org/bot$BotToken/sendMessage"
    $payload = @{
        chat_id                  = $ChatId
        text                     = $Message
        disable_web_page_preview = $false
    } | ConvertTo-Json

    $lastError = $null
    foreach ($attempt in 1..3) {
        try {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $url)
            $request.Content = New-Object System.Net.Http.StringContent($payload, [System.Text.Encoding]::UTF8, "application/json")
            $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
            if (-not $response.IsSuccessStatusCode) {
                $body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                throw "Telegram returned HTTP $([int]$response.StatusCode): $body"
            }

            return $true
        }
        catch {
            $lastError = $_
            if ($attempt -lt 3) {
                Start-Sleep -Seconds $attempt
            }
        }
    }

    if ($LogCallback) {
        & $LogCallback "Telegram send failed: $($lastError.Exception.Message)"
    }

    return $false
}

function Get-TelegramUpdates {
    param(
        [string]$BotToken,
        [long]$Offset = 0
    )

    if ([string]::IsNullOrWhiteSpace($BotToken)) { return @() }

    $url = "https://api.telegram.org/bot$BotToken/getUpdates?offset=$Offset&timeout=0"
    try {
        $request  = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $url)
        $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { return @() }
        $json = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        if (-not $json.ok) { return @() }
        return @($json.result)
    }
    catch { return @() }
}

function Read-TelegramOffset {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return 0L }
    try { return [long]((Get-Content -LiteralPath $Path -Raw).Trim()) } catch { return 0L }
}

function Save-TelegramOffset {
    param([string]$Path, [long]$Offset)
    Set-Content -LiteralPath $Path -Value $Offset -Encoding ASCII
}

function Get-TelegramCommandText {
    param([string]$Raw)
    return ($Raw -replace '@\S+', '').ToLower().Trim()
}

function Get-IndeedJobs {
    param(
        [string]$Keyword,
        [string]$Location,
        [int]$MaxHours = 24
    )

    $scraperPath = Join-Path $script:AppRoot "indeed_scraper.py"
    if (-not (Test-Path -LiteralPath $scraperPath)) {
        if ($script:LogFunction) {
            & $script:LogFunction "Indeed: scraper not found at $scraperPath"
        }
        return @()
    }

    try {
        $jsonOutput = & python $scraperPath --keyword $Keyword --location $Location --max-hours $MaxHours 2>$null
    }
    catch {
        if ($script:LogFunction) {
            & $script:LogFunction "Indeed: failed to run scraper for '$Keyword': $($_.Exception.Message)"
        }
        return @()
    }

    if ([string]::IsNullOrWhiteSpace($jsonOutput)) {
        return @()
    }

    try {
        $data = $jsonOutput | ConvertFrom-Json
    }
    catch {
        if ($script:LogFunction) {
            & $script:LogFunction "Indeed: scraper output was not valid JSON for '$Keyword'"
        }
        return @()
    }

    if ($data.PSObject.Properties -and $data.PSObject.Properties["error"]) {
        if ($script:LogFunction) {
            & $script:LogFunction "Indeed scraper error: $($data.error)"
        }
        return @()
    }

    $parsed = @($data | ForEach-Object {
        [pscustomobject]@{
            Id         = [string]$_.Id
            Keyword    = [string]$_.Keyword
            Title      = [string]$_.Title
            Company    = [string]$_.Company
            Location   = [string]$_.Location
            Url        = [string]$_.Url
            PostedDate = [string]$_.PostedDate
            PostedText = [string]$_.PostedText
            IsApplied  = $false
            Source     = "Indeed"
        }
    })
    return @($parsed | Group-Object Id | ForEach-Object { $_.Group[0] })
}

function Get-JoobleJobs {
    param(
        [string]$Keyword,
        [string]$Location,
        [string]$ApiKey
    )

    if ([string]::IsNullOrWhiteSpace($ApiKey)) {
        if ($script:LogFunction) {
            & $script:LogFunction "Jooble: API key not set. Add JoobleApiKey to settings.json (free at https://jooble.org/api)."
        }
        return @()
    }

    $allJobs = @()

    foreach ($page in @(1, 2)) {
        $url  = "https://jooble.org/api/$ApiKey"
        $body = [pscustomobject]@{
            keywords = $Keyword
            location = $Location
            page     = "$page"
        } | ConvertTo-Json

        try {
            $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Post, $url)
            $request.Content = New-Object System.Net.Http.StringContent($body, [System.Text.Encoding]::UTF8, "application/json")
            $response = $script:HttpClient.SendAsync($request).GetAwaiter().GetResult()

            if (-not $response.IsSuccessStatusCode) {
                $code = [int]$response.StatusCode
                if (($code -eq 401 -or $code -eq 403) -and $script:LogFunction) {
                    & $script:LogFunction "Jooble: invalid API key (HTTP $code). Check JoobleApiKey in settings.json."
                }
                break
            }

            $json = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json
        }
        catch {
            if ($script:LogFunction) {
                & $script:LogFunction "Jooble fetch failed for '$Keyword': $($_.Exception.Message)"
            }
            break
        }

        $results = @($json.jobs)
        if ($results.Count -eq 0) { break }

        foreach ($r in $results) {
            $jobUrl = [string]$r.link
            if ([string]::IsNullOrWhiteSpace($jobUrl)) { continue }

            $allJobs += [pscustomobject]@{
                Id         = "jooble-$([string]$r.id)"
                Keyword    = $Keyword
                Title      = Convert-ToPlainText ([string]$r.title)
                Company    = Convert-ToPlainText ([string]$r.company)
                Location   = Convert-ToPlainText ([string]$r.location)
                Url        = $jobUrl
                PostedDate = [string]$r.updated
                PostedText = ""
                IsApplied  = $false
                Source     = "Jooble"
            }
        }

        Start-Sleep -Milliseconds 300
    }

    return @($allJobs | Group-Object Id | ForEach-Object { $_.Group[0] })
}

function Prune-SeenJobs {
    param(
        [hashtable]$SeenJobs,
        [int]$MaxAgeDays = 60
    )

    $cutoff = (Get-Date).AddDays(-$MaxAgeDays)
    $pruned = @{}

    foreach ($key in $SeenJobs.Keys) {
        try {
            $seen = [datetime]::Parse($SeenJobs[$key])
            if ($seen -gt $cutoff) {
                $pruned[$key] = $SeenJobs[$key]
            }
        }
        catch {
            $pruned[$key] = $SeenJobs[$key]
        }
    }

    return $pruned
}
