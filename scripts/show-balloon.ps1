param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $true)]
    [string]$Message
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $Root "RutrackerChecker.exe"
$UiUrl = "http://127.0.0.1:9876/"
$script:OpenedUi = $false

function Open-CheckerUi {
    if ($script:OpenedUi) {
        return
    }
    $script:OpenedUi = $true

    if (Test-Path $Launcher) {
        Start-Process -FilePath $Launcher -WorkingDirectory $Root
        return
    }

    Start-Process $UiUrl
}

$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$notify.BalloonTipTitle = $Title
$notify.BalloonTipText = $Message
$notify.Visible = $true
$notify.add_BalloonTipClicked({ Open-CheckerUi })
$notify.add_Click({ Open-CheckerUi })
$notify.ShowBalloonTip(10000)

Start-Sleep -Seconds 11
$notify.Dispose()
