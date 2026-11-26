#!/usr/bin/env bash
# Make an offline update for the office server (step 13f), on any PC with
# internet, Git and Docker, when the server itself can't reach the internet:
#
#   bash scripts/office-bundle.sh v1.4.0 /media/usb
#
# writes /media/usb/motie-update-v1.4.0/ with:
#   code.bundle   the code (a git bundle: the commit and the tags)
#   COMMIT        the commit it is
#   VERSION       its version name
#   images/*.tar  every image the office stack runs, built for that version
#   SHA256SUMS    to check nothing was damaged on the way
# Then, on the server:  sudo bash scripts/office-update.sh --from /media/usb/motie-update-v1.4.0
set -euo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "$0")/.."

ref="${1:?Usage: scripts/office-bundle.sh <tag or commit> <folder on the USB stick>}"
target="${2:?Usage: scripts/office-bundle.sh <tag or commit> <folder on the USB stick>}"
commit="$(git rev-parse "$ref^{commit}")"
version="$(git describe --tags --always "$commit")"
out="$target/motie-update-$version"
[ -e "$out" ] && { echo "$out already exists." >&2; exit 1; }
mkdir -p "$out/images"

echo "==> The code: $version ($commit)"
git bundle create "$out/code.bundle" "$commit" --tags
echo "$commit" > "$out/COMMIT"
echo "$version" > "$out/VERSION"

echo "==> Building the images for $version"
work="$(mktemp -d)"
git worktree add --detach "$work/src" "$commit" >/dev/null
trap 'git worktree remove --force "$work/src" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
# Building needs no real settings, but the compose file insists on them.
cat > "$work/build.env" <<'EOF'
OFFICE_HOSTNAME=build.invalid
OFFICE_BIND_IP=127.0.0.1
OFFICE_NETWORK=127.0.0.0/8
POSTGRES_DB=x
APP_DB_PASSWORD=x
MIGRATION_DB_PASSWORD=x
JWT_SECRET=x
MFA_SECRET_KEY=x
STAFF_PORTAL_KEY=x
BACKUP_PATH=/tmp
EOF
(cd "$work/src" && MOTIE_VERSION="$version" docker compose -f docker-compose.office.yml --env-file "$work/build.env" --profile tools build)

echo "==> Saving the images"
for image in "motie/office-backend:$version" "motie/office-staff:$version" "motie/office-backup:$version" \
             pgvector/pgvector:pg16 caddy:2.8.4; do
    docker pull --quiet "$image" >/dev/null 2>&1 || true  # the two outside images
    docker save --output "$out/images/$(echo "$image" | tr '/:' '__').tar" "$image"
done

(cd "$out" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "Done: $out ($(du -sh "$out" | cut -f1)). On the server:"
echo "  (cd $out && sha256sum --check SHA256SUMS)"
echo "  sudo bash scripts/office-update.sh --from $out"
