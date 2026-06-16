$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Startup = [Environment]::GetFolderPath("Startup")
$Target = Join-Path $Root "start_background.vbs"

if (-not (Test-Path $Target)) {
    throw "start_background.vbs was not found: $Target"
}

$ShortcutPath = Join-Path $Startup "RutrackerChecker Background.lnk"
$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Target
$Shortcut.WorkingDirectory = $Root
$Shortcut.Description = "Starts RuTracker Checker background loop"
$Shortcut.Save()

Start-Process -FilePath "wscript.exe" -ArgumentList "`"$Target`"" -WindowStyle Hidden

Write-Host "Installed Startup shortcut:"
Write-Host $ShortcutPath
Write-Host "Background checker started."
