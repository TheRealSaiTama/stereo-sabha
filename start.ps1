$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) { throw "Run .\setup.ps1 first." }
Write-Host "Cloud voice mode. No Ollama, Piper, Whisper, or GPU needed." -ForegroundColor Green
Write-Host "Use only remaining free Sarvam credits. No paid top-ups."
Write-Host "Room URL after startup: http://127.0.0.1:8765"
& $venvPython server.py
if ($LASTEXITCODE -ne 0) { throw "Room server failed. See the error above." }
