# Multi-stage build for 1Reach backend.
# Same image is used for API, worker, and beat — CONTAINER_ROLE env var selects the command.
# See entrypoint.sh for role-based command selection.

# --- Stage 1: Build ---
FROM python:3.12-slim AS builder

RUN pip install uv

WORKDIR /app

# Install dependencies first (layer cache — only re-runs when deps change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen

# Copy application code
COPY . .
RUN chmod +x entrypoint.sh

# Stamp deploy version (overridden by CI via --build-arg)
ARG DEPLOY_SHA=dev
RUN sed -i "s/DEPLOY_SHA = 'dev'/DEPLOY_SHA = '${DEPLOY_SHA}'/" app/health.py

# Collect static files (Django admin CSS/JS for WhiteNoise)
# Dummy DJANGO_SECRET_KEY is sufficient — collectstatic only needs static finders, not DB
RUN DJANGO_SECRET_KEY=build-only \
    DJANGO_SETTINGS_MODULE=app.settings \
    uv run python manage.py collectstatic --noinput

# --- Stage 2: Runtime ---
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY --from=builder /app /app

ENV DJANGO_SETTINGS_MODULE=app.settings

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]

# Default: run the API server. Override with CONTAINER_ROLE env var for worker/beat.
# See entrypoint.sh for the role-based command selection.
CMD ["api"]
