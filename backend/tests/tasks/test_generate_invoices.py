"""Tests for the generate_monthly_invoices Celery task."""

import zoneinfo
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.celery import (
    generate_monthly_invoices,
    _previous_month_boundaries,
)
from app.utils.billing import build_line_items
from app.models import CreditTransaction, Invoice, Organisation
from app.utils.metered_billing import MockMeteredBillingProvider


ADELAIDE_TZ = zoneinfo.ZoneInfo('Australia/Adelaide')


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
        start, end = _previous_month_boundaries(ADELAIDE_TZ)
        assert start.day == 1
        assert end.day == 1
        assert start < end
        assert start.tzinfo is not None

    def test_boundaries_span_one_month(self):
        start, end = _previous_month_boundaries(ADELAIDE_TZ)
        # end should be exactly one month after start
        if start.month == 12:
            assert end.month == 1
            assert end.year == start.year + 1
        else:
            assert end.month == start.month + 1
            assert end.year == start.year


def _wide_period():
    """Return a period that covers 'now' — from 1 year ago to 1 year ahead."""
    now = datetime.now(ADELAIDE_TZ)
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
            description='SMS to +614000',
            format='sms',
        )
        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.20'),
            balance_after=Decimal('0'),
            description='MMS to +614000',
            format='mms',
        )

        items = build_line_items(subscribed_org, period_start, period_end)

        assert len(items) == 2
        formats = {item.description.split()[0] for item in items}
        assert 'SMS' in formats
        assert 'MMS' in formats

    def test_nets_refunds(self, subscribed_org):
        period_start, period_end = _wide_period()

        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('0.50'),
            balance_after=Decimal('0'),
            description='SMS',
            format='sms',
        )
        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.REFUND,
            amount=Decimal('0.50'),
            balance_after=Decimal('0'),
            description='Refund',
            format='sms',
        )

        items = build_line_items(subscribed_org, period_start, period_end)

        assert len(items) == 0

    def test_empty_usage_returns_empty_list(self, subscribed_org):
        period_start, period_end = _wide_period()

        items = build_line_items(subscribed_org, period_start, period_end)

        assert items == []


@pytest.mark.django_db
class TestGenerateMonthlyInvoices:
    @patch('app.celery.get_billing_provider')
    @patch('app.celery._previous_month_boundaries')
    def test_creates_invoice_for_subscribed_org(self, mock_boundaries, mock_get_provider, subscribed_org):
        period_start, period_end = _wide_period()
        mock_boundaries.return_value = (period_start, period_end)

        mock_provider = MockMeteredBillingProvider()
        mock_get_provider.return_value = mock_provider

        # Create usage in the period
        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('2.50'),
            balance_after=Decimal('0'),
            description='SMS usage',
            format='sms',
        )

        result = generate_monthly_invoices()

        assert result['created'] == 1
        assert result['failed'] == 0
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 1

        invoice = Invoice.objects.get(organisation=subscribed_org)
        assert invoice.amount == Decimal('2.50')
        assert invoice.period_start == period_start
        assert invoice.period_end == period_end
        assert invoice.status == 'open'

    @patch('app.celery.get_billing_provider')
    @patch('app.celery._previous_month_boundaries')
    def test_skips_org_without_billing_customer_id(self, mock_boundaries, mock_get_provider, db):
        """Orgs without billing_customer_id are filtered out by the queryset."""
        mock_boundaries.return_value = _wide_period()
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
    @patch('app.celery._previous_month_boundaries')
    def test_skips_trial_orgs(self, mock_boundaries, mock_get_provider, trial_org):
        mock_boundaries.return_value = _wide_period()
        mock_get_provider.return_value = MockMeteredBillingProvider()

        result = generate_monthly_invoices()
        assert result['created'] == 0

    @patch('app.celery.get_billing_provider')
    @patch('app.celery._previous_month_boundaries')
    def test_idempotent_skips_existing_invoice(self, mock_boundaries, mock_get_provider, subscribed_org):
        period_start, period_end = _wide_period()
        mock_boundaries.return_value = (period_start, period_end)
        mock_get_provider.return_value = MockMeteredBillingProvider()

        # Pre-existing invoice
        Invoice.objects.create(
            organisation=subscribed_org,
            provider_invoice_id='inv_existing',
            status=Invoice.STATUS_OPEN,
            amount=Decimal('5.00'),
            period_start=period_start,
            period_end=period_end,
        )

        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('1.00'),
            balance_after=Decimal('0'),
            description='SMS',
            format='sms',
        )

        result = generate_monthly_invoices()
        assert result['skipped'] == 1
        assert result['created'] == 0
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 1

    @patch('app.celery.get_billing_provider')
    @patch('app.celery._previous_month_boundaries')
    def test_allows_recreation_after_void(self, mock_boundaries, mock_get_provider, subscribed_org):
        period_start, period_end = _wide_period()
        mock_boundaries.return_value = (period_start, period_end)
        mock_get_provider.return_value = MockMeteredBillingProvider()

        # Voided invoice
        Invoice.objects.create(
            organisation=subscribed_org,
            provider_invoice_id='inv_voided',
            status=Invoice.STATUS_VOID,
            amount=Decimal('5.00'),
            period_start=period_start,
            period_end=period_end,
        )

        CreditTransaction.objects.create(
            organisation=subscribed_org,
            transaction_type=CreditTransaction.USAGE,
            amount=Decimal('1.00'),
            balance_after=Decimal('0'),
            description='SMS',
            format='sms',
        )

        result = generate_monthly_invoices()
        assert result['created'] == 1
        # Should have 2 invoices now (one void, one new)
        assert Invoice.objects.filter(organisation=subscribed_org).count() == 2

    @patch('app.celery.get_billing_provider')
    @patch('app.celery._previous_month_boundaries')
    def test_skips_org_with_no_usage(self, mock_boundaries, mock_get_provider, subscribed_org):
        mock_boundaries.return_value = _wide_period()
        mock_get_provider.return_value = MockMeteredBillingProvider()

        result = generate_monthly_invoices()
        assert result['skipped'] == 1
        assert result['created'] == 0
