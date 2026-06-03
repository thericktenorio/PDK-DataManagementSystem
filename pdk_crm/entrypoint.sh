#!/usr/bin/env bash
set -euo pipefail

cd /app

# If you're using env files, ensure DJANGO_SETTINGS_MODULE is correct
: "${DJANGO_SETTINGS_MODULE:=pdk_crm.settings}"

python manage.py migrate --noinput
if [ "${ANALYTICS_ENABLED:-false}" = "true" ]; then
  python manage.py migrate --database=analytics --noinput
fi
python manage.py collectstatic --noinput

if [ "${SEED_MVP_DEMO:-false}" = "true" ]; then
  python manage.py seed_mvp_demo ${SEED_MVP_SAMPLE_CLIENT:+--with-sample-client} || exit 1
fi

exec gunicorn pdk_crm.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120