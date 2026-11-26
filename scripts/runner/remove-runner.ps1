# Remove the self-hosted runner from this PC and from GitHub (step 12i).
# In PowerShell opened "as administrator":
#
#     powershell -ExecutionPolicy Bypass -File scripts\runner\remove-runner.ps1
$ErrorActionPreference = "Stop"
$Repo = "Atijan123/MOTIE_WORKFLOW_SYSTEM"
$Dir = "C:\actions-runner"
if (-not (Test-Path "$Dir\config.cmd")) { Write-Host "No runner in $Dir."; exit 0 }
$token = gh api -X POST "repos/$Repo/actions/runners/remove-token" --jq .token
Push-Location $Dir
try { & .\config.cmd remove --token $token } finally { Pop-Location }
Write-Host "Removed. You can delete $Dir now. To run CI on GitHub's machines instead:"
Write-Host "  gh variable set CI_RUNS_ON --body ubuntu-24.04 --repo $Repo"
