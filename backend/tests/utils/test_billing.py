"""
Tests for billing utilities.

Tests:
- grant_credits: Adds dollar credits to org balance
- get_balance: Reads current balance from DB
- get_rate: Rate resolution (per-org Config -> USAGE_RATES[type] -> default)
- check_can_spend: Pre-spend gate (past due + monthly limit + prepaid balance)
- record_usage: Records billable actions (prepaid deducts, subscribed tracks)
- refund_usage: Reverses charges by reference, at most once per charge
- get_monthly_usage / get_total_monthly_spend: Monthly aggregation
- build_line_items / get_current_month_preview: Invoice aggregation
"""

import pytest
from decimal import Decimal

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from app.models import CreditTransaction, Organisation
from app.utils.billing import (
    build_line_items,
    check_can_spend,
    get_balance,
    get_current_month_preview,
    get_monthly_usage,
    get_rate,
    get_total_monthly_spend,
    grant_credits,
    record_usage,
    refund_usage,
)
from tests.factories import ConfigFactory, OrganisationFactory, UserFactory

# Derive expected amounts from settings so environment-level rate overrides
# (e.g. in CI) don't break assertions. 'api_call' and 'report' have no explicit
# entry in USAGE_RATES, so both resolve to the 'default' rate.
RATE = settings.USAGE_RATES['default']


