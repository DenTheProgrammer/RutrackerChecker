$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$AssetsDir = Join-Path $Root "assets"
$BaseIconPath = Join-Path $AssetsDir "app-icon.png"
$DataDir = Join-Path $Root "data"
$RuntimeStatusPath = Join-Path $DataDir "runtime_status.json"
$AppExe = Join-Path $Root "RutrackerChecker.exe"
$AppUrl = "http://127.0.0.1:9876/"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = $null
$TrayMutexName = "Local\RutrackerCheckerTray"
$TrayMutexCreated = $false
$TrayMutex = $null

function Get-RootProcessesByPattern {
    param([string[]]$Patterns)
    return @(Get-CimInstance Win32_Process |
        Where-Object {
            if (-not $_.CommandLine -or $_.ProcessId -eq $PID) {
                return $false
            }
            if ($_.CommandLine -notlike "*$Root*") {
                return $false
            }
            foreach ($Pattern in $Patterns) {
                if ($_.CommandLine -like $Pattern) {
                    return $true
                }
            }
            return $false
        })
}

function Stop-RootProcessesByPattern {
    param([string[]]$Patterns)
    foreach ($Process in (Get-RootProcessesByPattern $Patterns)) {
        try {
            Stop-Process -Id $Process.ProcessId -Force
        } catch {
        }
    }
}

function New-TrayMutex {
    $script:TrayMutexCreated = $false
    $script:TrayMutex = New-Object System.Threading.Mutex($true, $TrayMutexName, [ref]$script:TrayMutexCreated)
}

New-TrayMutex
if (-not $TrayMutexCreated) {
    $TrayMutex.Dispose()
    Stop-RootProcessesByPattern @("*start-tray.ps1*")
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 150
        New-TrayMutex
        if ($TrayMutexCreated) {
            break
        }
        $TrayMutex.Dispose()
    }
    if (-not $TrayMutexCreated) {
        exit 0
    }
}

if (-not ("NativeIconMethods" -as [type])) {
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class NativeIconMethods {
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool DestroyIcon(IntPtr hIcon);
}
"@
}

function Find-Python {
    try {
        return (Get-Command python -ErrorAction Stop).Source
    } catch {
        if (Test-Path $BundledPython) {
            return $BundledPython
        }
    }
    return $null
}

function Test-ProcessCommandLine {
    param([string]$Pattern)
    return (Get-RootProcessesByPattern @($Pattern)).Count -gt 0
}

$Python = Find-Python
if (-not $Python) {
    [System.Windows.Forms.MessageBox]::Show(
        "Python was not found. Install Python 3.11+ or run .\run.ps1 from the project folder.",
        "RuTracker Checker",
        [System.Windows.Forms.MessageBoxButtons]::OK,
        [System.Windows.Forms.MessageBoxIcon]::Error
    ) | Out-Null
    exit 1
}

if (-not (Test-Path $DataDir)) {
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}

function Start-BackgroundLoop {
    param([switch]$Replace)

    if (-not (Get-BackgroundEnabled)) {
        return
    }
    if ($Replace) {
        Stop-RootProcessesByPattern @("*background_loop.py*")
    } elseif (Test-ProcessCommandLine "*background_loop.py*") {
        return
    }
    $OutLog = Join-Path $DataDir "background.out.log"
    $ErrLog = Join-Path $DataDir "background.err.log"
    $LoopPath = Join-Path $Root "background_loop.py"
    Start-Process `
        -FilePath $Python `
        -ArgumentList "`"$LoopPath`"" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $OutLog `
        -RedirectStandardError $ErrLog
}

function Open-Ui {
    if (Test-Path $AppExe) {
        Start-Process -FilePath $AppExe -WorkingDirectory $Root
    } else {
        Start-Process $AppUrl
    }
}

function Set-BackgroundEnabled {
    param([bool]$Enabled)
    $Value = if ($Enabled) { "1" } else { "0" }
    Start-Process `
        -FilePath $Python `
        -ArgumentList "-c `"from app import DB; DB.set_setting('background_enabled', '$Value')`"" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden
}

function Get-BackgroundEnabled {
    try {
        $Output = & $Python -c "from app import DB; print('1' if DB.get_setting('background_enabled', '1') == '1' else '0')" 2>$null
        return (($Output | Select-Object -First 1) -eq "1")
    } catch {
        return $false
    }
}

function Invoke-CheckNow {
    $CheckPath = Join-Path $Root "check_once.py"
    Start-Process `
        -FilePath $Python `
        -ArgumentList "`"$CheckPath`"" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden
}

