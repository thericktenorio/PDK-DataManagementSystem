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

# Pass commit SHA as BUILD_VERSION so Docker invalidates COPY layers after git pull.
export GIT_SHA="$(git rev-parse HEAD)"
echo "Deploying GIT_SHA=${GIT_SHA}"

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

echo "Smoke: parser disposition route..."
# Use Django URL resolution — HTTP POST with a random UUID hits the view and, with
# DJANGO_DEBUG=1, returns the same debug 404 page as an unregistered route.
docker compose exec -T pdf_web python manage.py shell -c "
from django.urls import resolve

match = resolve('/api/jobs/00000000-0000-0000-0000-000000000001/disposition/')
if match.url_name != 'job_disposition':
    raise SystemExit(f'unexpected view: {match.url_name!r}')
print('disposition route OK')
"
