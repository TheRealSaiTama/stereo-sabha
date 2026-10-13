$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required. Virtual environment creation failed." }
}
& $venvPython -m pip install -r requirements-local.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check internet access and Python wheel support." }
& $venvPython setup_models.py
if ($LASTEXITCODE -ne 0) { throw "Model setup failed. Run setup.ps1 again to retry." }
Write-Host ""
Write-Host "Setup complete. Run: .\start-local.ps1" -ForegroundColor Green
