import logging
from unittest.mock import MagicMock

from app.celery import _on_task_failure


class TestTaskFailureSignal:
    """The task_failure signal handler runs the REAL logger (via caplog) so an
    unexpected error inside the handler — e.g. a bad format string or attribute
    access on the exception — surfaces as a test failure instead of being hidden
    behind a mocked logger that swallows everything.
    """

    def test_logs_error_on_task_failure(self, caplog, propagate_app_logs):
        sender = MagicMock()
        sender.name = 'app.celery.worker_heartbeat'
        exc = ValueError('something broke')

        with caplog.at_level(logging.ERROR, logger='app.celery'):
            _on_task_failure(
                sender=sender,
                task_id='abc-123',
                exception=exc,
                traceback=None,
            )

        records = [r for r in caplog.records if r.name == 'app.celery']
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        # The real logger formats the % args — assert on the rendered message.
        msg = record.getMessage()
        assert 'worker_heartbeat' in msg
        assert 'abc-123' in msg
        assert 'something broke' in msg
        # exc_info is attached so the traceback reaches Sentry/Azure Monitor.
        assert record.exc_info is not None
        assert record.exc_info[1] is exc

    def test_handles_missing_sender(self, caplog, propagate_app_logs):
        exc = RuntimeError('fail')

        with caplog.at_level(logging.ERROR, logger='app.celery'):
            _on_task_failure(
                sender=None,
                task_id='xyz-456',
                exception=exc,
                traceback=None,
            )

        records = [r for r in caplog.records if r.name == 'app.celery']
        assert len(records) == 1
        msg = records[0].getMessage()
        assert 'unknown' in msg
        assert 'xyz-456' in msg
