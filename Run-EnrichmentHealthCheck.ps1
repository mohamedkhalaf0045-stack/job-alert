# Run-EnrichmentHealthCheck.ps1
# Diagnostic: verify Ollama + profile + enricher all work end-to-end.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-EnrichmentHealthCheck.ps1

[CmdletBinding()]
param(
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$script:AppRoot      = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$script:SettingsPath = Join-Path $script:AppRoot "settings.json"
$script:EnricherPy   = Join-Path $script:AppRoot "cloud\enricher.py"
$script:HealthLog    = Join-Path $script:AppRoot "enricher-health.log"

$results = [System.Collections.Generic.List[string]]::new()
$failed  = $false

function Write-Step {
    param([string]$Tag, [string]$Message)
    $ts   = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] [$Tag] $Message"
    if (-not $Quiet) { Write-Host $line }
    $results.Add($line) | Out-Null
}

function Record-Pass { param([string]$What) Write-Step "PASS" $What }
function Record-Fail { param([string]$What) Write-Step "FAIL" $What; $script:failed = $true }
function Record-Info { param([string]$What) Write-Step "INFO" $What }

Write-Step "START" "Enrichment health check beginning"

# 1. Settings file
if (-not (Test-Path -LiteralPath $script:SettingsPath)) {
    Record-Fail "settings.json not found at $script:SettingsPath"
    $settings = $null
} else {
    try {
        $settings = Get-Content -LiteralPath $script:SettingsPath -Raw | ConvertFrom-Json
        Record-Pass "settings.json loaded"
    } catch {
        Record-Fail ("settings.json present but invalid JSON: " + $_.Exception.Message)
        $settings = $null
    }
}

# 2. Ollama binary present
$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($null -eq $ollamaCmd) {
    Record-Fail "'ollama' command not found in PATH. Install from https://ollama.com/download"
} else {
    Record-Pass ("ollama binary found at " + $ollamaCmd.Source)

    try {
        $listing = & ollama list 2>&1
        $listing | ForEach-Object { Record-Info ("  " + $_) }
        $hasLlama = ($listing | Out-String) -match "llama3"
        if ($hasLlama) {
            Record-Pass "A llama3-family model is installed"
        } else {
            Record-Fail "No llama3 model installed. Run: ollama pull llama3.1:latest"
        }
    } catch {
        Record-Fail ("ollama list failed: " + $_.Exception.Message)
    }
}

# 3. Ollama daemon reachable
$ollamaUrl = "http://localhost:11434"
if ($settings -and ($settings.PSObject.Properties.Name -contains "OllamaUrl") -and -not [string]::IsNullOrWhiteSpace($settings.OllamaUrl)) {
    $ollamaUrl = ([string]$settings.OllamaUrl).TrimEnd("/")
}
try {
    $tags = Invoke-RestMethod -Uri ($ollamaUrl + "/api/tags") -TimeoutSec 5 -Method Get
    Record-Pass ("Ollama daemon reachable at " + $ollamaUrl + " (models: " + $tags.models.Count + ")")
} catch {
    Record-Fail ("Cannot reach Ollama daemon at " + $ollamaUrl + " - is 'ollama serve' running? " + $_.Exception.Message)
}

# 4. Python + enricher.py present
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonCmd) {
    Record-Fail "'python' not found in PATH"
} else {
    try {
        $pyVersion = (& python --version 2>&1) -join ""
        Record-Pass ("python found: " + $pyVersion)
    } catch {
        Record-Info ("python --version returned: " + $_.Exception.Message)
    }
}

if (-not (Test-Path -LiteralPath $script:EnricherPy)) {
    Record-Fail ("cloud\enricher.py not found at " + $script:EnricherPy)
}

# 5. Required Python packages
if ($pythonCmd -and (Test-Path -LiteralPath $script:EnricherPy)) {
    $pkgCheck = (& python -c "import requests, supabase; print('OK')" 2>&1 | Out-String).Trim()
    if ($pkgCheck.EndsWith("OK")) {
        Record-Pass "Required Python packages (requests, supabase) importable"
    } else {
        Record-Fail ("Missing Python packages. Run: pip install -r cloud/requirements.txt`n" + $pkgCheck)
    }
}

# 6. End-to-end test: invoke enricher in --health-check mode
if (-not $failed -and (Test-Path -LiteralPath $script:EnricherPy)) {
    Record-Info "Invoking enricher.py --health-check (will score one job if any are unscored) ..."

    if ($settings -and ($settings.PSObject.Properties.Name -contains "LinkedInCookie")) {
        $env:LINKEDIN_COOKIE = [string]$settings.LinkedInCookie
    }
    if ($settings -and ($settings.PSObject.Properties.Name -contains "SupabaseUrl")) {
        $env:SUPABASE_URL = [string]$settings.SupabaseUrl
    }
    if ($settings -and ($settings.PSObject.Properties.Name -contains "SupabaseKey")) {
        $env:SUPABASE_KEY = [string]$settings.SupabaseKey
    }

    $stdout = & python $script:EnricherPy --health-check --ollama $ollamaUrl 2>&1
    $exitCode = $LASTEXITCODE
    foreach ($line in $stdout) { Record-Info ("  " + $line) }

    if ($exitCode -eq 0) {
        Record-Pass "Enricher health-check returned exit 0"
    } elseif ($exitCode -eq 2) {
        Record-Fail "Enricher health-check FAILED - see lines above for the root cause"
    } else {
        Record-Fail ("Enricher health-check returned unexpected exit code " + $exitCode)
    }
}

# 7. Summary
if ($failed) {
    Write-Step "RESULT" ("FAIL - one or more checks failed. See " + $script:HealthLog + " for full log.")
} else {
    Write-Step "RESULT" "OK - all checks passed."
}

$results | Set-Content -LiteralPath $script:HealthLog -Encoding UTF8

if ($failed) { exit 1 } else { exit 0 }