function Stop-AppProcesses {
    $Patterns = @("*background_loop.py*", "*check_once.py*", "*app.py*", "*RutrackerChecker.exe*")
    $Processes = @(Get-CimInstance Win32_Process |
        Where-Object {
            if (-not $_.CommandLine -or $_.ProcessId -eq $PID) {
                return $false
            }
            if ($_.CommandLine -notlike "*$Root*") {
                return $false
            }
            foreach ($Pattern in $Patterns) {
                if ($_.CommandLine -like $Pattern) {
                    return $true
                }
            }
            return $false
        })

    foreach ($Process in $Processes) {
        try {
            Stop-Process -Id $Process.ProcessId -Force
        } catch {
        }
    }
}

function Exit-App {
    try {
        Invoke-RestMethod -Method Post -Uri "$($AppUrl)api/shutdown" -TimeoutSec 2 | Out-Null
        Start-Sleep -Milliseconds 500
    } catch {
    }

    Stop-AppProcesses
    if ($NotifyIcon) {
        $NotifyIcon.Visible = $false
    }
    [System.Windows.Forms.Application]::Exit()
}

function Get-RuntimeStatus {
    if (-not (Test-Path $RuntimeStatusPath)) {
        return $null
    }
    try {
        return Get-Content -Raw -Path $RuntimeStatusPath | ConvertFrom-Json
    } catch {
        return $null
    }
}

function New-AppIcon {
    param([string]$State)

    $Bitmap = New-Object System.Drawing.Bitmap 64, 64
    $Graphics = [System.Drawing.Graphics]::FromImage($Bitmap)
    $Graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $Graphics.Clear([System.Drawing.Color]::Transparent)

    if (Test-Path $BaseIconPath) {
        $BaseImage = [System.Drawing.Image]::FromFile($BaseIconPath)
        $Graphics.DrawImage($BaseImage, 0, 0, 64, 64)
        $BaseImage.Dispose()
    } else {
        $BackBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 23, 32, 51))
        $FilmBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 246, 248, 252))
        $HoleBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 23, 32, 51))
        $Graphics.FillEllipse($BackBrush, 3, 3, 58, 58)
        $Graphics.FillRectangle($FilmBrush, 16, 13, 32, 38)
        foreach ($Y in @(18, 27, 36, 45)) {
            $Graphics.FillRectangle($HoleBrush, 19, $Y, 5, 4)
            $Graphics.FillRectangle($HoleBrush, 40, $Y, 5, 4)
        }
        $BackBrush.Dispose()
        $FilmBrush.Dispose()
        $HoleBrush.Dispose()
    }

    $AccentColor = switch ($State) {
        "running" { [System.Drawing.Color]::FromArgb(255, 34, 197, 94) }
        "paused" { [System.Drawing.Color]::FromArgb(255, 245, 158, 11) }
        "stale" { [System.Drawing.Color]::FromArgb(255, 239, 68, 68) }
        default { [System.Drawing.Color]::FromArgb(255, 102, 112, 133) }
    }
    $AccentBrush = New-Object System.Drawing.SolidBrush $AccentColor
    $BorderBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 255, 255, 255))
    $GlyphBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
    $GlyphPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), 4

    $Graphics.FillEllipse($BorderBrush, 38, 38, 24, 24)
    $Graphics.FillEllipse($AccentBrush, 41, 41, 18, 18)
    if ($State -eq "paused") {
        $Graphics.FillRectangle($GlyphBrush, 46, 46, 3, 9)
        $Graphics.FillRectangle($GlyphBrush, 52, 46, 3, 9)
    } elseif ($State -eq "stale") {
        $Graphics.DrawLine($GlyphPen, 46, 46, 55, 55)
        $Graphics.DrawLine($GlyphPen, 55, 46, 46, 55)
    } else {
        $Graphics.DrawLines($GlyphPen, @(
            [System.Drawing.Point]::new(45, 51),
            [System.Drawing.Point]::new(49, 55),
            [System.Drawing.Point]::new(56, 46)
        ))
    }

    $Handle = $Bitmap.GetHicon()
    $Icon = ([System.Drawing.Icon]::FromHandle($Handle)).Clone()
    [NativeIconMethods]::DestroyIcon($Handle) | Out-Null
    $Graphics.Dispose()
    $AccentBrush.Dispose()
    $BorderBrush.Dispose()
    $GlyphBrush.Dispose()
    $GlyphPen.Dispose()
    $Bitmap.Dispose()
    return $Icon
}

function Get-StateName {
    $Status = Get-RuntimeStatus
    if (-not $Status) {
        return "stale"
    }
    if ($Status.status -eq "paused" -or $Status.status -eq "manual_only") {
        return "paused"
    }
    try {
        $Heartbeat = [datetime]::Parse($Status.last_heartbeat_at).ToUniversalTime()
        if (((Get-Date).ToUniversalTime() - $Heartbeat).TotalSeconds -gt 180) {
            return "stale"
        }
    } catch {
        return "stale"
    }
    return "running"
}

