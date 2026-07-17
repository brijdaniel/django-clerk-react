import logging
import ssl
import uuid
from datetime import datetime, timezone

import certifi
import redis
from django.conf import settings
from django.db import DatabaseError, connection, transaction
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from app.models import Organisation

logger = logging.getLogger(__name__)

# Replaced by CI with the git SHA at build time (see deploy-backend.yml).
DEPLOY_SHA = 'dev'


def _get_redis_client():
    """Create a Redis client from the Celery broker URL, handling Azure TLS.

    TLS params are passed as kwargs (redis-py rejects ssl.CERT_* constant
    names in query params), with certificates verified like everywhere else.
    """
    url = settings.CELERY_BROKER_URL
    kwargs = {}
    if url.startswith('rediss://'):
        url = url.split('?')[0]
        kwargs['ssl_cert_reqs'] = ssl.CERT_REQUIRED
        kwargs['ssl_ca_certs'] = certifi.where()
    return redis.from_url(url, socket_connect_timeout=10, socket_timeout=10, **kwargs)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # ACA probes poll frequently

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


class WorkerHealthView(APIView):
    """Liveness of the Celery worker + beat via the worker heartbeat.

    The worker_heartbeat beat task writes settings.WORKER_HEARTBEAT_KEY to the
    broker Redis each tick — a fresh value proves beat fired AND a worker
    consumed the task. A stale/missing heartbeat means the worker or beat is
    down (e.g. a misconfigured container running the wrong command), even when
    /api/health/ is green. The heartbeat is the authoritative signal; an HTTP
    probe against the api container reads it from the shared broker Redis the
    worker writes to.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # ACA/deploy probes poll frequently

    def get(self, request):
        checks = {}

        r = None
        try:
            r = _get_redis_client()
            r.ping()
            checks['broker'] = 'ok'
        except redis.RedisError as e:
            logger.warning('Worker health broker check failed: %s', e, exc_info=True)
            checks['broker'] = str(e)

        interval = float(getattr(settings, 'WORKER_HEARTBEAT_INTERVAL_SECONDS', 60))
        stale_after = getattr(settings, 'WORKER_HEARTBEAT_STALE_FACTOR', 2) * interval
        if r is None:
            checks['heartbeat'] = 'unknown (broker unreachable)'
        else:
            try:
                raw = r.get(settings.WORKER_HEARTBEAT_KEY)
                if not raw:
                    checks['heartbeat'] = 'missing'
                else:
                    ts = datetime.fromisoformat(raw.decode() if isinstance(raw, bytes) else raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - ts).total_seconds()
                    checks['heartbeat'] = 'ok' if age <= stale_after else f'stale ({int(age)}s)'
            except (redis.RedisError, ValueError) as e:
                checks['heartbeat'] = f'error: {e}'

        all_ok = all(v == 'ok' for v in checks.values())
        status = 200 if all_ok else 503
        return Response({'status': 'ok' if all_ok else 'degraded', 'checks': checks, 'version': DEPLOY_SHA}, status=status)


class SmokeCheckView(APIView):
    """Deep health check that verifies DB writes and Redis read/write work."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []  # deploy smoke tests poll frequently

    def get(self, request):
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
