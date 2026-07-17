"""Tests for the metered billing provider abstraction (metered_billing.py)."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch

from app.utils.metered_billing import (
    CustomerResult,
    InvoiceLineItem,
    InvoiceResult,
    MeteredBillingProvider,
    MockMeteredBillingProvider,
    get_billing_provider,
    _BillingProviderCache,
)


class TestDataclasses:
    def test_invoice_line_item(self):
        item = InvoiceLineItem(
            description='api_call usage: 10 units @ $0.05',
            amount=Decimal('0.50'),
            quantity=10,
            unit_amount=Decimal('0.05'),
        )
        assert item.description == 'api_call usage: 10 units @ $0.05'
        assert item.amount == Decimal('0.50')
        assert item.quantity == 10
        assert item.unit_amount == Decimal('0.05')

    def test_invoice_result_success(self):
        result = InvoiceResult(
            success=True,
            invoice_id='inv_123',
            invoice_url='https://example.com/inv/123',
            status='open',
        )
        assert result.success is True
        assert result.invoice_id == 'inv_123'
        assert result.error is None

    def test_invoice_result_failure(self):
        result = InvoiceResult(success=False, error='Something went wrong')
        assert result.success is False
        assert result.invoice_id is None
        assert result.error == 'Something went wrong'

    def test_customer_result(self):
        result = CustomerResult(success=True, customer_id='cus_xxx')
        assert result.success is True
        assert result.customer_id == 'cus_xxx'


class TestMockMeteredBillingProvider:
    def setup_method(self):
        self.provider = MockMeteredBillingProvider()

    def test_find_customer_by_org(self):
        result = self.provider.find_customer_by_org('org_123')
        assert result.success is True
        assert result.customer_id == 'mock_cus_org_123'

    def test_create_invoice(self):
        items = [
            InvoiceLineItem(
                description='api_call usage',
                amount=Decimal('5.00'),
                quantity=100,
                unit_amount=Decimal('0.05'),
            )
        ]
        result = self.provider.create_invoice(
            customer_id='mock_cus_123',
            line_items=items,
            period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        assert result.success is True
        assert result.invoice_id is not None
        assert result.invoice_url is not None
        assert result.status == 'open'

    def test_create_invoice_increments_counter(self):
        items = [InvoiceLineItem('test', Decimal('1'), 1, Decimal('1'))]
        r1 = self.provider.create_invoice('cus_1', items, datetime.now(timezone.utc), datetime.now(timezone.utc))
        r2 = self.provider.create_invoice('cus_1', items, datetime.now(timezone.utc), datetime.now(timezone.utc))
        assert r1.invoice_id != r2.invoice_id

    def test_get_invoice(self):
        result = self.provider.get_invoice('inv_123')
        assert result.success is True
        assert result.invoice_id == 'inv_123'

    def test_void_invoice(self):
        result = self.provider.void_invoice('inv_123')
        assert result.success is True
        assert result.status == 'void'

    def test_create_customer_raises(self):
        with pytest.raises(NotImplementedError):
            self.provider.create_customer('org_123', 'Test Org')

    def test_parse_webhook_raises(self):
        with pytest.raises(NotImplementedError):
            self.provider.parse_webhook(b'{}', 'sig')


class TestGetBillingProvider:
    def setup_method(self):
        _BillingProviderCache.instance = None

    def teardown_method(self):
        _BillingProviderCache.instance = None

    @patch('app.utils.metered_billing.settings')
    def test_returns_mock_when_configured(self, mock_settings):
        mock_settings.METERED_BILLING_PROVIDER_CLASS = 'app.utils.metered_billing.MockMeteredBillingProvider'
        mock_settings.METERED_BILLING_PROVIDER_CONFIG = {}
        provider = get_billing_provider()
        assert isinstance(provider, MockMeteredBillingProvider)

    @patch('app.utils.metered_billing.settings')
    def test_caches_instance(self, mock_settings):
        mock_settings.METERED_BILLING_PROVIDER_CLASS = 'app.utils.metered_billing.MockMeteredBillingProvider'
        mock_settings.METERED_BILLING_PROVIDER_CONFIG = {}
        p1 = get_billing_provider()
        p2 = get_billing_provider()
        assert p1 is p2

    @patch('app.utils.metered_billing.settings')
    def test_uses_configured_class(self, mock_settings):
        mock_settings.METERED_BILLING_PROVIDER_CLASS = 'app.utils.metered_billing.MockMeteredBillingProvider'
        mock_settings.METERED_BILLING_PROVIDER_CONFIG = {}
        provider = get_billing_provider()
        assert isinstance(provider, MockMeteredBillingProvider)
