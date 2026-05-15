import logging
import ssl
import uuid

import redis
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)

# Replaced by CI with the git SHA at build time (see deploy-backend.yml).
DEPLOY_SHA = 'dev'


def _get_redis_client():
    """Create a Redis client from the Celery broker URL, handling Azure TLS."""
    url = settings.CELERY_BROKER_URL
    kwargs = {}
    if url.startswith('rediss://'):
        # Strip ssl_cert_reqs from URL — redis-py rejects the string
        # "CERT_NONE" from query params, so pass the constant as a kwarg.
        url = url.split('?')[0] if 'ssl_cert_reqs' in url else url
        kwargs['ssl_cert_reqs'] = ssl.CERT_NONE
    return redis.from_url(url, socket_connect_timeout=10, socket_timeout=10, **kwargs)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        checks = {}

        try:
            connection.ensure_connection()
            checks['db'] = 'ok'
        except DatabaseError as e:
            checks['db'] = str(e)

        try:
            r = _get_redis_client()
            r.ping()
            checks['redis'] = 'ok'
        except redis.RedisError as e:
            logger.warning('Redis health check failed: %s', e, exc_info=True)
            checks['redis'] = str(e)

        all_ok = all(v == 'ok' for v in checks.values())
        status = 200 if all_ok else 503
        return Response({'status': 'ok' if all_ok else 'degraded', 'checks': checks, 'version': DEPLOY_SHA}, status=status)


class SmokeCheckView(APIView):
    """Deep health check that verifies DB writes and Redis read/write work."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        from app.models import Organisation

        checks = {}

        # DB write/read cycle using ORM — rolled back via set_rollback
        try:
            with transaction.atomic():
                obj = Organisation.objects.create(
                    clerk_org_id='_smoke_test', name='_smoke_test',
                )
                readback = Organisation.objects.filter(pk=obj.pk).values_list('name', flat=True).first()
                checks['db_write'] = 'ok' if readback == '_smoke_test' else 'read-back mismatch'
                transaction.set_rollback(True)
        except DatabaseError as e:
            checks['db_write'] = str(e)

        # Redis write/read/delete cycle
        try:
            r = _get_redis_client()
            key = f'_smoke_test_{uuid.uuid4().hex[:8]}'
            r.set(key, 'ok', ex=10)
            val = r.get(key)
            r.delete(key)
            checks['redis_write'] = 'ok' if val == b'ok' else 'read-back mismatch'
        except redis.RedisError as e:
            logger.warning('Redis smoke check failed: %s', e, exc_info=True)
            checks['redis_write'] = str(e)

        all_ok = all(v == 'ok' for v in checks.values())
        status = 200 if all_ok else 503
        return Response({'status': 'ok' if all_ok else 'degraded', 'checks': checks, 'version': DEPLOY_SHA}, status=status)
