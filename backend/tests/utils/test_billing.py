"""
Tests for billing utilities.

Tests:
- grant_credits: Adds dollar credits to org balance
- get_balance: Reads current balance from DB
- check_can_send: Pre-send gate (monthly limit + trial balance)
- record_usage: Records billable sends (trial deducts, subscribed tracks)
- get_monthly_usage: Sums usage for a format this month
- get_total_monthly_spend: Sums all usage charges this month
"""

import pytest
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from app.models import CreditTransaction, Organisation, Schedule, ScheduleStatus, MessageFormat
from app.utils.billing import (
    build_line_items,
    check_can_send,
    get_balance,
    get_current_month_preview,
    get_monthly_usage,
    get_total_monthly_spend,
    grant_credits,
    record_usage,
    refund_usage,
)
from tests.factories import ConfigFactory, OrganisationFactory, UserFactory


@pytest.mark.django_db
class TestGrantCredits:
    def test_adds_to_balance(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        new_balance = grant_credits(org, Decimal('10.00'), 'Free trial')
        assert new_balance == Decimal('10.00')

    def test_creates_transaction(self):
        from app.models import CreditTransaction
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        grant_credits(org, Decimal('5.00'), 'Test grant')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='grant')
        assert tx.amount == Decimal('5.00')
        assert tx.balance_after == Decimal('5.00')
        assert tx.description == 'Test grant'
        assert tx.format is None
        assert tx.created_by is None

    def test_accumulates(self):
        org = OrganisationFactory(credit_balance=Decimal('5.00'))
        new_balance = grant_credits(org, Decimal('3.00'), 'Top-up')
        assert new_balance == Decimal('8.00')


@pytest.mark.django_db
class TestGetBalance:
    def test_reads_from_db(self):
        org = OrganisationFactory(credit_balance=Decimal('7.50'))
        assert get_balance(org) == Decimal('7.50')


