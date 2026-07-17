from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from django.db import DatabaseError
from django.test import override_settings
from redis import RedisError
from rest_framework.test import APIClient


@pytest.mark.django_db
class TestHealthCheck:
    def setup_method(self):
        self.client = APIClient()

    def test_returns_200_when_healthy(self):
        response = self.client.get('/api/health/')
        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['checks']['db'] == 'ok'
        assert response.data['checks']['redis'] == 'ok'
        assert response.data['version'] == 'dev'

    def test_no_auth_required(self):
        """Unauthenticated request succeeds — endpoint uses AllowAny."""
        response = self.client.get('/api/health/')
        assert response.status_code == 200

    def test_returns_503_when_db_fails(self):
        with patch('app.health.connection') as mock_conn:
            mock_conn.ensure_connection.side_effect = DatabaseError('DB unavailable')
            response = self.client.get('/api/health/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert response.data['checks']['db'] != 'ok'
        assert response.data['checks']['redis'] == 'ok'

    def test_returns_503_when_redis_fails(self):
        with patch('app.health._get_redis_client') as mock_get:
            mock_get.return_value.ping.side_effect = RedisError('Redis unavailable')
            response = self.client.get('/api/health/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert response.data['checks']['redis'] != 'ok'
        assert response.data['checks']['db'] == 'ok'

    def test_returns_503_when_both_fail(self):
        with patch('app.health.connection') as mock_conn, \
             patch('app.health._get_redis_client') as mock_get:
            mock_conn.ensure_connection.side_effect = DatabaseError('DB down')
            mock_get.return_value.ping.side_effect = RedisError('Redis down')
            response = self.client.get('/api/health/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert response.data['checks']['db'] != 'ok'
        assert response.data['checks']['redis'] != 'ok'


@pytest.mark.django_db
class TestSmokeCheck:
    def setup_method(self):
        self.client = APIClient()

    def test_returns_200_when_healthy(self):
        response = self.client.get('/api/health/smoke/')
        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['checks']['db_write'] == 'ok'
        assert response.data['checks']['redis_write'] == 'ok'
        assert response.data['version'] == 'dev'

    def test_no_auth_required(self):
        response = self.client.get('/api/health/smoke/')
        assert response.status_code == 200

    def test_db_write_leaves_no_data(self):
        """Smoke test rolls back — no Organisation row persists."""
        from app.models import Organisation
        before = Organisation.objects.filter(name='_smoke_test').count()
        self.client.get('/api/health/smoke/')
        after = Organisation.objects.filter(name='_smoke_test').count()
        assert before == after

    def test_returns_503_when_db_write_fails(self):
        with patch('app.health.transaction') as mock_tx:
            mock_tx.atomic.side_effect = DatabaseError('DB write failed')
            mock_tx.set_rollback = lambda x: None
            response = self.client.get('/api/health/smoke/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert response.data['checks']['db_write'] != 'ok'

    def test_returns_503_when_redis_write_fails(self):
        with patch('app.health._get_redis_client') as mock_get:
            mock_get.return_value.set.side_effect = RedisError('Redis write failed')
            response = self.client.get('/api/health/smoke/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert response.data['checks']['redis_write'] != 'ok'
        assert response.data['checks']['db_write'] == 'ok'


@pytest.mark.django_db
class TestWorkerHealthCheck:
    """/api/health/worker/ — detects a dead or misconfigured Celery worker/beat."""

    def setup_method(self):
        self.client = APIClient()

    def _fake_redis(self, heartbeat_iso=None, ping_ok=True):
        r = MagicMock()
        if not ping_ok:
            r.ping.side_effect = RedisError('broker down')
        r.get.return_value = heartbeat_iso.encode() if heartbeat_iso else None
        return r

    @staticmethod
    def _iso(seconds_ago=0):
        return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).isoformat()

    def test_200_when_broker_ok_and_heartbeat_fresh(self):
        with patch('app.health._get_redis_client', return_value=self._fake_redis(self._iso(0))):
            response = self.client.get('/api/health/worker/')
        assert response.status_code == 200
        assert response.data['status'] == 'ok'
        assert response.data['checks']['broker'] == 'ok'
        assert response.data['checks']['heartbeat'] == 'ok'

    @override_settings(WORKER_HEARTBEAT_INTERVAL_SECONDS=60, WORKER_HEARTBEAT_STALE_FACTOR=2)
    def test_503_when_heartbeat_stale(self):
        # 600s old > 2 x 60s
        with patch('app.health._get_redis_client', return_value=self._fake_redis(self._iso(600))):
            response = self.client.get('/api/health/worker/')
        assert response.status_code == 503
        assert response.data['status'] == 'degraded'
        assert 'stale' in response.data['checks']['heartbeat']

    def test_503_when_heartbeat_missing(self):
        """No heartbeat key — worker/beat never ran."""
        with patch('app.health._get_redis_client', return_value=self._fake_redis(None)):
            response = self.client.get('/api/health/worker/')
        assert response.status_code == 503
        assert response.data['checks']['heartbeat'] == 'missing'

    def test_503_when_broker_unreachable(self):
        with patch('app.health._get_redis_client', return_value=self._fake_redis(ping_ok=False)):
            response = self.client.get('/api/health/worker/')
        assert response.status_code == 503
        assert response.data['checks']['broker'] != 'ok'

    def test_no_auth_required(self):
        with patch('app.health._get_redis_client', return_value=self._fake_redis(self._iso(0))):
            response = self.client.get('/api/health/worker/')
        assert response.status_code == 200


class TestSwaggerGating:
    """Swagger/OpenAPI endpoints should only be accessible when DEBUG=True."""

    def setup_method(self):
        self.client = APIClient()

    @override_settings(DEBUG=False)
    def test_swagger_not_accessible_with_debug_false(self):
        response = self.client.get('/api/schema/')
        assert response.status_code == 404

    def test_swagger_urls_present_in_debug_urlconf(self):
        """Swagger URL patterns are defined in app.urls when DEBUG=True.

        URL patterns are evaluated at import time so we can't test the live
        endpoint with override_settings; instead we verify the conditional
        branch in the URL conf adds the expected named patterns.
        """
        import importlib
        from django.test import override_settings
        from django.urls import clear_url_caches

        with override_settings(DEBUG=True):
            import app.urls
            importlib.reload(app.urls)
            clear_url_caches()
            url_names = [p.name for p in app.urls.urlpatterns if hasattr(p, 'name')]
            importlib.reload(app.urls)  # restore to original DEBUG=False state
            clear_url_caches()

        assert 'schema' in url_names
        assert 'swagger-ui' in url_names
