param(
    [string]$TaskName = "RutrackerChecker"
)

$ErrorActionPreference = "Stop"

foreach ($Name in @($TaskName, "$TaskName-AtLogon")) {
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
        Write-Host "Removed scheduled task '$Name'."
        continue
    }

    & schtasks.exe /Query /TN $Name *> $null
    if ($LASTEXITCODE -eq 0) {
        & schtasks.exe /Delete /TN $Name /F | Out-Null
        Write-Host "Removed scheduled task '$Name'."
    } else {
        Write-Host "Scheduled task '$Name' was not installed."
    }
}