function Format-Relative {
    param($Value)
    if (-not $Value) {
        return "-"
    }
    try {
        $Target = [datetime]::Parse($Value).ToUniversalTime()
    } catch {
        return "-"
    }
    $Seconds = [math]::Round(($Target - (Get-Date).ToUniversalTime()).TotalSeconds)
    $Abs = [math]::Abs($Seconds)
    if ($Abs -lt 45) {
        return "now"
    }
    $Minutes = [math]::Round($Abs / 60)
    $Hours = [math]::Floor($Minutes / 60)
    if ($Hours -gt 0) {
        $Text = "$($Hours)h $($Minutes % 60)m"
    } else {
        $Text = "$($Minutes)m"
    }
    if ($Seconds -ge 0) {
        return "in $Text"
    }
    return "$Text ago"
}

$NotifyIcon = $null
$Menu = $null
$Timer = $null

function Update-Tray {
    if (-not (Get-BackgroundEnabled)) {
        [System.Windows.Forms.Application]::Exit()
        return
    }
    $State = Get-StateName
    if ($State -eq "stale") {
        Start-BackgroundLoop
    }
    $Status = Get-RuntimeStatus
    $Title = switch ($State) {
        "running" { "RuTracker Checker: running" }
        "paused" { "RuTracker Checker: manual only" }
        "stale" { "RuTracker Checker: not detected" }
        default { "RuTracker Checker" }
    }

    if ($Status -and $Status.next_check_at) {
        $StatusItem.Text = "$Title, next check $(Format-Relative $Status.next_check_at)"
    } else {
        $StatusItem.Text = $Title
    }
    $NotifyIcon.Text = $Title.Substring(0, [Math]::Min(63, $Title.Length))
    $OldIcon = $NotifyIcon.Icon
    $NotifyIcon.Icon = New-AppIcon $State
    if ($OldIcon) {
        $OldIcon.Dispose()
    }
    $PauseItem.Visible = $State -ne "paused"
    $ResumeItem.Visible = $State -eq "paused"
}

try {
    if (-not (Get-BackgroundEnabled)) {
        return
    }

    Start-BackgroundLoop -Replace

    $NotifyIcon = New-Object System.Windows.Forms.NotifyIcon
    $NotifyIcon.Text = "RuTracker Checker"
    $NotifyIcon.Visible = $true
    $NotifyIcon.Icon = New-AppIcon "stale"

    $Menu = New-Object System.Windows.Forms.ContextMenuStrip
    $StatusItem = $Menu.Items.Add("Starting background checker...")
    $StatusItem.Enabled = $false
    $Menu.Items.Add("-") | Out-Null
    $OpenItem = $Menu.Items.Add("Open UI")
    $CheckItem = $Menu.Items.Add("Check now")
    $PauseItem = $Menu.Items.Add("Pause background checks")
    $ResumeItem = $Menu.Items.Add("Resume background checks")
    $RefreshItem = $Menu.Items.Add("Refresh status")
    $Menu.Items.Add("-") | Out-Null
    $ExitItem = $Menu.Items.Add("Exit (stops background checks!)")
    $NotifyIcon.ContextMenuStrip = $Menu

    $OpenItem.Add_Click({ Open-Ui })
    $NotifyIcon.Add_DoubleClick({ Open-Ui })
    $CheckItem.Add_Click({ Invoke-CheckNow })
    $PauseItem.Add_Click({ Set-BackgroundEnabled $false; [System.Windows.Forms.Application]::Exit() })
    $ResumeItem.Add_Click({ Set-BackgroundEnabled $true; Start-BackgroundLoop -Replace })
    $RefreshItem.Add_Click({ Update-Tray })
    $ExitItem.Add_Click({ Exit-App })

    $Timer = New-Object System.Windows.Forms.Timer
    $Timer.Interval = 15000
    $Timer.Add_Tick({ Update-Tray })
    $Timer.Start()
    Update-Tray

    [System.Windows.Forms.Application]::Run()
} finally {
    if ($Timer) {
        $Timer.Stop()
        $Timer.Dispose()
    }
    if ($NotifyIcon) {
        $NotifyIcon.Visible = $false
        if ($NotifyIcon.Icon) {
            $NotifyIcon.Icon.Dispose()
        }
        $NotifyIcon.Dispose()
    }
    if ($Menu) {
        $Menu.Dispose()
    }
    if ($TrayMutex) {
        $TrayMutex.ReleaseMutex()
        $TrayMutex.Dispose()
    }
}
