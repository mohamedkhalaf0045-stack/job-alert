Set-StrictMode -Version Latest

$script:JobDatabasePath = Join-Path $script:AppRoot "jobs.db"
$script:JobDatabaseSqliteLoaded = $false

function Initialize-JobDatabaseProvider {
    if ($script:JobDatabaseSqliteLoaded) {
        return
    }

    $candidatePaths = @(
        (Join-Path $script:AppRoot "System.Data.SQLite.dll"),  # bundled alongside app (preferred)
        "C:\Program Files\Google\Play Games\current\service\System.Data.SQLite.dll",
        "C:\Program Files\Google\Play Games\26.4.613.1\service\System.Data.SQLite.dll",
        "C:\Program Files\Dell\SupportAssistAgent\CDM\System.Data.SQLite.dll"
    )

    foreach ($path in $candidatePaths) {
        if (Test-Path -LiteralPath $path) {
            Add-Type -Path $path -ErrorAction SilentlyContinue
            $script:JobDatabaseSqliteLoaded = $true
            return
        }
    }

    throw "Could not load System.Data.SQLite.dll. Download it from https://system.data.sqlite.org/index.html/doc/trunk/www/downloads.wiki and place System.Data.SQLite.dll in the app folder ($script:AppRoot)."
}

function Open-JobDatabaseConnection {
    Initialize-JobDatabaseProvider

    $connection = New-Object System.Data.SQLite.SQLiteConnection("Data Source=$script:JobDatabasePath;Version=3;")
    $connection.Open()
    return $connection
}

function Initialize-JobDatabase {
    $connection = Open-JobDatabaseConnection
    try {
        $command = $connection.CreateCommand()
        $command.CommandText = @"
create table if not exists jobs (
    job_id text primary key,
    title text not null,
    company text not null,
    location text not null,
    url text not null unique,
    date_posted text,
    date_collected text not null,
    source text not null,
    status text not null default 'new',
    telegram_sent_at text
);

create index if not exists idx_jobs_url on jobs(url);
create index if not exists idx_jobs_date_posted on jobs(date_posted);
create index if not exists idx_jobs_status on jobs(status);
create index if not exists idx_jobs_title_company_location on jobs(title, company, location);
"@
        [void]$command.ExecuteNonQuery()

        # Migrate existing databases that lack the telegram_sent_at column
        $command.CommandText = "ALTER TABLE jobs ADD COLUMN telegram_sent_at text"
        try { [void]$command.ExecuteNonQuery() } catch {}
    }
    finally {
        $connection.Dispose()
    }
}

function Get-TelegramSentUrls {
    $conn = Open-JobDatabaseConnection
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "select url from jobs where telegram_sent_at is not null"
        $reader = $cmd.ExecuteReader()
        $urls = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
        try {
            while ($reader.Read()) {
                [void]$urls.Add([string]$reader["url"])
            }
        }
        finally {
            $reader.Close()
            $cmd.Dispose()
        }
        return $urls
    }
    finally {
        $conn.Dispose()
    }
}

function Set-JobTelegramSent {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) { return }

    $canonicalUrl = Get-CanonicalJobUrl -Url $Url
    if ([string]::IsNullOrWhiteSpace($canonicalUrl)) { return }

    $conn = Open-JobDatabaseConnection
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = "update jobs set telegram_sent_at = @now where url = @url"
        [void]$cmd.Parameters.AddWithValue("@now", (Get-Date).ToUniversalTime().ToString("o"))
        [void]$cmd.Parameters.AddWithValue("@url", $canonicalUrl)
        [void]$cmd.ExecuteNonQuery()
        $cmd.Dispose()
    }
    finally {
        $conn.Dispose()
    }
}

function Normalize-JobField {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ""
    }

    return ([regex]::Replace($Value.Trim(), "\s+", " "))
}

function Get-CanonicalJobUrl {
    param([string]$Url)

    if ([string]::IsNullOrWhiteSpace($Url)) {
        return ""
    }

    try {
        $uri = [System.Uri]$Url
        $builder = [System.UriBuilder]::new($uri)
        $builder.Query = ""
        $builder.Fragment = ""
        return $builder.Uri.AbsoluteUri.TrimEnd("/")
    }
    catch {
        return ""
    }
}

