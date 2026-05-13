"""
Unit tests for the send_message Celery task.

All tests call the task function directly (not via .delay()) to avoid
needing a running Redis broker. Provider is mocked at app.celery.get_sms_provider.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from django.utils import timezone

from app.models import (
    CreditTransaction,
    MessageFormat,
    Schedule,
    ScheduleStatus,
)
from app.celery import send_message
from app.utils.sms import SendResult
from app.utils.billing import get_balance, grant_credits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_queued(db, organisation, user, contact, **kwargs):
    defaults = dict(
        organisation=organisation,
        contact=contact,
        phone='0412345678',
        text='Hello test',
        scheduled_time=timezone.now(),
        status=ScheduleStatus.QUEUED,
        format=MessageFormat.SMS,
        message_parts=1,
        max_retries=3,
        created_by=user,
        updated_by=user,
    )
    defaults.update(kwargs)
    return Schedule.objects.create(**defaults)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendMessageSuccess:
    def test_success_marks_schedule_sent(
        self, schedule_queued, mock_sms_provider
    ):
        send_message(schedule_queued.pk)

        schedule_queued.refresh_from_db()
        assert schedule_queued.status == ScheduleStatus.SENT
        assert schedule_queued.sent_time is not None
        assert schedule_queued.provider_message_id == 'mock-sms-123'
        assert schedule_queued.error is None

    def test_success_records_usage_for_subscribed_org(
        self, schedule_queued, mock_sms_provider
    ):
        org = schedule_queued.organisation
        org.billing_mode = org.BILLING_SUBSCRIBED
        org.save()

        send_message(schedule_queued.pk)

        tx = CreditTransaction.objects.filter(
            organisation=org,
            schedule=schedule_queued,
            transaction_type=CreditTransaction.USAGE,
        ).first()
        assert tx is not None

    def test_success_does_not_double_deduct_trial_org(
        self, db, organisation, contact, user, mock_sms_provider
    ):
        """Prepaid credits reserved at dispatch time; task must NOT deduct again."""
        grant_credits(organisation, Decimal('10.00'), 'test grant')
        schedule = _make_queued(db, organisation, user, contact)

        # Simulate credit reservation at dispatch time
        from app.utils.billing import record_usage
        record_usage(organisation, 1, 'sms', 'dispatch reservation', user, schedule)
        balance_after_reserve = get_balance(organisation)

        send_message(schedule.pk)

        # Balance must not change further
        assert get_balance(organisation) == balance_after_reserve

    def test_mms_dispatched_via_send_mms_method(
        self, db, organisation, contact, user, mock_sms_provider
    ):
        schedule = Schedule.objects.create(
            organisation=organisation,
            contact=contact,
            phone='0412345678',
            text='Check this',
            scheduled_time=timezone.now(),
            status=ScheduleStatus.QUEUED,
            format=MessageFormat.MMS,
            media_url='https://example.com/img.jpg',
            message_parts=1,
            max_retries=3,
            created_by=user,
            updated_by=user,
        )

        with patch('app.celery.get_storage_provider'):
            send_message(schedule.pk)

        mock_sms_provider.send_mms.assert_called_once()
        mock_sms_provider.send_sms.assert_not_called()

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.SENT


# ---------------------------------------------------------------------------
# Transient failure / retry path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendMessageTransientFailure:
    def test_transient_failure_sets_retrying_status(
        self, schedule_queued, mock_sms_provider_transient_fail
    ):
        with patch('app.celery.send_message.apply_async'):
            send_message(schedule_queued.pk)

        schedule_queued.refresh_from_db()
        assert schedule_queued.status == ScheduleStatus.RETRYING
        assert schedule_queued.retry_count == 1
        assert schedule_queued.next_retry_at is not None
        assert schedule_queued.failure_category == 'server_error'

    def test_transient_failure_re_enqueues_task(
        self, schedule_queued, mock_sms_provider_transient_fail
    ):
        with patch('app.celery.send_message.apply_async') as mock_async:
            send_message(schedule_queued.pk)

        mock_async.assert_called_once()
        call_kwargs = mock_async.call_args
        assert call_kwargs[1]['countdown'] > 0

    def test_transient_failure_at_max_retries_marks_failed(
        self, schedule_queued_at_max_retries, mock_sms_provider_transient_fail
    ):
        send_message(schedule_queued_at_max_retries.pk)

        schedule_queued_at_max_retries.refresh_from_db()
        assert schedule_queued_at_max_retries.status == ScheduleStatus.FAILED

    def test_transient_failure_at_max_retries_refunds_trial_credits(
        self, db, organisation, contact, user, mock_sms_provider_transient_fail
    ):
        grant_credits(organisation, Decimal('10.00'), 'test')
        schedule = _make_queued(db, organisation, user, contact, max_retries=0, retry_count=0)

        from app.utils.billing import record_usage
        record_usage(organisation, 1, 'sms', 'dispatch', user, schedule)
        balance_before = get_balance(organisation)

        send_message(schedule.pk)

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.FAILED
        # Balance should be restored
        assert get_balance(organisation) == balance_before + settings.SMS_RATE


# ---------------------------------------------------------------------------
# Permanent failure path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendMessagePermanentFailure:
    def test_permanent_failure_marks_failed_immediately(
        self, schedule_queued, mock_sms_provider_permanent_fail
    ):
        send_message(schedule_queued.pk)

        schedule_queued.refresh_from_db()
        assert schedule_queued.status == ScheduleStatus.FAILED
        assert schedule_queued.retry_count == 0  # Never retried

    def test_permanent_failure_refunds_trial_credits(
        self, db, organisation, contact, user, mock_sms_provider_permanent_fail
    ):
        grant_credits(organisation, Decimal('10.00'), 'test')
        schedule = _make_queued(db, organisation, user, contact)

        from app.utils.billing import record_usage
        record_usage(organisation, 1, 'sms', 'dispatch', user, schedule)
        balance_before = get_balance(organisation)

        send_message(schedule.pk)

        # Refund restores SMS rate
        assert get_balance(organisation) == balance_before + settings.SMS_RATE
        assert CreditTransaction.objects.filter(
            organisation=organisation,
            schedule=schedule,
            transaction_type=CreditTransaction.REFUND,
        ).exists()

    def test_permanent_failure_sets_failure_category(
        self, schedule_queued, mock_sms_provider_permanent_fail
    ):
        send_message(schedule_queued.pk)

        schedule_queued.refresh_from_db()
        assert schedule_queued.failure_category == 'invalid_number'


# ---------------------------------------------------------------------------
# Idempotency / concurrency guards
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendMessageIdempotency:
    def test_already_sent_schedule_is_skipped(
        self, schedule_sent, mock_sms_provider
    ):
        result = send_message(schedule_sent.pk)

        assert result['skipped'] is True
        assert result['reason'] == 'not_found_or_wrong_status'
        mock_sms_provider.send_sms.assert_not_called()

    def test_nonexistent_schedule_is_skipped(
        self, db, mock_sms_provider
    ):
        result = send_message(99999)

        assert result['skipped'] is True
        mock_sms_provider.send_sms.assert_not_called()


# ---------------------------------------------------------------------------
# Concurrency lock path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendMessageConcurrency:
    def test_concurrent_lock_is_discarded(self, db, mock_sms_provider):
        """OperationalError from select_for_update(nowait=True) returns concurrent_lock skip."""
        from django.db import OperationalError
        from unittest.mock import MagicMock

        mock_qs = MagicMock()
        mock_qs.get.side_effect = OperationalError('could not obtain lock on row in relation "schedules"')

        with patch.object(Schedule.objects, 'select_for_update', return_value=mock_qs):
            result = send_message(12345)

        assert result == {'skipped': True, 'reason': 'concurrent_lock'}
        mock_sms_provider.send_sms.assert_not_called()


# ---------------------------------------------------------------------------
# classify_failure fallback path
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestHandleFailureClassification:
    def test_classifies_via_error_code_when_no_failure_category(
        self, db, organisation, contact, user
    ):
        """When provider omits failure_category, classify_failure() is used to determine it."""
        schedule = _make_queued(db, organisation, user, contact, max_retries=0)

        # Provider returns raw error fields only — no pre-classified failure_category
        raw_result = SendResult(
            success=False,
            error='Invalid phone number',
            message_parts=1,
            error_code='21211',   # Twilio "invalid number" code
            http_status=400,
        )
        with patch('app.celery.get_sms_provider') as mock_provider_factory:
            mock_provider = mock_provider_factory.return_value
            mock_provider.send_sms.return_value = raw_result
            send_message(schedule.pk)

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.FAILED
        # classifier maps 21211 → invalid_number (permanent)
        assert schedule.failure_category == 'invalid_number'

    def test_classifies_via_http_status_when_no_error_code(
        self, db, organisation, contact, user
    ):
        """When no error_code, classify_failure() falls back to http_status heuristic."""
        schedule = _make_queued(db, organisation, user, contact, max_retries=0)

        raw_result = SendResult(
            success=False,
            error='Service temporarily unavailable',
            message_parts=1,
            http_status=503,      # server-side transient — would retry if max_retries > 0
        )
        with patch('app.celery.get_sms_provider') as mock_provider_factory:
            mock_provider = mock_provider_factory.return_value
            mock_provider.send_sms.return_value = raw_result
            send_message(schedule.pk)

        schedule.refresh_from_db()
        # max_retries=0 so it fails immediately, but category should reflect transient
        assert schedule.status == ScheduleStatus.FAILED
        assert schedule.failure_category in ('server_error', 'provider_timeout', 'unknown_transient')


# ---------------------------------------------------------------------------
# _estimate_parts helper
# ---------------------------------------------------------------------------

class TestEstimateParts:
    """_estimate_parts is a pure function — no DB needed."""

    def test_mms_always_one_part(self):
        from app.celery import _estimate_parts
        assert _estimate_parts('any text', 'mms') == 1

    def test_sms_short_message_is_one_part(self):
        from app.celery import _estimate_parts
        assert _estimate_parts('Hello', 'sms') == 1

    def test_sms_exactly_160_chars_is_one_part(self):
        from app.celery import _estimate_parts
        assert _estimate_parts('x' * 160, 'sms') == 1

    def test_sms_161_chars_is_two_parts(self):
        from app.celery import _estimate_parts
        # 161 chars → ceil(161/153) = 2
        assert _estimate_parts('x' * 161, 'sms') == 2

    def test_sms_306_chars_is_two_parts(self):
        from app.celery import _estimate_parts
        assert _estimate_parts('x' * 306, 'sms') == 2

    def test_sms_empty_message_is_one_part(self):
        from app.celery import _estimate_parts
        assert _estimate_parts('', 'sms') == 1

    def test_sms_none_message_is_one_part(self):
        from app.celery import _estimate_parts
        assert _estimate_parts(None, 'sms') == 1


# ---------------------------------------------------------------------------
# Parent group schedule status sync
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestParentStatusSync:
    def test_parent_status_sent_when_all_children_sent(
        self, group_schedule_with_children, mock_sms_provider
    ):
        parent = group_schedule_with_children
        children = list(Schedule.objects.filter(parent=parent))

        # Queue all children
        Schedule.objects.filter(parent=parent).update(status=ScheduleStatus.QUEUED)

        for child in children:
            child.refresh_from_db()
            send_message(child.pk)

        parent.refresh_from_db()
        assert parent.status == ScheduleStatus.SENT

    def test_parent_status_failed_when_child_fails(
        self, group_schedule_with_children, mock_sms_provider, mock_sms_provider_permanent_fail
    ):
        parent = group_schedule_with_children
        children = list(Schedule.objects.filter(parent=parent))

        # Queue all children
        Schedule.objects.filter(parent=parent).update(status=ScheduleStatus.QUEUED)

        # Send first child successfully
        send_message(children[0].pk)

        # Fail the rest permanently
        with patch('app.celery.get_sms_provider') as mock:
            from unittest.mock import Mock
            provider = Mock()
            provider.send_sms.return_value = SendResult(
                success=False, error='Invalid number', message_parts=1,
                error_code='21211', http_status=400,
                failure_category='invalid_number',
            )
            mock.return_value = provider
            for child in children[1:]:
                child.refresh_from_db()
                send_message(child.pk)

        parent.refresh_from_db()
        assert parent.status == ScheduleStatus.FAILED

    def test_parent_status_processing_while_children_pending(
        self, group_schedule_with_children, mock_sms_provider
    ):
        parent = group_schedule_with_children
        children = list(Schedule.objects.filter(parent=parent))

        # Queue and send only the first child
        children[0].status = ScheduleStatus.QUEUED
        children[0].save()
        send_message(children[0].pk)

        parent.refresh_from_db()
        assert parent.status == ScheduleStatus.PROCESSING

    def test_no_error_for_schedule_without_parent(
        self, schedule_queued, mock_sms_provider
    ):
        """Schedules without a parent should not error during sync."""
        assert schedule_queued.parent is None
        send_message(schedule_queued.pk)

        schedule_queued.refresh_from_db()
        assert schedule_queued.status == ScheduleStatus.SENT


# ---------------------------------------------------------------------------
# Media blob cleanup on terminal state
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMediaBlobCleanup:
    def test_mms_blob_not_deleted_on_sent(
        self, db, organisation, contact, user, mock_sms_provider
    ):
        """Media blob is NOT deleted on SENT — Welcorp still needs to fetch it."""
        schedule = _make_queued(
            db, organisation, user, contact,
            format=MessageFormat.MMS,
            media_url='https://myaccount.blob.core.windows.net/media/abc123.png?sv=2022&sig=token',
        )

        with patch('app.celery.get_storage_provider') as mock_storage:
            send_message(schedule.pk)

            mock_storage.assert_not_called()

    def test_sms_no_blob_cleanup(
        self, schedule_queued, mock_sms_provider
    ):
        """SMS schedules (no media_url) don't trigger blob cleanup."""
        with patch('app.celery.get_storage_provider') as mock_storage:
            send_message(schedule_queued.pk)
            mock_storage.assert_not_called()

    def test_mms_blob_not_deleted_on_permanent_failure(
        self, db, organisation, contact, user, mock_sms_provider_permanent_fail
    ):
        """Media blob is NOT deleted on permanent failure — deferred to cleanup_stale_media_blobs."""
        schedule = _make_queued(
            db, organisation, user, contact,
            format=MessageFormat.MMS,
            media_url='https://myaccount.blob.core.windows.net/media/def456.png?sv=2022&sig=token',
        )

        with patch('app.celery.get_storage_provider') as mock_storage:
            send_message(schedule.pk)

            mock_storage.assert_not_called()

    def test_mms_sent_status_without_blob_cleanup(
        self, db, organisation, contact, user, mock_sms_provider
    ):
        """MMS schedule reaches SENT without touching blob storage."""
        schedule = _make_queued(
            db, organisation, user, contact,
            format=MessageFormat.MMS,
            media_url='https://myaccount.blob.core.windows.net/media/fail.png?sv=2022&sig=token',
        )

        with patch('app.celery.get_storage_provider') as mock_storage:
            send_message(schedule.pk)
            mock_storage.assert_not_called()

        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.SENT

    def test_no_cleanup_during_retry(
        self, db, organisation, contact, user, mock_sms_provider_transient_fail
    ):
        """Media blob is NOT deleted on transient failure (schedule will retry)."""
        schedule = _make_queued(
            db, organisation, user, contact,
            format=MessageFormat.MMS,
            media_url='https://myaccount.blob.core.windows.net/media/retry.png?sv=2022&sig=token',
        )

        with patch('app.celery.get_storage_provider') as mock_storage:
            with patch('app.celery.send_message.apply_async'):
                send_message(schedule.pk)

            mock_storage.assert_not_called()