@pytest.mark.django_db
class TestGrantCredits:
    def test_adds_to_balance(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        tx = grant_credits(org, Decimal('10.00'), 'Free credits')
        assert tx.balance_after == Decimal('10.00')
        assert get_balance(org) == Decimal('10.00')

    def test_creates_transaction(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        grant_credits(org, Decimal('5.00'), 'Test grant')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='grant')
        assert tx.amount == Decimal('5.00')
        assert tx.balance_after == Decimal('5.00')
        assert tx.description == 'Test grant'
        assert tx.usage_type is None
        assert tx.reference is None
        assert tx.created_by is None

    def test_accumulates(self):
        org = OrganisationFactory(credit_balance=Decimal('5.00'))
        tx = grant_credits(org, Decimal('3.00'), 'Top-up')
        assert tx.balance_after == Decimal('8.00')


@pytest.mark.django_db
class TestGetBalance:
    def test_reads_from_db(self):
        org = OrganisationFactory(credit_balance=Decimal('7.50'))
        assert get_balance(org) == Decimal('7.50')


@pytest.mark.django_db
class TestCheckCanSpend:
    def test_prepaid_allows_when_sufficient_balance(self):
        org = OrganisationFactory(
            credit_balance=RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is True
        assert error is None

    def test_prepaid_blocks_when_insufficient_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is False
        assert 'Insufficient balance' in error

    def test_subscribed_allows_with_zero_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is True
        assert error is None

    def test_monthly_limit_blocks_both_modes(self):
        for mode in [Organisation.BILLING_PREPAID, Organisation.BILLING_SUBSCRIBED]:
            org = OrganisationFactory(
                credit_balance=Decimal('100.00'),
                billing_mode=mode,
            )
            ConfigFactory(organisation=org, name='monthly_limit', value='0.01')
            allowed, error = check_can_spend(org, units=1, usage_type='api_call')
            assert allowed is False
            assert 'Monthly spending limit' in error

    def test_allows_when_under_monthly_limit(self):
        org = OrganisationFactory(
            credit_balance=Decimal('100.00'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        ConfigFactory(organisation=org, name='monthly_limit', value='100.00')
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is True

    def test_multi_unit_cost_check(self):
        """Cost = units * rate; balance just under the cost of 10 units should block."""
        cost_of_10 = 10 * RATE
        org = OrganisationFactory(
            credit_balance=cost_of_10 - Decimal('0.01'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        allowed, error = check_can_spend(org, units=10, usage_type='api_call')
        assert allowed is False
        assert 'Insufficient balance' in error

    def test_returns_false_when_billing_past_due(self):
        """check_can_spend is blocked immediately when billing_mode is past_due."""
        org = OrganisationFactory(billing_mode=Organisation.BILLING_PAST_DUE)
        allowed, error = check_can_spend(org, 1, 'api_call')
        assert allowed is False
        assert 'past due' in error.lower()

    def test_monthly_limit_zero_blocks_all_spending(self):
        """monthly_limit=0.00 blocks every action regardless of balance or mode."""
        for mode in [Organisation.BILLING_PREPAID, Organisation.BILLING_SUBSCRIBED]:
            org = OrganisationFactory(
                credit_balance=Decimal('100.00'),
                billing_mode=mode,
            )
            ConfigFactory(organisation=org, name='monthly_limit', value='0.00')
            allowed, error = check_can_spend(org, units=1, usage_type='api_call')
            assert allowed is False, f'Expected False for billing_mode={mode}'
            assert 'Monthly spending limit' in error


@pytest.mark.django_db
class TestRecordUsage:
    def test_prepaid_deduction_below_zero_raises_and_rolls_back(self):
        """The locked balance floor is what prevents negative balances.

        check_can_spend() is an unlocked pre-check, so concurrent spends can all
        pass it — record_usage must refuse the deduction itself.
        """
        from app.utils.billing import InsufficientBalanceError

        org = OrganisationFactory(
            credit_balance=RATE - Decimal('0.01'),
            billing_mode=Organisation.BILLING_PREPAID,
        )

        with pytest.raises(InsufficientBalanceError):
            record_usage(org, 1, usage_type='api_call', description='Test')  # costs RATE

        assert get_balance(org) == RATE - Decimal('0.01')  # unchanged
        assert not CreditTransaction.objects.filter(organisation=org).exists()

    def test_prepaid_deducts_balance(self):
        org = OrganisationFactory(
            credit_balance=10 * RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 1, usage_type='api_call', description='Test')
        assert get_balance(org) == 9 * RATE

    def test_prepaid_creates_deduct_transaction(self):
        org = OrganisationFactory(
            credit_balance=10 * RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 1, usage_type='api_call', description='Test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.amount == RATE
        assert tx.usage_type == 'api_call'

    def test_returns_the_created_transaction(self):
        org = OrganisationFactory(
            credit_balance=10 * RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        tx = record_usage(org, 1, usage_type='api_call', description='Test')
        assert isinstance(tx, CreditTransaction)
        assert tx.pk is not None
        assert tx.transaction_type == CreditTransaction.DEDUCT

    def test_stores_reference(self):
        org = OrganisationFactory(
            credit_balance=10 * RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        tx = record_usage(
            org, 1, usage_type='api_call', description='Test', reference='order:1234',
        )
        assert tx.reference == 'order:1234'

    def test_subscribed_does_not_change_balance(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        record_usage(org, 1, usage_type='api_call', description='Test')
        assert get_balance(org) == Decimal('10.00')

    def test_subscribed_creates_usage_transaction(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.00'),
            billing_mode=Organisation.BILLING_SUBSCRIBED,
        )
        record_usage(org, 1, usage_type='report', description='Test report')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='usage')
        assert tx.amount == RATE
        assert tx.usage_type == 'report'

    def test_records_created_by_user(self):
        user = UserFactory()
        org = OrganisationFactory(
            credit_balance=10 * RATE,
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 1, usage_type='api_call', description='Test', user=user)
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.created_by == user

    def test_explicit_usage_rate_applied(self):
        """A usage type with its own entry in USAGE_RATES is charged at that rate."""
        premium_rate = Decimal('0.75')
        with override_settings(USAGE_RATES={**settings.USAGE_RATES, 'premium': premium_rate}):
            org = OrganisationFactory(
                credit_balance=Decimal('1.00'),
                billing_mode=Organisation.BILLING_PREPAID,
            )
            record_usage(org, 1, usage_type='premium', description='Premium action')
            assert get_balance(org) == Decimal('1.00') - premium_rate


@pytest.mark.django_db
class TestGetMonthlyUsage:
    def test_sums_deduct_and_usage(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 2, usage_type='api_call', description='Action 1')
        record_usage(org, 1, usage_type='api_call', description='Action 2')
        total = get_monthly_usage(org, 'api_call')
        assert total == 3 * RATE

    def test_excludes_other_usage_types(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 1, usage_type='api_call', description='API call')
        record_usage(org, 1, usage_type='report', description='Report')
        assert get_monthly_usage(org, 'api_call') == RATE
        assert get_monthly_usage(org, 'report') == RATE

    def test_returns_zero_when_no_usage(self):
        org = OrganisationFactory()
        assert get_monthly_usage(org, 'api_call') == Decimal('0.00')


@pytest.mark.django_db
class TestGetTotalMonthlySpend:
    def test_sums_all_usage_types(self):
        org = OrganisationFactory(
            credit_balance=Decimal('10.00'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        record_usage(org, 1, usage_type='api_call', description='API call')
        record_usage(org, 1, usage_type='report', description='Report')
        total = get_total_monthly_spend(org)
        assert total == 2 * RATE

    def test_excludes_grants(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'))
        grant_credits(org, Decimal('10.00'), 'Grant')
        total = get_total_monthly_spend(org)
        assert total == Decimal('0.00')

    def test_returns_zero_when_no_usage(self):
        org = OrganisationFactory()
        assert get_total_monthly_spend(org) == Decimal('0.00')

    def test_refunds_reduce_monthly_spend(self):
        """Refunded charges free their share of the monthly cap.

        Regression test: monthly spend previously summed only charges, so a
        failed-and-refunded action consumed the limit forever.
        """
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'action one', user, reference='order:1')
        record_usage(org, 1, 'api_call', 'action two', user)

        assert get_total_monthly_spend(org) == 2 * RATE
        refund_usage(org, 'order:1')

        assert get_total_monthly_spend(org) == RATE
        assert get_monthly_usage(org, 'api_call') == RATE


@pytest.mark.django_db
class TestRefundUsage:
    """Tests for refund_usage() — reference-keyed credit refunds."""

    REF = 'order:1234'

    def test_prepaid_refund_restores_balance(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)
        balance_after_deduct = get_balance(org)

        refund_usage(org, self.REF)

        assert get_balance(org) == balance_after_deduct + RATE

    def test_prepaid_refund_creates_refund_transaction(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)

        refund_usage(org, self.REF)

        assert CreditTransaction.objects.filter(
            organisation=org,
            reference=self.REF,
            transaction_type=CreditTransaction.REFUND,
        ).exists()

    def test_refund_description_defaults_to_original(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)

        refund_usage(org, self.REF)

        refund_tx = CreditTransaction.objects.get(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.REFUND,
        )
        assert refund_tx.description == 'Refund: test action'

    def test_subscribed_refund_does_not_change_balance(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)
        balance = get_balance(org)

        refund_usage(org, self.REF)

        assert get_balance(org) == balance  # balance unchanged

    def test_subscribed_refund_creates_refund_transaction(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)

        refund_usage(org, self.REF)

        assert CreditTransaction.objects.filter(
            organisation=org,
            reference=self.REF,
            transaction_type=CreditTransaction.REFUND,
        ).exists()

    def test_refund_is_idempotent(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)

        refund_usage(org, self.REF)
        refund_usage(org, self.REF)  # second call is no-op

        assert CreditTransaction.objects.filter(
            organisation=org,
            reference=self.REF,
            transaction_type=CreditTransaction.REFUND,
        ).count() == 1

    def test_refund_links_the_charge_it_reverses(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)
        charge = CreditTransaction.objects.get(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.DEDUCT
        )

        refund_usage(org, self.REF)

        refund_tx = CreditTransaction.objects.get(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.REFUND
        )
        assert refund_tx.refunded_transaction_id == charge.pk

    def test_refund_after_retry_recharge_refunds_again(self):
        """A reference re-charged on retry is refunded again on a second failure.

        Regression test: an object-level idempotency check would make any second
        refund a no-op, silently keeping the retry charge.
        """
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()

        record_usage(org, 1, 'api_call', 'initial attempt', user, reference=self.REF)
        refund_usage(org, self.REF)
        record_usage(org, 1, 'api_call', 'retry attempt', user, reference=self.REF)
        refund_usage(org, self.REF)

        assert get_balance(org) == Decimal('10.00')  # fully restored
        assert CreditTransaction.objects.filter(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.REFUND,
        ).count() == 2
        # Each refund links a distinct charge
        linked = CreditTransaction.objects.filter(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.REFUND,
        ).values_list('refunded_transaction_id', flat=True)
        assert len(set(linked)) == 2

    def test_refund_with_no_original_charge_is_noop(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        # No record_usage call
        balance_before = get_balance(org)

        refund_usage(org, self.REF)  # Should not raise

        assert get_balance(org) == balance_before

    def test_refund_rejects_falsy_reference(self):
        """None/'' must raise — they would match charges recorded without a
        reference and silently reverse an arbitrary unrelated one."""
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        record_usage(org, 1, 'api_call', 'charge without reference')
        balance_before = get_balance(org)

        with pytest.raises(ValueError):
            refund_usage(org, None)
        with pytest.raises(ValueError):
            refund_usage(org, '')

        assert get_balance(org) == balance_before

    def test_refund_multi_unit_charge(self):
        """A multi-unit charge is fully refunded — amount scales with units."""
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 2, 'api_call', 'bulk action', user, reference=self.REF)
        balance_after_deduct = get_balance(org)

        refund_usage(org, self.REF)

        expected_refund = 2 * RATE
        assert get_balance(org) == balance_after_deduct + expected_refund
        refund_tx = CreditTransaction.objects.get(
            organisation=org, reference=self.REF, transaction_type=CreditTransaction.REFUND
        )
        assert refund_tx.amount == expected_refund

    def test_refund_amount_matches_original_charge(self):
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'test action', user, reference=self.REF)
        balance_before_refund = get_balance(org)

        refund_usage(org, self.REF)

        refund_tx = CreditTransaction.objects.get(
            organisation=org,
            reference=self.REF,
            transaction_type=CreditTransaction.REFUND,
        )
        assert refund_tx.amount == RATE
        assert get_balance(org) == balance_before_refund + RATE

    def test_refund_only_reverses_matching_reference(self):
        """Charges under other references are untouched."""
        org = OrganisationFactory(billing_mode='prepaid', credit_balance=Decimal('10.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'target', user, reference='order:1')
        record_usage(org, 1, 'api_call', 'other', user, reference='order:2')

        refund_usage(org, 'order:1')

        refunds = CreditTransaction.objects.filter(
            organisation=org, transaction_type=CreditTransaction.REFUND,
        )
        assert refunds.count() == 1
        assert refunds.first().reference == 'order:1'


@pytest.mark.django_db
class TestBuildLineItems:
    """Tests for build_line_items — aggregates CreditTransaction records into invoice line items."""

    def test_empty_when_no_transactions(self):
        org = OrganisationFactory(billing_mode='subscribed')
        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now()

        result = build_line_items(org, start, end)

        assert result == []

    def test_aggregates_usage_by_type(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        # Record 3 usage transactions of the same type
        for i in range(3):
            record_usage(org, 1, 'api_call', f'API call {i}', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 1
        assert result[0].quantity == 3
        assert result[0].amount == 3 * RATE
        assert result[0].usage_type == 'api_call'

    def test_nets_refunds_against_usage(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'charged', user, reference='order:1')
        record_usage(org, 1, 'api_call', 'charged2', user)
        refund_usage(org, 'order:1')

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 1
        assert result[0].quantity == 1  # 2 usage - 1 refund = 1 net
        assert result[0].amount == RATE

    def test_zero_net_usage_returns_empty(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'charged', user, reference='order:1')
        refund_usage(org, 'order:1')

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert result == []

    def test_multiple_usage_types(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()
        record_usage(org, 1, 'api_call', 'API call', user)
        record_usage(org, 1, 'report', 'Report', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 2
        types = {item.usage_type for item in result}
        assert types == {'api_call', 'report'}


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
        record_usage(org, 2, 'api_call', 'Two API calls', user)

        result = get_current_month_preview(org)

        expected_total = 2 * RATE
        assert result['total'] == str(expected_total)
        assert len(result['line_items']) == 1
        assert result['line_items'][0]['usage_type'] == 'api_call'
        assert result['line_items'][0]['quantity'] == 2
        assert result['line_items'][0]['rate'] == str(RATE.normalize())
        assert result['line_items'][0]['amount'] == str(expected_total)


class TestGetRate:
    def test_raises_when_no_rate_resolves(self):
        """Without a 'default' entry, unknown usage types have no rate."""
        with override_settings(USAGE_RATES={'api_call': Decimal('0.10')}):
            with pytest.raises(ValueError, match='No billing rate configured'):
                get_rate('fax')

    def test_returns_explicit_entry(self):
        with override_settings(USAGE_RATES={'api_call': Decimal('0.20'), 'default': Decimal('0.10')}):
            assert get_rate('api_call') == Decimal('0.20')

    def test_falls_back_to_default_entry(self):
        assert get_rate('api_call') == RATE
        assert get_rate('anything_else') == RATE

    @pytest.mark.django_db
    def test_returns_global_default_when_no_config_override(self):
        org = OrganisationFactory()
        assert get_rate('api_call', org) == RATE

    @pytest.mark.django_db
    def test_returns_per_org_override(self):
        org = OrganisationFactory()
        ConfigFactory(organisation=org, name='api_call_rate', value='0.03')
        assert get_rate('api_call', org) == Decimal('0.03')

    @pytest.mark.django_db
    def test_per_org_override_does_not_affect_other_orgs(self):
        org_a = OrganisationFactory()
        org_b = OrganisationFactory()
        ConfigFactory(organisation=org_a, name='api_call_rate', value='0.03')
        assert get_rate('api_call', org_a) == Decimal('0.03')
        assert get_rate('api_call', org_b) == RATE  # global default

    @pytest.mark.django_db
    def test_per_org_override_scoped_to_usage_type(self):
        org = OrganisationFactory()
        ConfigFactory(organisation=org, name='report_rate', value='0.10')
        assert get_rate('report', org) == Decimal('0.10')
        assert get_rate('api_call', org) == RATE


@pytest.mark.django_db
class TestUnitRateOnTransaction:
    """Tests that unit_rate is stored on CreditTransaction records."""

    def test_prepaid_deduct_stores_unit_rate(self):
        org = OrganisationFactory(credit_balance=10 * RATE, billing_mode='prepaid')
        record_usage(org, 1, 'api_call', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.unit_rate == RATE

    def test_subscribed_usage_stores_unit_rate(self):
        org = OrganisationFactory(credit_balance=Decimal('0.00'), billing_mode='subscribed')
        record_usage(org, 1, 'report', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='usage')
        assert tx.unit_rate == RATE

    def test_stores_per_org_override_rate(self):
        org = OrganisationFactory(credit_balance=Decimal('1.00'), billing_mode='prepaid')
        ConfigFactory(organisation=org, name='api_call_rate', value='0.03')
        record_usage(org, 1, 'api_call', 'test')
        tx = CreditTransaction.objects.get(organisation=org, transaction_type='deduct')
        assert tx.unit_rate == Decimal('0.03')
        assert tx.amount == Decimal('0.03')


@pytest.mark.django_db
class TestCheckCanSpendWithOrgRate:
    """Tests that check_can_spend uses per-org rate overrides."""

    def test_custom_rate_affects_cost_check(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.04'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        ConfigFactory(organisation=org, name='api_call_rate', value='0.03')
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is True

    def test_custom_rate_blocks_when_insufficient(self):
        org = OrganisationFactory(
            credit_balance=Decimal('0.02'),
            billing_mode=Organisation.BILLING_PREPAID,
        )
        ConfigFactory(organisation=org, name='api_call_rate', value='0.03')
        allowed, error = check_can_spend(org, units=1, usage_type='api_call')
        assert allowed is False


@pytest.mark.django_db
class TestBuildLineItemsWithMixedRates:
    """Tests that build_line_items groups by (usage_type, unit_rate) correctly."""

    def test_mixed_rates_produce_separate_line_items(self):
        org = OrganisationFactory(billing_mode='subscribed', credit_balance=Decimal('0.00'))
        user = UserFactory()

        # An override rate guaranteed to differ from the default
        override_rate = (RATE + Decimal('0.02')).quantize(Decimal('0.01'))

        # Record 2 charges at the default rate
        record_usage(org, 1, 'api_call', 'call 1', user)
        record_usage(org, 1, 'api_call', 'call 2', user)

        # Change the org rate and record 3 more
        ConfigFactory(organisation=org, name='api_call_rate', value=str(override_rate))
        record_usage(org, 1, 'api_call', 'call 3', user)
        record_usage(org, 1, 'api_call', 'call 4', user)
        record_usage(org, 1, 'api_call', 'call 5', user)

        start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = timezone.now() + timezone.timedelta(seconds=1)

        result = build_line_items(org, start, end)

        assert len(result) == 2
        by_rate = {item.unit_amount: item for item in result}
        default_rate = RATE.normalize()
        assert by_rate[default_rate].quantity == 2
        assert by_rate[default_rate].amount == 2 * RATE
        assert by_rate[override_rate.normalize()].quantity == 3
        assert by_rate[override_rate.normalize()].amount == 3 * override_rate
