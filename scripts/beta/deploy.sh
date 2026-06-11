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
if ! docker compose exec -T pdf_web grep -q 'disposition/' /app/pdf_manager/apps/ui/urls_api.py; then
  echo "ERROR: pdf_web image missing disposition route in urls_api.py." >&2
  exit 1
fi

docker compose exec -T crm_web python - <<'PY'
import json
import urllib.error
import urllib.request
import uuid

url = f"http://pdfmgr:8000/api/jobs/{uuid.uuid4()}/disposition/"
req = urllib.request.Request(
    url,
    data=json.dumps({"status": "APPLIED"}).encode(),
    method="POST",
    headers={"Content-Type": "application/json"},
)
try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", errors="replace")
    if "Page not found at /api/jobs/" in body:
        raise SystemExit(f"disposition route not mounted: HTTP {exc.code} {body[:200]}")
print("disposition route OK")
PY
