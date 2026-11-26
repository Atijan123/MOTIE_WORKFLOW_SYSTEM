# Install the GitHub Actions self-hosted runner on this Windows PC, as a
# service (step 12i). Run ONCE, in PowerShell opened "as administrator":
#
#     powershell -ExecutionPolicy Bypass -File scripts\runner\install-runner.ps1
#
# It asks for your Windows password (to run the service as you: only your
# account can reach Docker Desktop). The password goes to Windows' service
# manager and nowhere else. See docs/SELF-HOSTED-RUNNER.md.
$ErrorActionPreference = "Stop"
$Repo = "Atijan123/MOTIE_WORKFLOW_SYSTEM"
$Dir = "C:\actions-runner"
$GitBin = "C:\Program Files\Git\bin"

function Fail($message) { Write-Host "Stopped: $message" -ForegroundColor Red; exit 1 }

# 1. Check what it needs.
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) { Fail "open PowerShell with 'Run as administrator' and run this again." }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { Fail "the GitHub CLI (gh) isn't installed." }
gh auth status *> $null; if ($LASTEXITCODE -ne 0) { Fail "gh isn't signed in: run 'gh auth login' first." }
docker info *> $null; if ($LASTEXITCODE -ne 0) { Fail "Docker Desktop isn't running. Start it, then run this again." }
if (-not (Test-Path "$GitBin\bash.exe")) { Fail "Git Bash isn't at $GitBin (install Git for Windows)." }
if (Test-Path "$Dir\.runner") { Fail "a runner is already set up in $Dir. Remove it first (scripts\runner\remove-runner.ps1)." }

# 2. Download the latest runner and check it against GitHub's published checksum.
$release = gh api repos/actions/runner/releases/latest | ConvertFrom-Json
$version = $release.tag_name.TrimStart("v")
$asset = $release.assets | Where-Object { $_.name -eq "actions-runner-win-x64-$version.zip" }
if (-not $asset) { Fail "couldn't find the Windows runner in release $version." }
if ($release.body -notmatch "<!-- BEGIN SHA win-x64 -->([0-9a-f]{64})<!-- END SHA win-x64 -->") { Fail "couldn't read the release's checksum." }
$expected = $Matches[1]
New-Item -ItemType Directory -Force $Dir | Out-Null
$zip = Join-Path $Dir $asset.name
Write-Host "Downloading runner $version ..."
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zip -UseBasicParsing
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
if ($actual -ne $expected) { Remove-Item $zip; Fail "the download's checksum doesn't match GitHub's ($actual). Nothing installed." }
Expand-Archive -Path $zip -DestinationPath $Dir -Force
Remove-Item $zip

# 3. Jobs use Git Bash, not WSL's bash (which can't reach Docker Desktop):
#    the runner gives jobs the PATH in its .path file.
Set-Content -Path "$Dir\.path" -Value "$GitBin;$env:PATH" -Encoding ASCII

# 4. Register with the repository (a one-hour token, through your gh login)
#    and install the service, running as you.
$token = gh api -X POST "repos/$Repo/actions/runners/registration-token" --jq .token
$account = "$env:USERDOMAIN\$env:USERNAME"
$credential = Get-Credential -UserName $account -Message "Your Windows password, to run the runner service as you (for Docker Desktop)"
$password = $credential.GetNetworkCredential().Password
Push-Location $Dir
try {
    & .\config.cmd --unattended --url "https://github.com/$Repo" --token $token `
        --name "$env:COMPUTERNAME-motie" --labels "motie" --work "_work" --replace `
        --runasservice --windowslogonaccount $account --windowslogonpassword $password
    if ($LASTEXITCODE -ne 0) { Fail "config.cmd failed (see above)." }
} finally {
    $password = $null
    Pop-Location
}

Get-Service "actions.runner.*" | Format-Table Name, Status, StartType
Write-Host "Done. Check it on GitHub: https://github.com/$Repo/settings/actions/runners" -ForegroundColor Green