@pytest.mark.django_db
class TestCheckCanSend:
    def test_trial_allows_when_sufficient_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('1.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is True
        assert error is None

    def test_trial_blocks_when_insufficient_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is False
        assert 'Insufficient balance' in error

    def test_subscribed_allows_with_zero_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is True
        assert error is None

    def test_monthly_limit_blocks_both_modes(self):
        for mode in [Organisation.BILLING_TRIAL, Organisation.BILLING_SUBSCRIBED]:
            org = OrganisationFactory(
                credit_balance=Decimal('100.00'),
                billing_mode=mode,
            )
            ConfigFactory(organisation=org, name='monthly_limit', value='0.01')
            allowed, error = check_can_send(org, units=1, format='sms')
            assert allowed is False
            assert 'Monthly spending limit' in error

    def test_allows_when_under_monthly_limit(self):
        org = OrganisationFactory(
            credit_balance=Decimal('100.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        ConfigFactory(organisation=org, name='monthly_limit', value='100.00')
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is True

    def test_multi_unit_cost_check(self):
        """Cost = units * rate; balance just under the cost of 10 SMS should block."""
        cost_of_10 = 10 * settings.SMS_RATE
        org = OrganisationFactory(
            credit_balance=cost_of_10 - Decimal('0.01'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        allowed, error = check_can_send(org, units=10, format='sms')
        assert allowed is False
        assert 'Insufficient balance' in error

    def test_returns_false_when_billing_past_due(self):
        """check_can_send is blocked immediately when billing_mode is past_due."""
        org = OrganisationFactory(billing_mode=Organisation.BILLING_PAST_DUE)
        allowed, error = check_can_send(org, 1, 'sms')
        assert allowed is False
        assert 'past due' in error.lower()

    def test_monthly_limit_zero_blocks_all_sends(self):
        """monthly_limit=0.00 blocks every send regardless of balance or mode."""
        for mode in [Organisation.BILLING_TRIAL, Organisation.BILLING_SUBSCRIBED]:
            org = OrganisationFactory(
                credit_balance=Decimal('100.00'),
                billing_mode=mode,
            )
            ConfigFactory(organisation=org, name='monthly_limit', value='0.00')
            allowed, error = check_can_send(org, units=1, format='sms')
            assert allowed is False, f'Expected False for billing_mode={mode}'
            assert 'Monthly spending limit' in error


@pytest.mark.django_db
class TestRecordUsage:
    def test_trial_deducts_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('1.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='sms', description='Test SMS')
        assert get_balance(org) == Decimal('1.00') - settings.SMS_RATE

    def test_trial_creates_deduct_transaction(self):
        from app.models import CreditTransaction
        org = OrganisationFactory(
            credit_balance=Decimal('1.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='sms', description='Test SMS')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.amount == settings.SMS_RATE
        assert tx.format == 'sms'

    def test_subscribed_does_not_change_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        record_usage(org, 1, format='sms', description='Test SMS')
        assert get_balance(org) == Decimal('10.00')

    def test_subscribed_creates_usage_transaction(self):
        from app.models import CreditTransaction
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        record_usage(org, 1, format='mms', description='Test MMS')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='usage')
        assert tx.amount == settings.MMS_RATE
        assert tx.format == 'mms'

    def test_records_created_by_user(self):
        from app.models import CreditTransaction
        user = UserFactory()
        org = OrganisationFactory(
            credit_balance=Decimal('1.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='sms', description='Test', user=user)
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.created_by == user

    def test_mms_rate_applied(self):
        org = OrganisationFactory(
            credit_balance=Decimal('1.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='mms', description='Test MMS')
        assert get_balance(org) == Decimal('1.00') - settings.MMS_RATE


@pytest.mark.django_db
class TestGetMonthlyUsage:
    def test_sums_deduct_and_usage(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 2, format='sms', description='Send 1')
        record_usage(org, 1, format='sms', description='Send 2')
        total = get_monthly_usage(org, 'sms')
        assert total == 3 * settings.SMS_RATE

    def test_excludes_other_formats(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='sms', description='SMS')
        record_usage(org, 1, format='mms', description='MMS')
        assert get_monthly_usage(org, 'sms') == settings.SMS_RATE
        assert get_monthly_usage(org, 'mms') == settings.MMS_RATE

    def test_returns_zero_when_no_usage(self):
        org = OrganisationFactory()
        assert get_monthly_usage(org, 'sms') == Decimal('0.00')


@pytest.mark.django_db
class TestGetTotalMonthlySpend:
    def test_sums_all_formats(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        record_usage(org, 1, format='sms', description='SMS')
        record_usage(org, 1, format='mms', description='MMS')
        total = get_total_monthly_spend(org)
        assert total == settings.SMS_RATE + settings.MMS_RATE

    def test_excludes_grants(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        grant_credits(org, Decimal('10.00'), 'Grant')
        total = get_total_monthly_spend(org)
        assert total == Decimal('0.00')

    def test_returns_zero_when_no_usage(self):
        org = OrganisationFactory()
        assert get_total_monthly_spend(org) == Decimal('0.00')



@pytest.mark.django_db
class TestRefundUsage:
    """Tests for refund_usage() — credit refund on failed sends."""

    def _make_schedule(self, org, user):
        from django.utils import timezone
        return Schedule.objects.create(
            organisation=org,
            phone='0412345678',
            text='Test',
            scheduled_time=timezone.now(),
            status=ScheduleStatus.FAILED,
            format=MessageFormat.SMS,
            message_parts=1,
            failure_category='invalid_number',
            created_by=user,
            updated_by=user,
        )

    def test_trial_refund_restores_balance(self):
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)
        balance_after_deduct = get_balance(org)

        refund_usage(org, schedule)

        assert get_balance(org) == balance_after_deduct + settings.SMS_RATE

    def test_trial_refund_creates_refund_transaction(self):
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)

        refund_usage(org, schedule)

        assert CreditTransaction.objects.filter(
            organisation=org,
            schedule=schedule,
            transaction_type=CreditTransaction.REFUND,
        ).exists()

    def test_subscribed_refund_does_not_change_balance(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)
        balance = get_balance(org)

        refund_usage(org, schedule)

        assert get_balance(org) == balance  # balance unchanged

    def test_subscribed_refund_creates_refund_transaction(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)

        refund_usage(org, schedule)

        assert CreditTransaction.objects.filter(
            organisation=org,
            schedule=schedule,
            transaction_type=CreditTransaction.REFUND,
        ).exists()

    def test_refund_is_idempotent(self):
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)

        refund_usage(org, schedule)
        refund_usage(org, schedule)  # second call is no-op

        assert CreditTransaction.objects.filter(
            organisation=org,
            schedule=schedule,
            transaction_type=CreditTransaction.REFUND,
        ).count() == 1

    def test_refund_with_no_original_charge_is_noop(self):
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        # No record_usage call
        balance_before = get_balance(org)

        refund_usage(org, schedule)  # Should not raise

        assert get_balance(org) == balance_before

    def test_refund_multi_part_sms(self):
        """A 2-part SMS is fully refunded — amount scales with message_parts."""
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = Schedule.objects.create(
            organisation=org,
            phone='0412345678',
            text='x' * 161,  # 161 chars → 2 parts
            scheduled_time=timezone.now(),
            status=ScheduleStatus.FAILED,
            format=MessageFormat.SMS,
            message_parts=2,
            failure_category='invalid_number',
            created_by=user,
            updated_by=user,
        )
        record_usage(org, 2, 'sms', 'dispatch', user, schedule)
        balance_after_deduct = get_balance(org)

        refund_usage(org, schedule)

        expected_refund = 2 * settings.SMS_RATE
        assert get_balance(org) == balance_after_deduct + expected_refund
        refund_tx = CreditTransaction.objects.get(
            organisation=org, schedule=schedule, transaction_type=CreditTransaction.REFUND
        )
        assert refund_tx.amount == expected_refund

    def test_refund_amount_matches_original_charge(self):
        org = OrganisationFactory(billing_mode='trial', credit_balance=Decimal('10.00'))
        user = UserFactory()
        schedule = self._make_schedule(org, user)
        record_usage(org, 1, 'sms', 'test send', user, schedule)
        balance_before_refund = get_balance(org)

        refund_usage(org, schedule)

        refund_tx = CreditTransaction.objects.get(
            organisation=org,
            schedule=schedule,
            transaction_type=CreditTransaction.REFUND,
        )
        assert refund_tx.amount == settings.SMS_RATE
        assert get_balance(org) == balance_before_refund + settings.SMS_RATE


@pytest.mark.django_db
class TestBuildLineItems:
    """Tests for build_line_items — aggregates CreditTransaction records into invoice line items."""

    def test_empty_when_no_transactions(self):
        org = OrganisationFactory(billing_mode='subscribed')
        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now()

        result = build_line_items(org, start, end)

        assert result == []

    def test_aggregates_usage_by_format(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        # Record 3 SMS usage transactions
        for i in range(3):
            record_usage(org, 1, 'sms', f'SMS {i}', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 1
        assert result[0].quantity == 3
        assert result[0].amount == 3 * settings.SMS_RATE

    def test_nets_refunds_against_usage(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        schedule = Schedule.objects.create(
            organisation=org,
            phone='0412345678',
            text='Test',
            scheduled_time=timezone.now(),
            status=ScheduleStatus.FAILED,
            format=MessageFormat.SMS,
            message_parts=1,
            failure_category='invalid_number',
            created_by=user,
            updated_by=user,
        )
        record_usage(org, 1, 'sms', 'sent', user, schedule)
        record_usage(org, 1, 'sms', 'sent2', user)
        refund_usage(org, schedule)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 1
        assert result[0].quantity == 1  # 2 usage - 1 refund = 1 net
        assert result[0].amount == settings.SMS_RATE

    def test_zero_net_usage_returns_empty(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        schedule = Schedule.objects.create(
            organisation=org,
            phone='0412345678',
            text='Test',
            scheduled_time=timezone.now(),
            status=ScheduleStatus.FAILED,
            format=MessageFormat.SMS,
            message_parts=1,
            failure_category='invalid_number',
            created_by=user,
            updated_by=user,
        )
        record_usage(org, 1, 'sms', 'sent', user, schedule)
        refund_usage(org, schedule)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert result == []

    def test_multiple_formats(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'sms', 'SMS send', user)
        record_usage(org, 1, 'mms', 'MMS send', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 2
        formats = {item.description.split(' ')[0] for item in result}
        assert formats == {'SMS', 'MMS'}


@pytest.mark.django_db
class TestGetCurrentMonthPreview:
    """Tests for get_current_month_preview — current month invoice estimate."""

    def test_empty_preview_with_no_usage(self):
        org = OrganisationFactory(billing_mode='subscribed')

        result = get_current_month_preview(org)

        assert result['total'] == '0'
        assert result['line_items'] == []
        assert 'period_start' in result
        assert 'period_end' in result

    def test_preview_with_usage(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 2, 'sms', 'Two SMS', user)

        result = get_current_month_preview(org)

        expected_total = 2 * settings.SMS_RATE
        assert result['total'] == str(expected_total)
        assert len(result['line_items']) == 1
        assert result['line_items'][0]['format'] == 'sms'
        assert result['line_items'][0]['quantity'] == 2
        assert result['line_items'][0]['rate'] == str(settings.SMS_RATE.normalize())
        assert result['line_items'][0]['amount'] == str(expected_total)


class TestGetRate:
    def test_raises_for_unknown_format(self):
        from app.utils.billing import get_rate
        with pytest.raises(ValueError, match='No billing rate configured'):
            get_rate('fax')

    def test_returns_global_default_without_org(self):
        from app.utils.billing import get_rate
        assert get_rate('sms') == settings.SMS_RATE
        assert get_rate('mms') == settings.MMS_RATE

    @pytest.mark.django_db
    def test_returns_global_default_when_no_config_override(self):
        from app.utils.billing import get_rate
        org = OrganisationFactory()
        assert get_rate('sms', org) == settings.SMS_RATE

    @pytest.mark.django_db
    def test_returns_per_org_override(self):
        from app.utils.billing import get_rate
        org = OrganisationFactory()
        ConfigFactory(organisation=org, name='sms_rate', value='0.03')
        assert get_rate('sms', org) == Decimal('0.03')

    @pytest.mark.django_db
    def test_per_org_override_does_not_affect_other_orgs(self):
        from app.utils.billing import get_rate
        org_a = OrganisationFactory()
        org_b = OrganisationFactory()
        ConfigFactory(organisation=org_a, name='sms_rate', value='0.03')
        assert get_rate('sms', org_a) == Decimal('0.03')
        assert get_rate('sms', org_b) == settings.SMS_RATE  # global default

    @pytest.mark.django_db
    def test_per_org_mms_override(self):
        from app.utils.billing import get_rate
        org = OrganisationFactory()
        ConfigFactory(organisation=org, name='mms_rate', value='0.10')
        assert get_rate('mms', org) == Decimal('0.10')


@pytest.mark.django_db
class TestUnitRateOnTransaction:
    """Tests that unit_rate is stored on CreditTransaction records."""

    def test_trial_deduct_stores_unit_rate(self):
        org = OrganisationFactory(credit_balance=Decimal('1.00'), billing_mode='trial')
        record_usage(org, 1, 'sms', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.unit_rate == settings.SMS_RATE

    def test_subscribed_usage_stores_unit_rate(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'), billing_mode='subscribed')
        record_usage(org, 1, 'mms', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='usage')
        assert tx.unit_rate == settings.MMS_RATE

    def test_stores_per_org_override_rate(self):
        org = OrganisationFactory(credit_balance=Decimal('1.00'), billing_mode='trial')
        ConfigFactory(organisation=org, name='sms_rate', value='0.03')
        record_usage(org, 1, 'sms', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.unit_rate == Decimal('0.03')
        assert tx.amount == Decimal('0.03')


@pytest.mark.django_db
class TestCheckCanSendWithOrgRate:
    """Tests that check_can_send uses per-org rate overrides."""

    def test_custom_rate_affects_cost_check(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.04'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        # Default rate would block, custom rate $0.03 should allow
        ConfigFactory(organisation=org, name='sms_rate', value='0.03')
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is True

    def test_custom_rate_blocks_when_insufficient(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.02'),
            billing_mode=Organisation.BILLING_TRIAL,
        )
        ConfigFactory(organisation=org, name='sms_rate', value='0.03')
        allowed, error = check_can_send(org, units=1, format='sms')
        assert allowed is False


@pytest.mark.django_db
class TestBuildLineItemsWithMixedRates:
    """Tests that build_line_items groups by (format, unit_rate) correctly."""

    def test_mixed_rates_produce_separate_line_items(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()

        # Record 2 SMS at default rate
        record_usage(org, 1, 'sms', 'SMS 1', user)
        record_usage(org, 1, 'sms', 'SMS 2', user)

        # Change org rate to $0.03 and record 3 more
        ConfigFactory(organisation=org, name='sms_rate', value='0.03')
        record_usage(org, 1, 'sms', 'SMS 3', user)
        record_usage(org, 1, 'sms', 'SMS 4', user)
        record_usage(org, 1, 'sms', 'SMS 5', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 2
        by_rate = {item.unit_amount: item for item in result}
        default_rate = settings.SMS_RATE.normalize()
        assert by_rate[default_rate].quantity == 2
        assert by_rate[default_rate].amount == 2 * settings.SMS_RATE
        assert by_rate[Decimal('0.03')].quantity == 3
        assert by_rate[Decimal('0.03')].amount == Decimal('0.09')
