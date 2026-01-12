#!/usr/bin/env bash
set -euo pipefail

cd /app

# If you're using env files, ensure DJANGO_SETTINGS_MODULE is correct
: "${DJANGO_SETTINGS_MODULE:=pdk_crm.settings}"

python manage.py migrate --noinput
python manage.py collectstatic --noinput

exec gunicorn pdk_crm.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --timeout 120