param(
    [switch]$Test
)

$ErrorActionPreference = "Stop"
$BundledPython = "C:\Users\den4i\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = $null

try {
    $Python = (Get-Command python -ErrorAction Stop).Source
} catch {
    if (Test-Path $BundledPython) {
        $Python = $BundledPython
    }
}

if (-not $Python) {
    Write-Host "Python was not found in PATH."
    Write-Host "Install Python 3.11+ or run with the bundled Codex Python path if available:"
    Write-Host $BundledPython
    exit 1
}

if ($Test) {
    & $Python -m unittest discover -s tests
} else {
    & $Python app.py
}
