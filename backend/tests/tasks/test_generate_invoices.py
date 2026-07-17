"""Tests for the generate_monthly_invoices Celery task."""

import zoneinfo
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.conf import settings
from freezegun import freeze_time

from app.celery import (
    generate_monthly_invoices,
    _previous_month_boundaries,
)
from app.utils.billing import build_line_items
from app.models import CreditTransaction, Invoice, Organisation
from app.utils.metered_billing import MockMeteredBillingProvider


BILLING_TZ = zoneinfo.ZoneInfo(settings.BILLING_TIMEZONE)

# Freeze the task at a year-end boundary so real date math runs and the
# previous calendar month is December 2025. This exercises the year-rollover
# branch in _previous_month_boundaries (now.month == 1 -> previous year).
FROZEN_NOW = '2026-01-15'


def _backdate_into_previous_month(qs):
    """Move auto_now_add created_at timestamps into the frozen previous month.

    CreditTransaction.created_at is auto_now_add, so under @freeze_time(FROZEN_NOW)
    rows would be stamped 2026-01-15 — outside the Dec 2025 invoice period that
    _previous_month_boundaries computes. QuerySet.update() bypasses auto_now_add,
    letting the rows land inside the period build_line_items filters on.
    """
    qs.update(created_at=datetime(2025, 12, 15, tzinfo=BILLING_TZ))


@pytest.fixture
def subscribed_org(db):
    return Organisation.objects.create(
        clerk_org_id='org_inv_test',
        name='Invoice Test Org',
        slug='invoice-test',
        billing_mode=Organisation.BILLING_SUBSCRIBED,
        billing_customer_id='cus_test_123',
    )


@pytest.fixture
def trial_org(db):
    return Organisation.objects.create(
        clerk_org_id='org_trial_test',
        name='Prepaid Test Org',
        slug='prepaid-test',
        billing_mode=Organisation.BILLING_PREPAID,
    )


@pytest.fixture
def mock_provider():
    return MockMeteredBillingProvider()


class TestPreviousMonthBoundaries:
    def test_returns_valid_boundaries(self):
        start, end = _previous_month_boundaries(BILLING_TZ)
        assert start.day == 1
        assert end.day == 1
        assert start < end
        assert start.tzinfo is not None

    def test_boundaries_span_one_month(self):
        start, end = _previous_month_boundaries(BILLING_TZ)
        # end should be exactly one month after start
        if start.month == 12:
            assert end.month == 1
            assert end.year == start.year + 1
        else:
            assert end.month == start.month + 1
            assert end.year == start.year

    @freeze_time(FROZEN_NOW)
    def test_year_end_rollover(self):
        """In January the previous month is December of the prior year."""
        start, end = _previous_month_boundaries(BILLING_TZ)
        assert (start.year, start.month, start.day) == (2025, 12, 1)
        assert (end.year, end.month, end.day) == (2026, 1, 1)

    @freeze_time('2026-06-17')
    def test_mid_year_boundary(self):
        """Mid-year, previous month stays within the same year."""
        start, end = _previous_month_boundaries(BILLING_TZ)
        assert (start.year, start.month, start.day) == (2026, 5, 1)
        assert (end.year, end.month, end.day) == (2026, 6, 1)


def _wide_period():
    """Return a period that covers 'now' — from 1 year ago to 1 year ahead."""
    now = datetime.now(BILLING_TZ)
    return (
        now - timedelta(days=365),
        now + timedelta(days=365),
    )


@pytest.mark.django_db
class TestBuildLineItems:
    def test_builds_line_items_from_usage(self, subscribed_org):
        period_start, period_end = _wide_period()

        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.50'),
            balance_after=Decimal('0'),
            description='API usage',
            usage_type='api_call',
        )
        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.20'),
            balance_after=Decimal('0'),
            description='Report usage',
            usage_type='report',
        )

        items = build_line_items(subscribed_org, period_start, period_end)

        assert len(items) == 2
        types = {item.usage_type for item in items}
        assert 'api_call' in types
        assert 'report' in types

    def test_nets_refunds(self, subscribed_org):
        period_start, period_end = _wide_period()

        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.50'),
            balance_after=Decimal('0'),
            description='API usage',
            usage_type='api_call',
        )
        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.REFUND,
            amount=Decimal('0.50'),
            balance_after=Decimal('0'),
            description='Refund',
            usage_type='api_call',
        )

        items = build_line_items(subscribed_org, period_start, period_end)

        assert len(items) == 0

    def test_empty_usage_returns_empty_list(self, subscribed_org):
        period_start, period_end = _wide_period()

        items = build_line_items(subscribed_org, period_start, period_end)

        assert items == []


