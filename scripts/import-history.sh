#!/usr/bin/env bash
# Import the register of historical facility letters (step 11).
#
#     bash scripts/import-history.sh /path/to/ETLS_Facility_Letters_2025-2026.xlsx
#
# The register holds real importer data, so it stays where it is: its folder
# is mounted read-only at /data in a one-off tools container, and nothing is
# copied into the repository. Re-running replaces the previous import, in one
# transaction; a register with any problem changes nothing and lists them.
#
# It writes to whatever database .env points at. Run it on the dev database
# first and look at the Statistics page before running it anywhere else.
set -euo pipefail

# Git Bash on Windows would rewrite "/data/..." into a Windows path. Switch that off.
export MSYS_NO_PATHCONV=1

if [ $# -ne 1 ]; then
    echo "Usage: bash scripts/import-history.sh /path/to/register.xlsx" >&2
    exit 1
fi
# From PowerShell, "bash" can be WSL's, which may not reach Docker Desktop or C:/ paths.
if ! docker info >/dev/null 2>&1; then
    echo "Nothing was imported. This shell can't reach Docker. Is Docker Desktop running? From PowerShell, use Git Bash:" >&2
    echo '  & "C:\Program Files\Git\bin\bash.exe" scripts/import-history.sh "<path to the register>"' >&2
    exit 1
fi
if [ ! -f "$1" ]; then
    echo "Nothing was imported. This shell can't find the file: $1" >&2
    exit 1
fi
# An absolute folder for Docker: "C:/Users/..." in Git Bash (pwd -W), "/home/..." elsewhere.
folder="$(cd "$(dirname "$1")" && { pwd -W 2>/dev/null || pwd; })"
file="$(basename "$1")"

cd "$(dirname "$0")/.."
docker compose run --rm -v "${folder}:/data:ro" tools \
    python -m app.modules.etls.import_history "/data/${file}"
