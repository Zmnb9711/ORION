$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Here '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $Python)) {
    $RepositoryPython = Join-Path $Here '..\..\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $RepositoryPython) {
        & $RepositoryPython -m venv (Join-Path $Here '.venv')
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -m venv (Join-Path $Here '.venv')
    } else {
        python -m venv (Join-Path $Here '.venv')
    }
}

& $Python -m pip install -r (Join-Path $Here 'requirements.txt')
Push-Location $Here
try {
    & $Python -m PyInstaller --noconfirm --clean `
        --distpath $Here `
        --workpath (Join-Path $Here 'build') `
        (Join-Path $Here 'YandexRealtimeTester.spec')
} finally {
    Pop-Location
}

$Output = Join-Path $Here 'YandexRealtimeTester'
New-Item -ItemType Directory -Force -Path (Join-Path $Output 'logs') | Out-Null
$Exe = Join-Path $Output 'YandexRealtimeTester.exe'
& $Exe --srs-offline-smoke-test
if ($LASTEXITCODE -ne 0) {
    throw "Frozen SRS codec/resampler smoke failed with exit code $LASTEXITCODE"
}
& $Exe --gui-smoke-test
if ($LASTEXITCODE -ne 0) {
    throw "Frozen hidden Tk Direct/SRS mode smoke failed with exit code $LASTEXITCODE"
}
Write-Host "Built and smoke-tested: $Exe"
