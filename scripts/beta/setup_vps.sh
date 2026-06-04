#!/usr/bin/env bash
# Phase 10.Beta — first-time Droplet bootstrap (Ubuntu 24.04 on DigitalOcean).
# Prerequisite: DO Cloud Firewall allows SSH (22) from your IP only — see docs/CLOUD_BETA.md.
# Usage: scp to Droplet, then: bash scripts/beta/setup_vps.sh
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/thericktenorio/PDK-DataManagementSystem.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/pdk/pdk_crm_postgresql}"

echo "==> apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt update
apt install -y git ca-certificates curl ufw postgresql-client gzip

echo "==> AWS CLI (optional — for B2 backups later; not in Ubuntu 24.04 apt)"
if ! command -v aws >/dev/null 2>&1; then
  apt install -y python3-pip >/dev/null 2>&1 || true
  pip3 install --break-system-packages awscli 2>/dev/null \
    || echo "Skip aws CLI for now; install before enabling backup_beta.sh (pip3 install awscli)"
fi

echo "==> Docker Engine + Compose v2"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
docker compose version

echo "==> UFW: SSH only (adjust if your IP changes)"
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

echo "==> Clone application"
mkdir -p "$(dirname "$INSTALL_DIR")"
if [ ! -d "$INSTALL_DIR/.git" ]; then
  git clone "$REPO_URL" "$INSTALL_DIR"
else
  echo "Repo already exists at $INSTALL_DIR — git pull skipped (run manually)"
fi

echo "==> Next steps (manual):"
echo "  1. cp $INSTALL_DIR/pdk_crm/.env.beta.example $INSTALL_DIR/pdk_crm/.env.docker"
echo "  2. Edit .env.docker — SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS=crm.godelta.us"
echo "  3. cd $INSTALL_DIR && docker compose -f compose.yaml -f compose.beta.yaml up --build -d"
echo "  4. bash scripts/beta/install_cloudflared.sh"
echo "  5. Configure Cloudflare Access on crm.godelta.us"
echo "  6. bash scripts/beta/backup_beta.sh  (after B2 bucket + ~/.aws/credentials)"
