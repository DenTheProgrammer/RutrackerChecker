function Get-AppUrl {
    param([Parameter(Mandatory = $true)][string]$Root)

    $port = 19876
    $portFile = Join-Path $Root 'data\server-port.txt'
    try {
        $value = [System.IO.File]::ReadAllText($portFile).Trim()
        $selectedPort = 0
        if ([int]::TryParse($value, [ref]$selectedPort) -and $selectedPort -ge 1024 -and $selectedPort -le 65535) {
            $port = $selectedPort
        }
    } catch {
    }
    return "http://127.0.0.1:$port/"
}
