"""
Tests for custom middleware.

Tests:
- ClerkTenantMiddleware: Sets default org attributes on every request
"""

import pytest
from django.http import HttpRequest, HttpResponse

from app.middleware import ClerkTenantMiddleware


class TestClerkTenantMiddleware:
    """Tests for ClerkTenantMiddleware (defaults only)."""

    def test_sets_default_org_attributes(self):
        """Middleware sets default org attributes to None/empty."""
        request = HttpRequest()

        get_response = lambda r: HttpResponse()
        middleware = ClerkTenantMiddleware(get_response)

        middleware(request)

        assert request.org is None
        assert request.org_id is None
        assert request.org_role is None
        assert request.org_permissions == []

    def test_calls_get_response(self):
        """Middleware passes request through to get_response."""
        request = HttpRequest()
        response = HttpResponse(status=200)

        get_response = lambda r: response
        middleware = ClerkTenantMiddleware(get_response)

        result = middleware(request)

        assert result is response