function Resolve-JobPostedDateIso {
    param($Job)

    $postedDate = Normalize-JobField ([string]$Job.PostedDate)
    $postedText = Normalize-JobField ([string]$Job.PostedText)
    $now = (Get-Date).ToUniversalTime()

    if (-not [string]::IsNullOrWhiteSpace($postedDate)) {
        try {
            return ([DateTimeOffset]::Parse($postedDate, [System.Globalization.CultureInfo]::InvariantCulture)).UtcDateTime.ToString("o")
        }
        catch {}
        try {
            return ([datetime]::Parse($postedDate)).ToUniversalTime().ToString("o")
        }
        catch {}
    }

    if (-not [string]::IsNullOrWhiteSpace($postedText)) {
        if ($postedText -match '(?i)(\d+)\s*minute') {
            return $now.AddMinutes(-1 * [int]$matches[1]).ToString("o")
        }
        if ($postedText -match '(?i)(\d+)\s*hour') {
            return $now.AddHours(-1 * [int]$matches[1]).ToString("o")
        }
        if ($postedText -match '(?i)(\d+)\s*day') {
            return $now.AddDays(-1 * [int]$matches[1]).ToString("o")
        }
        if ($postedText -match '(?i)(\d+)\s*week') {
            return $now.AddDays(-7 * [int]$matches[1]).ToString("o")
        }
        if ($postedText -match '(?i)just now|today') {
            return $now.ToString("o")
        }
    }

    return ""
}

function Get-JobDatabaseId {
    param($Job)

    $jobId = Normalize-JobField ([string]$Job.Id)
    if (-not [string]::IsNullOrWhiteSpace($jobId)) {
        return $jobId
    }

    $fallback = "{0}|{1}|{2}" -f (Normalize-JobField $Job.Title), (Normalize-JobField $Job.Company), (Normalize-JobField $Job.Location)
    if ([string]::IsNullOrWhiteSpace($fallback.Replace("|", ""))) {
        return ""
    }

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($fallback.ToLowerInvariant())
        $hash = $sha.ComputeHash($bytes)
        return ([System.BitConverter]::ToString($hash)).Replace("-", "").ToLowerInvariant()
    }
    finally {
        $sha.Dispose()
    }
}

function Get-JobDatabaseRecord {
    param(
        [System.Data.SQLite.SQLiteConnection]$Connection,
        [string]$JobId,
        [string]$Url
    )

    $command = $Connection.CreateCommand()
    $command.CommandText = "select job_id, title, company, location, url, date_posted, date_collected, source, status from jobs where job_id = @job_id or url = @url limit 1"
    [void]$command.Parameters.AddWithValue("@job_id", $JobId)
    [void]$command.Parameters.AddWithValue("@url", $Url)

    $reader = $command.ExecuteReader()
    try {
        if (-not $reader.Read()) {
            return $null
        }

        return [pscustomobject]@{
            job_id         = [string]$reader["job_id"]
            title          = [string]$reader["title"]
            company        = [string]$reader["company"]
            location       = [string]$reader["location"]
            url            = [string]$reader["url"]
            date_posted    = [string]$reader["date_posted"]
            date_collected = [string]$reader["date_collected"]
            source         = [string]$reader["source"]
            status         = [string]$reader["status"]
        }
    }
    finally {
        $reader.Close()
        $reader.Dispose()
        $command.Dispose()
    }
}

