"""Django system checks for deploy-time safety.

These are defense-in-depth complements to the import-time boot guards in
settings.py: they surface misconfiguration via `manage.py check --deploy`
(run in CI/CD before a release) rather than only at process start.
"""
from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def check_test_mode_requires_debug(app_configs, **kwargs):
    """Error if TEST is enabled without DEBUG.

    TEST mode disables Clerk webhook signature verification (for CI/E2E
    seeding) and exposes test-only endpoints. settings.py already raises
    ImproperlyConfigured at import time for this combination, but a system
    check lets `manage.py check --deploy` fail a misconfigured prod that
    sets TEST=1 without DEBUG before anything is served.
    """
    errors = []
    if getattr(settings, 'TEST', False) and not getattr(settings, 'DEBUG', False):
        errors.append(
            Error(
                'TEST=1 disables webhook signature verification and must never '
                'be set in production.',
                hint='Unset TEST, or (for local/CI use only) also set DEBUG=1.',
                id='app.E001',
            )
        )
    return errors
