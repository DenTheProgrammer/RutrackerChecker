$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$DataDir = Join-Path $Root "data"
$RuntimeStatusPath = Join-Path $DataDir "runtime_status.json"
$AppExe = Join-Path $Root "RutrackerChecker.exe"
$AppUrl = "http://127.0.0.1:9876/"
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = $null

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
    return @(Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -like $Pattern -and
            $_.CommandLine -like "*$Root*"
        }).Count -gt 0
}

if (Test-ProcessCommandLine "*start-tray.ps1*") {
    exit 0
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
    if (Test-ProcessCommandLine "*background_loop.py*") {
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

function Invoke-CheckNow {
    $CheckPath = Join-Path $Root "check_once.py"
    Start-Process `
        -FilePath $Python `
        -ArgumentList "`"$CheckPath`"" `
        -WorkingDirectory $Root `
        -WindowStyle Hidden
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

    $BackBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 23, 32, 51))
    $FilmBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 246, 248, 252))
    $HoleBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255, 23, 32, 51))
    $AccentColor = switch ($State) {
        "running" { [System.Drawing.Color]::FromArgb(255, 15, 107, 88) }
        "paused" { [System.Drawing.Color]::FromArgb(255, 194, 65, 12) }
        "stale" { [System.Drawing.Color]::FromArgb(255, 180, 35, 24) }
        default { [System.Drawing.Color]::FromArgb(255, 102, 112, 133) }
    }
    $AccentBrush = New-Object System.Drawing.SolidBrush $AccentColor
    $AccentPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), 5

    $Graphics.FillEllipse($BackBrush, 3, 3, 58, 58)
    $Graphics.FillRectangle($FilmBrush, 16, 13, 32, 38)
    foreach ($Y in @(18, 27, 36, 45)) {
        $Graphics.FillRectangle($HoleBrush, 19, $Y, 5, 4)
        $Graphics.FillRectangle($HoleBrush, 40, $Y, 5, 4)
    }
    $Graphics.FillEllipse($AccentBrush, 31, 31, 25, 25)
    if ($State -eq "paused") {
        $PauseBrush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
        $Graphics.FillRectangle($PauseBrush, 39, 38, 4, 12)
        $Graphics.FillRectangle($PauseBrush, 47, 38, 4, 12)
        $PauseBrush.Dispose()
    } elseif ($State -eq "stale") {
        $CrossPen = New-Object System.Drawing.Pen ([System.Drawing.Color]::White), 5
        $Graphics.DrawLine($CrossPen, 39, 39, 51, 51)
        $Graphics.DrawLine($CrossPen, 51, 39, 39, 51)
        $CrossPen.Dispose()
    } else {
        $Graphics.DrawLines($AccentPen, @(
            [System.Drawing.Point]::new(38, 44),
            [System.Drawing.Point]::new(44, 50),
            [System.Drawing.Point]::new(53, 38)
        ))
    }

    $Icon = [System.Drawing.Icon]::FromHandle($Bitmap.GetHicon())
    $Graphics.Dispose()
    $BackBrush.Dispose()
    $FilmBrush.Dispose()
    $HoleBrush.Dispose()
    $AccentBrush.Dispose()
    $AccentPen.Dispose()
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

Start-BackgroundLoop

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
$ExitItem = $Menu.Items.Add("Exit tray icon")
$NotifyIcon.ContextMenuStrip = $Menu

$OpenItem.Add_Click({ Open-Ui })
$NotifyIcon.Add_DoubleClick({ Open-Ui })
$CheckItem.Add_Click({ Invoke-CheckNow })
$PauseItem.Add_Click({ Set-BackgroundEnabled $false })
$ResumeItem.Add_Click({ Set-BackgroundEnabled $true; Start-BackgroundLoop })
$RefreshItem.Add_Click({ Update-Tray })
$ExitItem.Add_Click({
    $NotifyIcon.Visible = $false
    [System.Windows.Forms.Application]::Exit()
})

function Update-Tray {
    $State = Get-StateName
    if ($State -eq "stale") {
        Start-BackgroundLoop
    }
    $Status = Get-RuntimeStatus
    $Title = switch ($State) {
        "running" { "RuTracker Checker - running" }
        "paused" { "RuTracker Checker - manual only" }
        "stale" { "RuTracker Checker - not detected" }
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

$Timer = New-Object System.Windows.Forms.Timer
$Timer.Interval = 15000
$Timer.Add_Tick({ Update-Tray })
$Timer.Start()
Update-Tray

[System.Windows.Forms.Application]::Run()
