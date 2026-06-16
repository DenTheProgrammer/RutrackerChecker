$ErrorActionPreference = "Stop"
$Startup = [Environment]::GetFolderPath("Startup")
$ShortcutPath = Join-Path $Startup "RutrackerChecker Background.lnk"

if (Test-Path $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath
    Write-Host "Removed Startup shortcut:"
    Write-Host $ShortcutPath
} else {
    Write-Host "Startup shortcut was not installed."
}

$Root = $PSScriptRoot
$Processes = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -like "*background_loop.py*" -and
        $_.CommandLine -like "*$Root*"
    }

foreach ($Process in $Processes) {
    Stop-Process -Id $Process.ProcessId -Force
    Write-Host "Stopped background process $($Process.ProcessId)."
}
