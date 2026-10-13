$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$repository = "therealsaitama/stereo-sabha"
$description = "Two AI voices, one in each ear. Jump into a live Hindi and English conversation with your microphone."

if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw "Install GitHub CLI, then run this script again." }
& gh auth status
if ($LASTEXITCODE -ne 0) { throw "Run: gh auth login --hostname github.com --web. Sign in as therealsaitama." }
$account = (& gh api user --jq .login | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $account -ine "therealsaitama") { throw "The active GitHub account must be therealsaitama. Current account: $account" }

$changes = (& git status --porcelain | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect the local Git repository." }
if ($changes) { throw "There are uncommitted changes. Review and commit them before publishing." }
$remoteNames = @(& git remote)
$origin = ""
if ($remoteNames -contains "origin") { $origin = (& git remote get-url origin | Out-String).Trim() }
if ($origin) {
    if ($origin -notmatch "^https://github\.com/therealsaitama/stereo-sabha(?:\.git)?$") {
        throw "Existing origin points elsewhere: $origin"
    }
    & gh auth setup-git
    if ($LASTEXITCODE -ne 0) { throw "Could not configure GitHub authentication." }
    & git push -u origin main
    if ($LASTEXITCODE -ne 0) { throw "Push failed. No force push was attempted." }
} else {
    & gh repo create $repository --public --description $description --source . --remote origin --push
    if ($LASTEXITCODE -ne 0) {
        throw "Repository creation or push failed. If origin was created, rerun this script after resolving the error."
    }
}
& gh repo edit $repository --add-topic voice-ai --add-topic sarvam --add-topic websockets --add-topic stereo-audio --add-topic hindi --add-topic python
if ($LASTEXITCODE -ne 0) { Write-Warning "Code was pushed, but repository topics could not be updated." }
Write-Host "Published: https://github.com/$repository" -ForegroundColor Green
