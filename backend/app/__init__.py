# Celery app is defined in app.celery and loaded directly by the worker (-A app.celery).
# No import here — avoids AppRegistryNotReady during Django startup.
