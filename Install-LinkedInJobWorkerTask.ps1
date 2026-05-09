Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$appRoot = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$workerScript = Join-Path $appRoot "linkedin-job-worker.ps1"
$taskName = "LinkedIn UAE Job Worker"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$workerScript`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output "Installed scheduled task: $taskName"
