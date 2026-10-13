$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required." }
}
& $venvPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Run from a terminal with internet access." }
Write-Host "Cloud mode ready. No local models downloaded." -ForegroundColor Green
Write-Host "Run .\start.ps1. It loads your local .env or asks for missing configuration."
