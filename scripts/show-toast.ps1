param(
    [Parameter(Mandatory = $true)]
    [string]$Title,

    [Parameter(Mandatory = $true)]
    [string]$Message
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $Root "RutrackerChecker.exe"
$BalloonScript = Join-Path $PSScriptRoot "show-balloon.ps1"
$ProtocolName = "rutrackerchecker"
$ProtocolUri = "${ProtocolName}://open"
$AppId = "RuTrackerChecker.Local"
$FallbackAppId = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
$UiUrl = "http://127.0.0.1:9876/"

function Escape-Xml {
    param([string]$Value)
    return [System.Security.SecurityElement]::Escape($Value)
}

function Register-CheckerProtocol {
    $protocolKey = "Registry::HKEY_CURRENT_USER\Software\Classes\$ProtocolName"
    $commandKey = Join-Path $protocolKey "shell\open\command"

    New-Item -Path $commandKey -Force | Out-Null
    Set-Item -Path $protocolKey -Value "URL:RuTracker Checker"
    New-ItemProperty -Path $protocolKey -Name "URL Protocol" -Value "" -PropertyType String -Force | Out-Null

    if (Test-Path $Launcher) {
        $command = '"' + $Launcher + '"'
    } else {
        $encoded = [Convert]::ToBase64String(
            [Text.Encoding]::Unicode.GetBytes("Start-Process '$UiUrl'")
        )
        $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encoded"
    }

    Set-Item -Path $commandKey -Value $command
}

function Show-ModernToast {
    Register-CheckerProtocol

    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

    $safeTitle = Escape-Xml $Title
    $safeMessage = Escape-Xml $Message
    $safeLaunch = Escape-Xml $ProtocolUri

    $toastXml = @"
<toast activationType="protocol" launch="$safeLaunch">
  <visual>
    <binding template="ToastGeneric">
      <text>$safeTitle</text>
      <text>$safeMessage</text>
    </binding>
  </visual>
  <actions>
    <action content="Open" activationType="protocol" arguments="$safeLaunch" />
  </actions>
</toast>
"@

    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml($toastXml)
    $toast = [Windows.UI.Notifications.ToastNotification]::new($xml)

    $lastError = $null
    foreach ($notifierAppId in @($AppId, $FallbackAppId)) {
        try {
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($notifierAppId).Show($toast)
            return
        } catch {
            $lastError = $_
        }
    }

    throw $lastError
}

try {
    Show-ModernToast
} catch {
    if (Test-Path $BalloonScript) {
        & $BalloonScript -Title $Title -Message $Message
    }
}
