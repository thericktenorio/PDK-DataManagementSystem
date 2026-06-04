#!/usr/bin/env bash
# Pull latest + rebuild beta stack on VPS.
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/pdk/pdk_crm_postgresql}"
cd "$INSTALL_DIR"

if [ ! -f pdk_crm/.env.docker ]; then
  echo "Missing pdk_crm/.env.docker — copy from pdk_crm/.env.beta.example and fill secrets."
  exit 1
fi

# Compose substitutes ${DB_NAME} etc. from project-root .env only (not crm_web env_file).
ln -sf pdk_crm/.env.docker .env

git pull --ff-only
docker compose -f compose.yaml -f compose.beta.yaml up --build -d

echo "Waiting for CRM health..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
    echo "CRM healthy."
    break
  fi
  sleep 5
done

docker compose exec -T crm_web python manage.py check_mvp_ready || true
docker compose exec -T pdf_web python manage.py migrate --noinput

echo "Smoke: curl http://127.0.0.1:8000/health/"
curl -sf http://127.0.0.1:8000/health/ && echo ""
