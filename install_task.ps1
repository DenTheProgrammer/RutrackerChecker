param(
    [int]$IntervalMinutes = 30,
    [string]$TaskName = "RutrackerChecker"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = $null

try {
    $Python = (Get-Command python -ErrorAction Stop).Source
} catch {
    if (Test-Path $BundledPython) {
        $Python = $BundledPython
    }
}

if (-not $Python) {
    throw "Python was not found. Install Python 3.11+ or edit this script to point to python.exe."
}

if ($IntervalMinutes -lt 5) {
    throw "Use IntervalMinutes >= 5 to avoid hammering RuTracker."
}

$Script = Join-Path $Root "check_once.py"
if (-not (Test-Path $Script)) {
    throw "check_once.py was not found: $Script"
}

$registered = $false

try {
    $Action = New-ScheduledTaskAction `
        -Execute $Python `
        -Argument "`"$Script`"" `
        -WorkingDirectory $Root

    $AtLogon = New-ScheduledTaskTrigger -AtLogOn
    $Repeating = New-ScheduledTaskTrigger `
        -Once `
        -At (Get-Date).AddMinutes(1) `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)

    $Settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger @($AtLogon, $Repeating) `
        -Settings $Settings `
        -Description "Checks RuTracker saved queries and shows a Windows notification when new matching releases appear." `
        -Force | Out-Null

    Start-ScheduledTask -TaskName $TaskName
    $registered = $true
} catch {
    Write-Host "Register-ScheduledTask failed, trying schtasks.exe fallback..."
    $TaskCommand = "`"$Python`" `"$Script`""
    $LogonTaskName = "$TaskName-AtLogon"

    & schtasks.exe /Create /TN $TaskName /TR $TaskCommand /SC MINUTE /MO $IntervalMinutes /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed to create repeating task '$TaskName'."
    }

    & schtasks.exe /Create /TN $LogonTaskName /TR $TaskCommand /SC ONLOGON /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "schtasks.exe failed to create logon task '$LogonTaskName'."
    }

    & schtasks.exe /Run /TN $TaskName | Out-Null
    $registered = $true
}

if (-not $registered) {
    throw "Scheduled task was not installed."
}

Write-Host "Installed scheduled task '$TaskName'."
Write-Host "Also installed '$TaskName-AtLogon' when schtasks.exe fallback is used."
Write-Host "Interval: every $IntervalMinutes minute(s), plus at logon."
Write-Host "Logs: $(Join-Path $Root 'data\checks.log')"
