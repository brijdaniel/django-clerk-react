"""
pytest configuration and shared fixtures for all tests.

This module provides:
- Database setup (pytest-django)
- DRF APIClient fixtures
- Model instance fixtures (users, orgs, memberships)
- Authentication fixtures (JWT payloads, authenticated clients)
"""

import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from app.models import Organisation, OrganisationMembership, User


# ============================================================================
# Database and Client Fixtures
# ============================================================================

@pytest.fixture
def api_client():
    """Return a Django REST Framework APIClient."""
    return APIClient()


@pytest.fixture
def authenticated_client(user, organisation, org_membership):
    """Return an authenticated API client with JWT token and org context."""
    client = APIClient()
    client.force_authenticate(user=user)

    # Monkey-patch DRF's APIView dispatch to inject org context
    from rest_framework.views import APIView
    original_dispatch = APIView.dispatch

    def patched_dispatch(self, request, *args, **kwargs):
        """Dispatch with org context injected."""
        # Inject org context that middleware would normally add
        request.org = organisation
        request.org_id = organisation.clerk_org_id
        request.org_role = 'member'
        request.org_permissions = []
        return original_dispatch(self, request, *args, **kwargs)

    APIView.dispatch = patched_dispatch

    yield client

    # Restore original
    APIView.dispatch = original_dispatch


# ============================================================================
# User and Organisation Fixtures
# ============================================================================

@pytest.fixture
def user(db):
    """Create a test user."""
    return User.objects.create(
        clerk_id='user_test123',
        email='test@example.com',
        first_name='Test',
        last_name='User'
    )


@pytest.fixture
def admin_user(db):
    """Create an admin user."""
    return User.objects.create(
        clerk_id='user_admin123',
        email='admin@example.com',
        first_name='Admin',
        last_name='User'
    )


@pytest.fixture
def organisation(db):
    """Create a test organisation.

    Funded by default (real orgs get free credits at signup) so prepaid
    deductions don't trip the record_usage balance floor in tests that
    aren't about billing. Balance-sensitive tests set their own value.
    """
    return Organisation.objects.create(
        clerk_org_id='org_test123',
        name='Test Organisation',
        slug='test-organisation',
        credit_balance=Decimal('100.00'),
    )


@pytest.fixture
def another_org(db):
    """Create a second organisation for multi-tenancy tests."""
    return Organisation.objects.create(
        clerk_org_id='org_other123',
        name='Other Organisation',
        slug='other-organisation'
    )


@pytest.fixture
def org_membership(db, user, organisation):
    """Create organisation membership for test user."""
    return OrganisationMembership.objects.create(
        user=user,
        organisation=organisation,
        role='member'
    )


@pytest.fixture
def admin_membership(db, admin_user, organisation):
    """Create admin organisation membership."""
    return OrganisationMembership.objects.create(
        user=admin_user,
        organisation=organisation,
        role='admin'
    )


# ============================================================================
# Logging Fixtures
# ============================================================================

@pytest.fixture
def propagate_app_logs():
    """Let pytest's caplog see records from the 'app.*' loggers.

    settings.LOGGING sets propagate=False on the 'app' logger (records go to its
    own console handler, not the root where caplog attaches). Tests that assert
    on real log output via caplog enable propagation for their duration.
    """
    app_logger = logging.getLogger('app')
    original = app_logger.propagate
    app_logger.propagate = True
    try:
        yield
    finally:
        app_logger.propagate = original


# ============================================================================
# JWT Token Fixtures
# ============================================================================

@pytest.fixture
def jwt_payload(user, organisation):
    """Create a JWT payload for testing."""
    return {
        'sub': user.clerk_id,
        'org_id': organisation.clerk_org_id,
        'org_role': 'member',
        'org_permissions': [],
        'azp': 'http://localhost:5173',
        'exp': (timezone.now() + timedelta(hours=1)).timestamp(),
        'iat': timezone.now().timestamp()
    }


@pytest.fixture
def admin_jwt_payload(admin_user, organisation):
    """Create an admin JWT payload."""
    return {
        'sub': admin_user.clerk_id,
        'org_id': organisation.clerk_org_id,
        'org_role': 'admin',
        'org_permissions': ['*'],
        'azp': 'http://localhost:5173',
        'exp': (timezone.now() + timedelta(hours=1)).timestamp(),
        'iat': timezone.now().timestamp()
    }
