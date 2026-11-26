# CI on your own PC: a GitHub self-hosted runner

The CI workflow (.github/workflows/ci.yml) can run on GitHub's machines or on
a **self-hosted runner**: a small program from GitHub that runs on your Windows
PC, waits for jobs from this repository, and runs them with your Docker
Desktop. It costs no GitHub minutes.

Commands marked **▶ You run** are for you to type. Everything else is
explanation.

---

## How it's kept safe

- **Pushes only.** The workflow has no `pull_request` trigger, every job checks
  it is this repository (`if: github.repository == ...`), and the repository is
  **private**. A pull request from someone else's fork would run *their* code on
  your PC, which is why GitHub warns never to use a self-hosted runner on a
  public repository.
- **Apart from your dev stack.** CI runs as Compose project `motie-ci` with
  docker-compose.ci.yml on top: its own database and volumes, no ports on your
  PC, its own image names (`motie-ci/...`). A CI run can't reset your dev
  database, and it doesn't clash with a dev stack that's running.
- **Cleans up after every job** (scripts/ci-cleanup.sh): removes the `motie-ci`
  containers and volumes, dangling images, Docker build cache older than 7
  days, and Playwright's local results. Failed runs' reports are uploaded to
  GitHub first, and kept there 7 days.
- **Runs as you.** The service runs under your Windows account, because Docker
  Desktop only answers its own user (and the `docker-users` group). Anything a
  job does, it does as you: that's why only your own pushes may run.

## Before you start

1. **Free disk space.** 10 GB or more free on C: is comfortable. CI keeps its
   images between runs (that's what makes the second run fast): about 3 GB.
2. **Give Docker more memory.** Two web apps, the API, Postgres and a browser
   need about 4–6 GB. With Docker Desktop's WSL 2 engine the limit is set in
   `C:\Users\<you>\.wslconfig`:

   **▶ You run** (PowerShell), then restart Docker Desktop:
   ```powershell
   notepad $env:USERPROFILE\.wslconfig
   ```
   and put in it:
   ```ini
   [wsl2]
   memory=6GB
   ```
3. **Docker Desktop starts when you sign in**: Docker Desktop → Settings →
   General → "Start Docker Desktop when you sign in to your computer". The
   runner service starts with Windows, but Docker Desktop only runs while you
   are signed in. Locking the screen (Windows key + L) is fine; signing out
   stops CI.
4. Installed already: Git for Windows (Git Bash), the GitHub CLI (`gh`, signed
   in), Docker Desktop.

## 1. Install, register and run as a service

**▶ You run**, in PowerShell opened with **Run as administrator**, in the
project folder:
```powershell
cd C:\Users\LENOVE\MOTIE_WORKFLOW_SYSTEM
powershell -ExecutionPolicy Bypass -File scripts\runner\install-runner.ps1
```

What scripts/runner/install-runner.ps1 does, in order:
1. checks you're an administrator, `gh` is signed in, Docker is running and Git Bash is installed;
2. downloads the latest runner from github.com/actions/runner into `C:\actions-runner`, and **checks its SHA-256 checksum** against the one GitHub publishes with the release (it stops if they differ);
3. writes `C:\actions-runner\.path`, so jobs find Git Bash's `bash` before WSL's (which can't reach Docker Desktop);
4. gets a one-hour registration token through your `gh` login and registers the runner as `<COMPUTERNAME>-motie`, with the label `motie`;
5. asks for **your Windows password** (a Windows dialog) and installs the Windows service `actions.runner.Atijan123-MOTIE_WORKFLOW_SYSTEM.<name>`, running as you, starting automatically.

Then tell me it's done. I'll switch CI to it by deleting the repository
variable `CI_RUNS_ON`, which currently sends CI to GitHub's machines, and make
the repository private again:
```bash
gh variable delete CI_RUNS_ON --repo Atijan123/MOTIE_WORKFLOW_SYSTEM
gh repo edit Atijan123/MOTIE_WORKFLOW_SYSTEM --visibility private --accept-visibility-change-consequences
```

## 2. Check its status

**▶ You run** (any PowerShell):
```powershell
Get-Service actions.runner.*
```
`Running` is good. On GitHub: the repository → Settings → Actions → Runners
shows it as **Idle** (waiting) or **Active** (running a job).

The runner's own logs: `C:\actions-runner\_diag\` (newest `Runner_*.log`;
each job has a `Worker_*.log`).

Watch a run from the terminal:
```bash
gh run list --limit 5
gh run watch
```

## 3. Stop, start, restart

**▶ You run** (PowerShell as administrator):
```powershell
Stop-Service actions.runner.*
Start-Service actions.runner.*
Restart-Service actions.runner.*
```
While it's stopped, pushes wait in the queue (up to 24 hours) and run when it's back.

## 4. Update

The runner **updates itself**: when GitHub releases a new version, it
downloads it between jobs and restarts. Nothing to do. If it has been off for
weeks and GitHub refuses it as too old, remove it (section 5) and install it
again (section 1).

## 5. Remove

**▶ You run** (PowerShell as administrator, in the project folder):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\runner\remove-runner.ps1
Remove-Item -Recurse -Force C:\actions-runner
```
It unregisters the runner from GitHub and removes the service. Then send CI
back to GitHub's machines, or nothing will run it:
```bash
gh variable set CI_RUNS_ON --body ubuntu-24.04 --repo Atijan123/MOTIE_WORKFLOW_SYSTEM
```
(A private repository on GitHub's machines uses your free minutes: 2,000 a month.)

## When something goes wrong

| What you see | Why, and what to do |
| --- | --- |
| A run stays "Queued" | The runner is offline: `Get-Service actions.runner.*`. Is Docker Desktop running, and are you signed in? |
| `error during connect ... dockerDesktopLinuxEngine` | Docker Desktop isn't running (or you signed out). Start it; re-run the job from the run's page ("Re-run failed jobs"). |
| `no space left on device` or `read-only file system` | C: is full. Free space; then Docker Desktop → Troubleshoot → Restart. `docker system df` shows what Docker holds. |
| `ENOMEM` in the web app's log | Docker needs more memory: `.wslconfig` (above). |
| `bash: ... WSL` errors | Jobs found WSL's bash: check `C:\actions-runner\.path` starts with `C:\Program Files\Git\bin`, then `Restart-Service actions.runner.*`. |

Your dev stack is unaffected by all of this: it is a different Compose project
(`motie_workflow_system`).