@pytest.mark.django_db
@freeze_time(FROZEN_NOW)
class TestGenerateMonthlyInvoices:
    # Previous-month period under FROZEN_NOW (2026-01-15): Dec 2025 -> Jan 2026.
    EXPECTED_PERIOD_START = datetime(2025, 12, 1, tzinfo=BILLING_TZ)
    EXPECTED_PERIOD_END = datetime(2026, 1, 1, tzinfo=BILLING_TZ)

    @patch('app.celery.get_billing_provider')
    def test_creates_invoice_for_subscribed_org(self, mock_get_provider, subscribed_org):
        mock_provider = MockMeteredBillingProvider()
        mock_get_provider.return_value = mock_provider

        # Create usage in the previous month (Dec 2025)
        usage = CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('2.50'),
            balance_after=Decimal('0'),
            description='API usage',
            usage_type='api_call',
        )
        _backdate_into_previous_month(
            CreditTransaction.objects.filter(pk=usage.pk)
        )

        result = generate_monthly_invoices()

        assert result['created'] == 1
        assert result['failed'] == 0
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 1

        invoice = Invoice.objects.get(organisation=subscribed_org)
        assert invoice.amount == Decimal('2.50')
        assert invoice.period_start == self.EXPECTED_PERIOD_START
        assert invoice.period_end == self.EXPECTED_PERIOD_END
        assert invoice.status == 'open'

    @patch('app.celery.get_billing_provider')
    def test_skips_org_without_billing_customer_id(self, mock_get_provider, db):
        """Orgs without billing_customer_id are filtered out by the queryset."""
        mock_get_provider.return_value = MockMeteredBillingProvider()

        Organisation.objects.create(
            clerk_org_id='org_no_cus',
            name='No Customer',
            billing_mode=Organisation.BILLING_SUBSCRIBED,
            billing_customer_id=None,
        )

        result = generate_monthly_invoices()
        assert result['created'] == 0

    @patch('app.celery.get_billing_provider')
    def test_skips_trial_orgs(self, mock_get_provider, trial_org):
        mock_get_provider.return_value = MockMeteredBillingProvider()

        result = generate_monthly_invoices()
        assert result['created'] == 0

    @patch('app.celery.get_billing_provider')
    def test_idempotent_skips_existing_invoice(self, mock_get_provider, subscribed_org):
        mock_get_provider.return_value = MockMeteredBillingProvider()

        # Pre-existing invoice for the previous month
        Invoice.objects.create(
            organisation=subscribed_org,
            provider_invoice_id='inv_existing',
            status=Invoice.STATUS_OPEN,
            amount=Decimal('5.00'),
            period_start=self.EXPECTED_PERIOD_START,
            period_end=self.EXPECTED_PERIOD_END,
        )

        usage = CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('1.00'),
            balance_after=Decimal('0'),
            description='API usage',
            usage_type='api_call',
        )
        _backdate_into_previous_month(
            CreditTransaction.objects.filter(pk=usage.pk)
        )

        result = generate_monthly_invoices()
        assert result['skipped'] == 1
        assert result['created'] == 0
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 1

    @patch('app.celery.get_billing_provider')
    def test_allows_recreation_after_void(self, mock_get_provider, subscribed_org):
        mock_get_provider.return_value = MockMeteredBillingProvider()

        # Voided invoice for the previous month
        Invoice.objects.create(
            organisation=subscribed_org,
            provider_invoice_id='inv_voided',
            status=Invoice.STATUS_VOID,
            amount=Decimal('5.00'),
            period_start=self.EXPECTED_PERIOD_START,
            period_end=self.EXPECTED_PERIOD_END,
        )

        usage = CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('1.00'),
            balance_after=Decimal('0'),
            description='API usage',
            usage_type='api_call',
        )
        _backdate_into_previous_month(
            CreditTransaction.objects.filter(pk=usage.pk)
        )

        result = generate_monthly_invoices()
        assert result['created'] == 1
        # Should have 2 invoices now (one void, one new)
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 2

    @patch('app.celery.get_billing_provider')
    def test_skips_org_with_no_usage(self, mock_get_provider, subscribed_org):
        mock_get_provider.return_value = MockMeteredBillingProvider()

        result = generate_monthly_invoices()
        assert result['skipped'] == 1
        assert result['created'] == 0
