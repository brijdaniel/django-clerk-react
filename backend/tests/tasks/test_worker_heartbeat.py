"""Tests for the worker_heartbeat beat task.

The task writes a timestamp to the broker Redis so /api/health/worker/ can
prove that beat fired AND a worker consumed the task. Redis is mocked at
app.celery._get_redis_client (patched where it is imported).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import redis as redis_lib
from django.conf import settings
from django.test import override_settings

from app.celery import worker_heartbeat


class TestWorkerHeartbeat:
    @override_settings(WORKER_HEARTBEAT_INTERVAL_SECONDS=60)
    def test_writes_heartbeat_key_with_ttl(self):
        client = MagicMock()
        with patch('app.celery._get_redis_client', return_value=client):
            result = worker_heartbeat()

        assert result == {'written': True}
        client.set.assert_called_once()
        args, kwargs = client.set.call_args
        assert args[0] == settings.WORKER_HEARTBEAT_KEY
        # Value is an ISO timestamp the health probe can parse for staleness.
        datetime.fromisoformat(args[1])
        # TTL = 5 x interval, floored at 60s.
        assert kwargs['ex'] == 300

    @override_settings(WORKER_HEARTBEAT_INTERVAL_SECONDS=5)
    def test_ttl_floored_at_60_seconds(self):
        client = MagicMock()
        with patch('app.celery._get_redis_client', return_value=client):
            worker_heartbeat()

        assert client.set.call_args.kwargs['ex'] == 60

    def test_redis_error_is_swallowed(self):
        """A Redis blip must never fail the task (it would spam task_failure)."""
        client = MagicMock()
        client.set.side_effect = redis_lib.RedisError('broker down')
        with patch('app.celery._get_redis_client', return_value=client):
            result = worker_heartbeat()

        assert result == {'written': False}
