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
    exit 1
}

$Existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -like "*background_loop.py*" -and
        $_.CommandLine -like "*$Root*"
    }

if ($Existing) {
    exit 0
}

Set-Location $Root
& $Python (Join-Path $Root "background_loop.py")
