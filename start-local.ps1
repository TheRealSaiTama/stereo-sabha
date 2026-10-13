$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$modelPath = Join-Path $PSScriptRoot "models\Qwen3-0.6B-Q4_0.gguf"
$llamaRoot = Join-Path $PSScriptRoot "runtime\llama"
if (-not (Test-Path -LiteralPath $venvPython) -or -not (Test-Path -LiteralPath $modelPath)) {
    throw "Run .\setup-local.ps1 first."
}
$llamaBinary = Get-ChildItem -LiteralPath $llamaRoot -Filter "llama-server.exe" -Recurse | Select-Object -First 1
if (-not $llamaBinary) { throw "Local inference runtime is missing. Run .\setup-local.ps1 again." }
foreach ($port in @(8081, 8765)) {
    $probe = New-Object System.Net.Sockets.TcpClient
    try {
        $probe.Connect("127.0.0.1", $port)
        throw "Port $port is already in use. Stop the existing process before launching."
    } catch [System.Net.Sockets.SocketException] {
    } finally {
        $probe.Dispose()
    }
}
$env:HF_HUB_OFFLINE = "1"
$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:OMP_NUM_THREADS = "2"
$quotedModel = '"' + $modelPath + '"'
$llamaArguments = @("-m", $quotedModel, "--host", "127.0.0.1", "--port", "8081", "-c", "4096", "-t", "4", "-np", "1", "-ngl", "0", "--jinja")
$llamaProcess = Start-Process -FilePath $llamaBinary.FullName -ArgumentList $llamaArguments -WorkingDirectory $llamaBinary.DirectoryName -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $PSScriptRoot "runtime\llama.stdout.log") -RedirectStandardError (Join-Path $PSScriptRoot "runtime\llama.stderr.log")
try {
    Write-Host "Loading the local model..." -ForegroundColor Green
    $ready = $false
    for ($attempt = 0; $attempt -lt 90; $attempt++) {
        if ($llamaProcess.HasExited) { throw "Local model exited. Check runtime\llama.stderr.log." }
        try {
            $health = Invoke-RestMethod -Uri "http://127.0.0.1:8081/health" -TimeoutSec 2
            if ($health.status -eq "ok") { $ready = $true; break }
        } catch {
        }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "Model startup timed out. Check runtime\llama.stderr.log." }
    Write-Host "Room URL: http://127.0.0.1:8765" -ForegroundColor Green
    Write-Host "Open it once the server says it is running. Ctrl+C stops both services."
    & $venvPython server.py --local
    if ($LASTEXITCODE -ne 0) { throw "Room server failed. See the error above." }
} finally {
    if (-not $llamaProcess.HasExited) { Stop-Process -Id $llamaProcess.Id }
}
