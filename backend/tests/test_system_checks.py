"""Tests for the deploy-time system checks in app/checks.py.

These guard against a misconfigured production that enables TEST mode (which
disables Clerk webhook signature verification) without DEBUG. The check is the
`manage.py check --deploy` complement to the import-time guard in settings.py.
"""
from django.core.checks import Error
from django.test import override_settings

from app.checks import check_test_mode_requires_debug


def test_errors_when_test_without_debug():
    with override_settings(TEST=True, DEBUG=False):
        errors = check_test_mode_requires_debug(app_configs=None)

    assert len(errors) == 1
    error = errors[0]
    assert isinstance(error, Error)
    assert error.id == 'app.E001'


def test_no_error_when_test_with_debug():
    with override_settings(TEST=True, DEBUG=True):
        errors = check_test_mode_requires_debug(app_configs=None)

    assert errors == []


def test_no_error_when_not_test():
    with override_settings(TEST=False, DEBUG=False):
        errors = check_test_mode_requires_debug(app_configs=None)

    assert errors == []


def test_no_error_when_not_test_and_debug():
    with override_settings(TEST=False, DEBUG=True):
        errors = check_test_mode_requires_debug(app_configs=None)

    assert errors == []


def test_check_is_registered_for_deploy():
    """The check is registered with deploy=True so `check --deploy` runs it."""
    from django.core.checks.registry import registry

    # Importing app.checks (also done by apps.ready()) applies the decorators.
    import app.checks  # noqa: F401

    deploy_checks = registry.get_checks(include_deployment_checks=True)
    assert check_test_mode_requires_debug in deploy_checks

    # And it must NOT run under a plain `manage.py check` (deploy-only).
    non_deploy_checks = registry.get_checks(include_deployment_checks=False)
    assert check_test_mode_requires_debug not in non_deploy_checks
