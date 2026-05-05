"""
End-to-end pipeline integration tests.

These tests cover the view → Celery task → database path that unit tests leave
uncovered:
- View tests mock send_message_task entirely (task never runs)
- Task tests call task functions directly (no view, no .delay())

Here we POST to the real endpoint and verify the final schedule status in the DB.
Celery is configured in 'always eager' mode so .delay() executes synchronously
in-process — no Redis or worker container required.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from django.conf import settings
from django.utils import timezone

from app.models import CreditTransaction, Organisation, Schedule, ScheduleStatus
from app.utils.billing import grant_credits
from app.utils.sms import SendResult
from tests.factories import create_contact_group_with_members


# ---------------------------------------------------------------------------
# Shared eager-mode fixture — active for every test in this module
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def celery_eager():
    """Execute Celery tasks synchronously (no broker/worker needed)."""
    from app.celery import app as celery_app
    celery_app.conf.update(task_always_eager=True, task_eager_propagates=True)
    yield
    celery_app.conf.update(task_always_eager=False, task_eager_propagates=False)


# ---------------------------------------------------------------------------
# Direct (individual) SMS send pipeline
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSendSMSPipeline:
    """Full pipeline tests for POST /api/sms/send/."""

    _PAYLOAD = {'recipients': [{'phone': '+61412345678'}], 'message': 'Hello pipeline'}

    def test_direct_send_processes_to_sent(
        self, authenticated_client, organisation, mock_sms_provider
    ):
        """POST /api/sms/send/ → task executes synchronously → schedule is SENT."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        response = authenticated_client.post('/api/sms/send/', self._PAYLOAD, format='json')

        assert response.status_code == 202
        schedule = Schedule.objects.get(pk=response.data['schedule_id'])
        assert schedule.status == ScheduleStatus.SENT

    def test_direct_send_trial_credits_consumed(
        self, authenticated_client, organisation, mock_sms_provider
    ):
        """Trial org: view reserves credits, task sends, final balance is reduced."""
        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'Test grant')

        response = authenticated_client.post('/api/sms/send/', self._PAYLOAD, format='json')

        assert response.status_code == 202
        # Credits reserved at view time (before task), balance already reduced
        organisation.refresh_from_db()
        assert organisation.credit_balance < Decimal('10.00')
        # Task ran synchronously — schedule should be SENT
        schedule = Schedule.objects.get(pk=response.data['schedule_id'])
        assert schedule.status == ScheduleStatus.SENT

    def test_direct_send_subscribed_records_usage_transaction(
        self, authenticated_client, organisation, mock_sms_provider
    ):
        """Subscribed org: CreditTransaction(type=usage) is created by the task on SENT."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        response = authenticated_client.post('/api/sms/send/', self._PAYLOAD, format='json')

        assert response.status_code == 202
        schedule = Schedule.objects.get(pk=response.data['schedule_id'])
        assert schedule.status == ScheduleStatus.SENT
        tx = CreditTransaction.objects.get(organisation=organisation, transaction_type='usage')
        assert tx.schedule == schedule

    def test_provider_transient_failure_then_retry_succeeds(
        self, authenticated_client, organisation
    ):
        """Transient provider failure on first attempt → retry runs → schedule is SENT."""
        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        with patch('app.celery.get_sms_provider') as mock_get:
            provider = Mock()
            provider.send_sms.side_effect = [
                # First call: transient failure
                SendResult(
                    success=False, error='Timeout', http_status=503,
                    retryable=True, failure_category='server_error',
                    message_parts=1,
                ),
                # Second call (retry): success
                SendResult(
                    success=True, message_id='mock-ok', message_parts=1,
                ),
            ]
            mock_get.return_value = provider

            response = authenticated_client.post('/api/sms/send/', self._PAYLOAD, format='json')

        assert response.status_code == 202
        schedule = Schedule.objects.get(pk=response.data['schedule_id'])
        assert schedule.status == ScheduleStatus.SENT
        assert schedule.retry_count == 1

    def test_provider_permanent_failure_refunds_trial_credits(
        self, authenticated_client, organisation, mock_sms_provider_permanent_fail
    ):
        """Permanent provider failure → schedule FAILED, trial credits are refunded."""
        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'Test grant')

        response = authenticated_client.post('/api/sms/send/', self._PAYLOAD, format='json')

        assert response.status_code == 202
        schedule = Schedule.objects.get(pk=response.data['schedule_id'])
        assert schedule.status == ScheduleStatus.FAILED
        # Credits reserved by view, then refunded by task on permanent failure
        organisation.refresh_from_db()
        assert organisation.credit_balance == Decimal('10.00')


# ---------------------------------------------------------------------------
# Group schedule pipeline (create → beat dispatch → send)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGroupSendPipeline:
    """Full pipeline tests for group scheduled sends via dispatch_due_messages()."""

    def test_group_schedule_dispatched_by_beat_to_sent(
        self, authenticated_client, organisation, user, mock_sms_provider
    ):
        """
        Create group schedule → call dispatch_due_messages() → children reach SENT.

        Covers the beat task → Celery task path in one integration test.
        """
        from app.celery import dispatch_due_messages

        organisation.billing_mode = Organisation.BILLING_SUBSCRIBED
        organisation.save()

        group, _ = create_contact_group_with_members(organisation, num_members=2, user=user)
        future_time = timezone.now() + timezone.timedelta(hours=1)

        response = authenticated_client.post('/api/group-schedules/', {
            'name': 'Pipeline test campaign',
            'group_id': group.id,
            'text': 'Hello from pipeline test',
            'scheduled_time': future_time.isoformat(),
        }, format='json')

        assert response.status_code == 201

        # Backdate parent and children so dispatch_due_messages() picks up the parent
        past = timezone.now() - timezone.timedelta(minutes=5)
        Schedule.objects.filter(pk=response.data['id']).update(scheduled_time=past)
        Schedule.objects.filter(parent_id=response.data['id']).update(scheduled_time=past)

        # Beat task picks up parent (batch) with scheduled_time <= now
        result = dispatch_due_messages()

        assert result['dispatched'] == 1  # parent only
        # With eager mode, batch task ran synchronously — children are SENT
        children = Schedule.objects.filter(
            parent_id=response.data['id'], status=ScheduleStatus.SENT
        )
        assert children.count() == 2

    def test_group_schedule_trial_credits_reserved_then_no_double_charge(
        self, authenticated_client, organisation, user, mock_sms_provider
    ):
        """
        Trial org: credits reserved at create time, no second deduction when task sends.

        view.create() calls record_usage() per child.
        send_message task skips record_usage() for trial orgs (already reserved).
        """
        from app.celery import dispatch_due_messages

        organisation.billing_mode = Organisation.BILLING_TRIAL
        organisation.save()
        grant_credits(organisation, Decimal('10.00'), 'Test grant')

        member_count = 2
        group, _ = create_contact_group_with_members(organisation, num_members=member_count, user=user)
        future_time = timezone.now() + timezone.timedelta(hours=1)

        response = authenticated_client.post('/api/group-schedules/', {
            'name': 'Trial pipeline test',
            'group_id': group.id,
            'text': 'Hi',
            'scheduled_time': future_time.isoformat(),
        }, format='json')

        assert response.status_code == 201

        # Backdate parent and children so dispatch_due_messages() picks up the parent
        past = timezone.now() - timezone.timedelta(minutes=5)
        Schedule.objects.filter(pk=response.data['id']).update(scheduled_time=past)
        Schedule.objects.filter(parent_id=response.data['id']).update(scheduled_time=past)

        organisation.refresh_from_db()
        expected_after_create = Decimal('10.00') - (member_count * 1 * settings.SMS_RATE)
        assert organisation.credit_balance == expected_after_create

        dispatch_due_messages()

        # Balance must not change again after dispatch — credits were already reserved
        organisation.refresh_from_db()
        assert organisation.credit_balance == expected_after_create