function Upsert-JobRecord {
    param(
        [System.Data.SQLite.SQLiteConnection]$Connection,
        $Job,
        [string]$Source = "LinkedIn"
    )

    $jobId = Get-JobDatabaseId -Job $Job
    $url = Get-CanonicalJobUrl -Url ([string]$Job.Url)
    if ([string]::IsNullOrWhiteSpace($jobId) -or [string]::IsNullOrWhiteSpace($url)) {
        return "invalid"
    }

    $record = [ordered]@{
        job_id         = $jobId
        title          = Normalize-JobField ([string]$Job.Title)
        company        = Normalize-JobField ([string]$Job.Company)
        location       = Normalize-JobField ([string]$Job.Location)
        url            = $url
        date_posted    = Resolve-JobPostedDateIso -Job $Job
        date_collected = (Get-Date).ToUniversalTime().ToString("o")
        source         = Normalize-JobField $Source
        status         = if ($Job.PSObject.Properties["Status"] -and -not [string]::IsNullOrWhiteSpace([string]$Job.Status)) { [string]$Job.Status } else { "new" }
    }

    if ([string]::IsNullOrWhiteSpace($record.title) -or [string]::IsNullOrWhiteSpace($record.company)) {
        return "invalid"
    }

    $existing = Get-JobDatabaseRecord -Connection $Connection -JobId $record.job_id -Url $record.url

    if ($null -eq $existing) {
        $command = $Connection.CreateCommand()
        $command.CommandText = @"
insert into jobs (job_id, title, company, location, url, date_posted, date_collected, source, status)
values (@job_id, @title, @company, @location, @url, @date_posted, @date_collected, @source, @status)
"@
        foreach ($key in $record.Keys) {
            [void]$command.Parameters.AddWithValue("@$key", $record[$key])
        }
        [void]$command.ExecuteNonQuery()
        $command.Dispose()
        return "inserted"
    }

    $changed = (
        $existing.title -ne $record.title -or
        $existing.company -ne $record.company -or
        $existing.location -ne $record.location -or
        $existing.url -ne $record.url -or
        $existing.date_posted -ne $record.date_posted -or
        $existing.source -ne $record.source -or
        $existing.status -ne $record.status
    )

    if (-not $changed) {
        return "seen"
    }

    $command = $Connection.CreateCommand()
    $command.CommandText = @"
update jobs
set
    title = @title,
    company = @company,
    location = @location,
    url = @url,
    date_posted = @date_posted,
    date_collected = @date_collected,
    source = @source,
    status = @status
where job_id = @existing_job_id
"@
    foreach ($key in $record.Keys) {
        [void]$command.Parameters.AddWithValue("@$key", $record[$key])
    }
    [void]$command.Parameters.AddWithValue("@existing_job_id", $existing.job_id)
    [void]$command.ExecuteNonQuery()
    $command.Dispose()

    return "updated"
}

function Get-RecentJobsSummary {
    param([int]$MaxJobs = 10, [int]$LastHours = 24)

    Initialize-JobDatabase
    $conn = Open-JobDatabaseConnection
    try {
        $cmd = $conn.CreateCommand()
        $cmd.CommandText = @"
select title, company, location, url
from jobs
where date_collected >= @since
order by date_collected desc
limit @max
"@
        [void]$cmd.Parameters.AddWithValue("@since", (Get-Date).AddHours(-$LastHours).ToUniversalTime().ToString("o"))
        [void]$cmd.Parameters.AddWithValue("@max",   $MaxJobs)
        $reader = $cmd.ExecuteReader()
        $lines = @("Recent jobs (last $LastHours h):")
        $n = 0
        try {
            while ($reader.Read()) {
                $n++
                $lines += "$n. $([string]$reader['title']) @ $([string]$reader['company'])"
                $lines += "   $([string]$reader['location'])"
                $lines += "   $([string]$reader['url'])"
            }
        } finally {
            $reader.Close()
            $cmd.Dispose()
        }
        if ($n -eq 0) { return "No jobs found in the last $LastHours hours." }
        return ($lines -join "`n")
    } finally {
        $conn.Dispose()
    }
}

function Sync-JobsToDatabase {
    param(
        $Jobs,
        [string]$Source = "LinkedIn"
    )

    Initialize-JobDatabase
    $connection = Open-JobDatabaseConnection
    $summary = [ordered]@{
        inserted = 0
        updated  = 0
        seen     = 0
        invalid  = 0
    }

    try {
        foreach ($job in @($Jobs)) {
            $result = Upsert-JobRecord -Connection $connection -Job $job -Source $Source
            if ($summary.Contains($result)) {
                $summary[$result] += 1
            }
        }
    }
    finally {
        $connection.Dispose()
    }

    return [pscustomobject]$summary
}
