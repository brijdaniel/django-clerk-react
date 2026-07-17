"""
Tests for ClerkJWTAuthentication.

Tests org claim extraction (setting request.org, org_id, org_role, org_permissions)
which happens during DRF authentication, before permissions are checked.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from django.http import HttpRequest
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from app.authentication import ClerkJWTAuthentication
from tests.factories import OrganisationFactory, UserFactory


def _make_request_with_token(token='fake-token'):
    """Create a DRF Request wrapping a Django HttpRequest with a Bearer token."""
    django_request = HttpRequest()
    django_request.META['HTTP_AUTHORIZATION'] = f'Bearer {token}'
    # Wrap in DRF Request like the real flow
    return Request(django_request)


def _mock_jwt_decode(payload):
    """Return a patch context that mocks JWT validation and returns the given payload."""
    mock_key = MagicMock()
    mock_key.key = 'fake-key'
    return patch.multiple(
        'app.authentication',
        jwks_client=MagicMock(get_signing_key_from_jwt=MagicMock(return_value=mock_key)),
        jwt=MagicMock(
            decode=MagicMock(return_value=payload),
            ExpiredSignatureError=Exception,
            InvalidTokenError=Exception,
        ),
    )


@pytest.mark.django_db
class TestClerkJWTAuthenticationOrgExtraction:
    """Tests that authenticate() sets org attributes on the Django request."""

    def test_sets_org_from_jwt_claims(self):
        """Org attributes are set on the Django request from JWT 'o' claim."""
        org = OrganisationFactory(clerk_org_id='org_abc123')
        user = UserFactory(clerk_id='user_test1')

        payload = {
            'sub': user.clerk_id,
            'azp': 'http://localhost:5173',
            'o': {
                'id': 'org_abc123',
                'rol': 'admin',
                'per': 'read,write',
            }
        }

        request = _make_request_with_token()
        with _mock_jwt_decode(payload):
            auth = ClerkJWTAuthentication()
            result_user, result_payload = auth.authenticate(request)

        assert result_user == user
        assert request._request.org == org
        assert request._request.org_id == 'org_abc123'
        assert request._request.org_role == 'admin'
        assert request._request.org_permissions == ['read', 'write']

    def test_sets_wildcard_permissions(self):
        """Wildcard permission string is parsed correctly."""
        OrganisationFactory(clerk_org_id='org_abc123')
        user = UserFactory(clerk_id='user_test2')

        payload = {
            'sub': user.clerk_id,
            'azp': 'http://localhost:5173',
            'o': {'id': 'org_abc123', 'rol': 'admin', 'per': '*'}
        }

        request = _make_request_with_token()
        with _mock_jwt_decode(payload):
            auth = ClerkJWTAuthentication()
            auth.authenticate(request)

        assert request._request.org_permissions == ['*']

    def test_handles_empty_permissions(self):
        """Empty permission string results in empty list."""
        OrganisationFactory(clerk_org_id='org_abc123')
        user = UserFactory(clerk_id='user_test3')

        payload = {
            'sub': user.clerk_id,
            'azp': 'http://localhost:5173',
            'o': {'id': 'org_abc123', 'rol': 'member', 'per': ''}
        }

        request = _make_request_with_token()
        with _mock_jwt_decode(payload):
            auth = ClerkJWTAuthentication()
            auth.authenticate(request)

        assert request._request.org_permissions == []

    def test_handles_missing_org_claims(self):
        """No 'o' claim in JWT leaves org attributes at middleware defaults."""
        user = UserFactory(clerk_id='user_test4')

        payload = {
            'sub': user.clerk_id,
            'azp': 'http://localhost:5173',
        }

        request = _make_request_with_token()
        # Set defaults like middleware would
        request._request.org = None
        request._request.org_id = None

        with _mock_jwt_decode(payload):
            auth = ClerkJWTAuthentication()
            auth.authenticate(request)

        # Should remain None (not overwritten)
        assert request._request.org is None
        assert request._request.org_id is None

    def test_handles_nonexistent_org(self):
        """Org ID in JWT but org not in DB fails fast with a clear message.

        Regression test: this previously proceeded with org_id set but
        org=None, producing confusing view-specific failures instead of a
        clear "not synced yet" 401.
        """
        import pytest
        from rest_framework.exceptions import AuthenticationFailed

        user = UserFactory(clerk_id='user_test5')

        payload = {
            'sub': user.clerk_id,
            'azp': 'http://localhost:5173',
            'o': {'id': 'org_nonexistent', 'rol': 'member', 'per': ''}
        }

        request = _make_request_with_token()
        with _mock_jwt_decode(payload):
            auth = ClerkJWTAuthentication()
            with pytest.raises(AuthenticationFailed, match='not synced'):
                auth.authenticate(request)

    def test_no_bearer_token_returns_none(self):
        """Request without Bearer token returns None (no auth attempted)."""
        django_request = HttpRequest()
        request = Request(django_request)

        auth = ClerkJWTAuthentication()
        result = auth.authenticate(request)

        assert result is None
