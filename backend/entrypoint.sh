#!/bin/bash
set -e

# --- Wait for database ---
echo "Waiting for database..."
for i in $(seq 1 30); do
  uv run python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null && echo "Database is ready." && break
  echo "Database not ready (attempt $i/30), retrying in 5s..."
  sleep 5
done

# --- Select command based on role ---
# Role can come from the first argument (e.g. docker-compose `command: ["worker"]`)
# or the CONTAINER_ROLE env var (set on each ACA container app via Bicep).
#
# Precedence is deliberate. The image's default CMD is ["api"], and all three ACA
# container apps (api/worker/beat) inherit it — they are distinguished ONLY by
# CONTAINER_ROLE. So when the first arg names a known role, CONTAINER_ROLE wins
# (otherwise the default "api" arg would override CONTAINER_ROLE=worker/beat and
# every app would start gunicorn). A first arg that is NOT a role is treated as an
# arbitrary command (pytest, manage.py, sh, ...) and run as-is, so
# `docker compose run backend ... pytest` is never hijacked into starting a server.
case "${1:-}" in
  api|worker|beat) ROLE="${CONTAINER_ROLE:-$1}" ;;
  '')              ROLE="${CONTAINER_ROLE:-api}" ;;
  *)               ROLE="__command__" ;;
esac

case "$ROLE" in
  api)
    # Migration check — CD workflows apply migrations before deploying the image.
    # SKIP_AUTO_MIGRATE=true (prod): refuse to start if migrations are pending.
    # SKIP_AUTO_MIGRATE=false (dev): auto-apply as a convenience safety net.
    if uv run python manage.py migrate --check 2>/dev/null; then
      echo "No pending migrations."
    elif [ "${SKIP_AUTO_MIGRATE:-false}" = "true" ]; then
      echo "ERROR: Pending migrations detected but SKIP_AUTO_MIGRATE=true."
      echo "Migrations must be applied via the CD pipeline before deploying."
      uv run python manage.py showmigrations --plan | grep "\[ \]" || true
      exit 1
    else
      echo "WARNING: Unapplied migrations detected. Running migrate..."
      uv run python manage.py migrate --no-input || { echo "Migration failed"; exit 1; }
    fi
    exec uv run python -m gunicorn app.asgi:application \
      -k app.worker.Worker \
      --bind 0.0.0.0:8000 \
      --workers 2 \
      --timeout 120 \
      --access-logfile -
    ;;
  worker)
    exec uv run python -m celery -A app.celery worker \
      --loglevel=info \
      -Q default \
      --concurrency=2
    ;;
  beat)
    exec uv run python -m celery -A app.celery beat \
      --loglevel=info \
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    ;;
  *)
    # Not a known role — run the arguments as a command (e.g. pytest, manage.py, etc.)
    exec "$@"
    ;;
esac
