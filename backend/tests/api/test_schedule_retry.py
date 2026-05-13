"""
Tests for POST /api/schedules/{id}/retry/ endpoint.

Tests:
- Retry resets failed schedule to QUEUED and dispatches Celery task
- Retry rejects non-failed schedules
- Retry checks billing before allowing retry
- Retry handles batch parents (only re-queues failed children)
- Prepaid orgs get re-charged on retry
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework import status

from app.models import (
    CreditTransaction,
    MessageFormat,
    Schedule,
    ScheduleStatus,
)
from app.utils.billing import grant_credits
from tests.factories import ContactFactory, ScheduleFactory


@pytest.mark.django_db
class TestScheduleRetry:
    """Tests for POST /api/schedules/{id}/retry/."""

    def test_retry_resets_failed_to_queued(
        self, authenticated_client, organisation, user, mock_send_message_task,
        mock_check_sms_limit,
    ):
        """Retrying a failed schedule resets it to QUEUED."""
        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Invalid phone number',
            failure_category='invalid_number',
            retry_count=3,
        )

        response = authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        assert response.status_code == status.HTTP_200_OK
        schedule.refresh_from_db()
        assert schedule.status == ScheduleStatus.QUEUED
        assert schedule.retry_count == 0
        assert schedule.error is None
        assert schedule.failure_category is None
        assert schedule.next_retry_at is None

    def test_retry_dispatches_send_message_task(
        self, authenticated_client, organisation, user, mock_send_message_task,
        mock_check_sms_limit,
    ):
        """Retrying dispatches the send_message Celery task."""
        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Server error',
        )

        authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        mock_send_message_task.delay.assert_called_once_with(schedule.pk)

    @pytest.mark.parametrize('invalid_status', [
        ScheduleStatus.PENDING,
        ScheduleStatus.QUEUED,
        ScheduleStatus.PROCESSING,
        ScheduleStatus.SENT,
        ScheduleStatus.RETRYING,
        ScheduleStatus.DELIVERED,
        ScheduleStatus.CANCELLED,
    ])
    def test_retry_rejects_non_failed_status(
        self, authenticated_client, organisation, user, invalid_status
    ):
        """Retry returns 400 for any non-failed status."""
        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=invalid_status,
        )

        response = authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_retry_checks_billing(
        self, authenticated_client, organisation, user
    ):
        """Retry returns 402 if billing check fails."""
        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Server error',
        )

        with patch('app.views.check_can_send', return_value=(False, 'Insufficient credits')):
            response = authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        assert response.status_code == status.HTTP_402_PAYMENT_REQUIRED
        assert 'Insufficient credits' in response.data['detail']

    def test_retry_batch_parent_resets_failed_children(
        self, authenticated_client, organisation, user,
        mock_send_batch_message_task, mock_check_sms_limit,
    ):
        """Retrying a batch parent resets only failed children to QUEUED."""
        parent = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Batch failed',
        )

        # One delivered child (should NOT be reset)
        child_delivered = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.DELIVERED,
        )

        # Two failed children (should be reset)
        child_failed_1 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Invalid number',
        )
        child_failed_2 = ScheduleFactory(
            organisation=organisation,
            parent=parent,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Server error',
        )

        response = authenticated_client.post(f'/api/schedules/{parent.id}/retry/')

        assert response.status_code == status.HTTP_200_OK

        parent.refresh_from_db()
        child_delivered.refresh_from_db()
        child_failed_1.refresh_from_db()
        child_failed_2.refresh_from_db()

        assert parent.status == ScheduleStatus.QUEUED
        assert child_delivered.status == ScheduleStatus.DELIVERED  # Untouched
        assert child_failed_1.status == ScheduleStatus.QUEUED
        assert child_failed_2.status == ScheduleStatus.QUEUED

        mock_send_batch_message_task.delay.assert_called_once_with(parent.pk)

    def test_retry_trial_org_records_usage(
        self, authenticated_client, organisation, user, mock_send_message_task
    ):
        """Retrying on a trial org re-charges credits (since refund ran on failure)."""
        organisation.billing_mode = organisation.BILLING_PREPAID
        grant_credits(organisation, Decimal('10.00'), description='Test credits')
        organisation.save()

        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Server error',
            message_parts=1,
            format=MessageFormat.SMS,
        )

        initial_txn_count = CreditTransaction.objects.filter(
            organisation=organisation, transaction_type='deduct'
        ).count()

        response = authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        assert response.status_code == status.HTTP_200_OK
        new_txn_count = CreditTransaction.objects.filter(
            organisation=organisation, transaction_type='deduct'
        ).count()
        assert new_txn_count == initial_txn_count + 1

    def test_retry_returns_serialized_schedule(
        self, authenticated_client, organisation, user, mock_send_message_task,
        mock_check_sms_limit,
    ):
        """Retry response includes the updated schedule data."""
        schedule = ScheduleFactory(
            organisation=organisation,
            for_contact=True,
            created_by=user,
            status=ScheduleStatus.FAILED,
            error='Server error',
        )

        response = authenticated_client.post(f'/api/schedules/{schedule.id}/retry/')

        assert response.status_code == status.HTTP_200_OK
        assert response.data['id'] == schedule.id
        assert response.data['status'] == ScheduleStatus.QUEUED
