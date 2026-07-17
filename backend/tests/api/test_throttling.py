"""
Tests for API throttling/rate limiting.

Tests:
- Global throttling (user rate) does not block normal traffic
- The BurstActionThrottle example pattern: attach a ScopedRateThrottle
  subclass to a view and its scope's rate from DEFAULT_THROTTLE_RATES applies
"""

import pytest
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from app.throttles import BurstActionThrottle


@pytest.mark.django_db
class TestGlobalThrottling:
    """Test global rate limiting for authenticated users."""

    def test_user_rate_limit_structure(self, authenticated_client, organisation):
        """Verify throttle configuration allows reasonable requests."""
        # Make 10 requests (well below the default user rate limit)
        for _ in range(10):
            response = authenticated_client.get('/api/configs/')
            assert response.status_code == status.HTTP_200_OK
        # No 429 expected for normal usage


class BurstView(APIView):
    """Minimal view demonstrating the scoped-throttle pattern."""
    throttle_classes = [BurstActionThrottle]

    def post(self, request):
        return Response({'status': 'ok'})


@pytest.mark.django_db
class TestBurstActionThrottle:
    """The documented example throttle enforces its 'burst' scope rate."""

    def setup_method(self):
        # DRF throttling stores request histories in the default cache;
        # clear it so counts never leak between tests.
        cache.clear()

    def teardown_method(self):
        cache.clear()

    def _post(self, view, user):
        request = APIRequestFactory().post('/burst-action/')
        force_authenticate(request, user=user)
        return view(request)

    def test_requests_over_rate_get_429(self, user):
        view = BurstView.as_view()
        with _burst_rate('2/min'):
            assert self._post(view, user).status_code == status.HTTP_200_OK
            assert self._post(view, user).status_code == status.HTTP_200_OK
            response = self._post(view, user)
            assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS

    def test_single_request_not_throttled(self, user):
        view = BurstView.as_view()
        with _burst_rate('10/min'):
            response = self._post(view, user)
            assert response.status_code == status.HTTP_200_OK


class _burst_rate:
    """Context manager pinning DEFAULT_THROTTLE_RATES['burst'] to a fixed rate.

    ScopedRateThrottle reads its rate at instantiation via api_settings, so we
    patch the DRF api_settings-backed dict directly for the duration.
    """

    def __init__(self, rate):
        self.rate = rate

    def __enter__(self):
        from rest_framework.settings import api_settings
        self._rates = api_settings.DEFAULT_THROTTLE_RATES
        self._original = self._rates.get('burst')
        self._rates['burst'] = self.rate
        return self

    def __exit__(self, *exc):
        if self._original is None:
            self._rates.pop('burst', None)
        else:
            self._rates['burst'] = self._original
        return False
