"""Tests for the Stripe metered billing provider (stripe.py)."""

import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest
import stripe

from app.models import Invoice, Organisation
from app.utils.metered_billing import InvoiceLineItem
from app.utils.stripe import StripeMeteredBillingProvider, StripeWebhookView


class TestStripeMeteredBillingProvider:
    def setup_method(self):
        self.provider = StripeMeteredBillingProvider(
            secret_key='sk_test_xxx',
            webhook_secret='whsec_test_xxx',
        )

    def test_requires_secret_key(self):
        with pytest.raises(ValueError, match='STRIPE_SECRET_KEY is required'):
            StripeMeteredBillingProvider(secret_key='')

    @patch('app.utils.stripe.stripe.Customer.search')
    def test_find_customer_by_org_success(self, mock_search):
        mock_customer = Mock()
        mock_customer.id = 'cus_abc123'
        mock_search.return_value = Mock(data=[mock_customer])

        result = self.provider.find_customer_by_org('org_test123')

        assert result.success is True
        assert result.customer_id == 'cus_abc123'
        mock_search.assert_called_once_with(
            query="metadata['organization_id']:'org_test123'",
        )

    @patch('app.utils.stripe.stripe.Customer.search')
    def test_find_customer_by_org_not_found(self, mock_search):
        mock_search.return_value = Mock(data=[])

        result = self.provider.find_customer_by_org('org_missing')

        assert result.success is False
        assert 'No Stripe customer found' in result.error

    @patch('app.utils.stripe.stripe.Customer.search')
    def test_find_customer_by_org_stripe_error(self, mock_search):
        mock_search.side_effect = stripe.StripeError('API error')

        result = self.provider.find_customer_by_org('org_test123')

        assert result.success is False
        assert 'API error' in result.error

    @patch('app.utils.stripe.stripe.Invoice.finalize_invoice')
    @patch('app.utils.stripe.stripe.InvoiceItem.create')
    @patch('app.utils.stripe.stripe.Invoice.create')
    def test_create_invoice_success(self, mock_inv_create, mock_item_create, mock_finalise):
        mock_inv_create.return_value = Mock(id='inv_123')
        mock_finalise.return_value = Mock(
            id='inv_123',
            hosted_invoice_url='https://invoice.stripe.com/inv_123',
            status='open',
        )

        items = [
            InvoiceLineItem('api_call usage: 10 units', Decimal('0.50'), 10, Decimal('0.05')),
            InvoiceLineItem('report usage: 2 units', Decimal('0.40'), 2, Decimal('0.20')),
        ]
        result = self.provider.create_invoice(
            customer_id='cus_abc',
            line_items=items,
            period_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

        assert result.success is True
        assert result.invoice_id == 'inv_123'
        assert result.invoice_url == 'https://invoice.stripe.com/inv_123'
        assert mock_item_create.call_count == 2
        # Verify amounts are in cents
        first_call = mock_item_create.call_args_list[0]
        assert first_call.kwargs['amount'] == 50  # $0.50 = 50 cents
        second_call = mock_item_create.call_args_list[1]
        assert second_call.kwargs['amount'] == 40  # $0.40 = 40 cents

    @patch('app.utils.stripe.stripe.Invoice.create')
    def test_create_invoice_stripe_error(self, mock_create):
        mock_create.side_effect = stripe.StripeError('Card declined')

        items = [InvoiceLineItem('api_call usage', Decimal('1.00'), 20, Decimal('0.05'))]
        result = self.provider.create_invoice(
            'cus_abc', items,
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 4, 1, tzinfo=timezone.utc),
        )

        assert result.success is False
        assert 'Card declined' in result.error

    @patch('app.utils.stripe.stripe.Invoice.retrieve')
    def test_get_invoice_success(self, mock_retrieve):
        mock_retrieve.return_value = Mock(
            id='inv_123', hosted_invoice_url='https://x.com', status='paid',
        )
        result = self.provider.get_invoice('inv_123')
        assert result.success is True
        assert result.status == 'paid'

    @patch('app.utils.stripe.stripe.Invoice.void_invoice')
    def test_void_invoice_success(self, mock_void):
        mock_void.return_value = Mock(id='inv_123', status='void')
        result = self.provider.void_invoice('inv_123')
        assert result.success is True
        assert result.status == 'void'

    @patch('app.utils.stripe.stripe.Webhook.construct_event')
    def test_parse_webhook_success(self, mock_construct):
        mock_event = Mock()
        mock_event.type = 'invoice.paid'
        mock_event.data.object = stripe.StripeObject.construct_from(
            {'id': 'inv_123'}, key=None,
        )
        mock_construct.return_value = mock_event

        result = self.provider.parse_webhook(b'payload', 'sig_header')

        assert result['type'] == 'invoice.paid'
        assert isinstance(result['data'], dict)
        assert result['data']['id'] == 'inv_123'
        mock_construct.assert_called_once_with(b'payload', 'sig_header', 'whsec_test_xxx')

    @patch('app.utils.stripe.stripe.Webhook.construct_event')
    def test_parse_webhook_invalid_signature(self, mock_construct):
        mock_construct.side_effect = stripe.SignatureVerificationError('bad sig', 'sig')

        with pytest.raises(stripe.SignatureVerificationError):
            self.provider.parse_webhook(b'payload', 'bad_sig')

    # --- create_checkout_session (was untested) ---

    @patch('app.utils.stripe.stripe.checkout.Session.create')
    def test_create_checkout_session_with_existing_customer(self, mock_create):
        mock_create.return_value = Mock(id='cs_123', url='https://checkout.stripe.com/cs_123')

        result = self.provider.create_checkout_session(
            customer_id='cus_x', amount=Decimal('25'), org_id='org_1',
            success_url='https://s', cancel_url='https://c',
        )

        assert result.success is True
        assert result.session_id == 'cs_123'
        assert result.checkout_url == 'https://checkout.stripe.com/cs_123'
        params = mock_create.call_args.kwargs
        assert params['customer'] == 'cus_x'
        assert 'customer_creation' not in params
        assert params['line_items'][0]['price_data']['unit_amount'] == 2500
        assert params['metadata'] == {'purchase_type': 'credit_purchase', 'org_id': 'org_1'}

    @patch('app.utils.stripe.stripe.checkout.Session.create')
    def test_create_checkout_session_without_customer_sets_creation_always(self, mock_create):
        mock_create.return_value = Mock(id='cs_456', url='https://checkout.stripe.com/cs_456')

        result = self.provider.create_checkout_session(
            customer_id=None, amount=Decimal('10'), org_id='org_2',
            success_url='https://s', cancel_url='https://c',
        )

        assert result.success is True
        params = mock_create.call_args.kwargs
        assert params.get('customer_creation') == 'always'
        assert 'customer' not in params

    @patch('app.utils.stripe.stripe.checkout.Session.create')
    def test_create_checkout_session_stripe_error(self, mock_create):
        mock_create.side_effect = stripe.StripeError('boom')

        result = self.provider.create_checkout_session(
            customer_id=None, amount=Decimal('10'), org_id='org_3',
            success_url='https://s', cancel_url='https://c',
        )

        assert result.success is False
        assert 'boom' in result.error

    # --- get_invoice_pdf (was untested) ---

    @patch('app.utils.stripe.http_requests.get')
    @patch('app.utils.stripe.stripe.Invoice.retrieve')
    def test_get_invoice_pdf_downloads_bytes(self, mock_retrieve, mock_get):
        mock_retrieve.return_value = Mock(invoice_pdf='https://files.stripe.com/in_1.pdf')
        mock_get.return_value = Mock(content=b'%PDF-1.4 fake')

        result = self.provider.get_invoice_pdf('in_1')

        assert result.success is True
        assert result.content == b'%PDF-1.4 fake'
        assert result.filename == 'invoice-in_1.pdf'

    @patch('app.utils.stripe.stripe.Invoice.retrieve')
    def test_get_invoice_pdf_no_pdf_url_returns_failure(self, mock_retrieve):
        mock_retrieve.return_value = Mock(invoice_pdf=None)

        result = self.provider.get_invoice_pdf('in_2')

        assert result.success is False
        assert 'No PDF available' in result.error

    @patch('app.utils.stripe.stripe.Invoice.retrieve')
    def test_get_invoice_pdf_stripe_error(self, mock_retrieve):
        mock_retrieve.side_effect = stripe.StripeError('nope')

        result = self.provider.get_invoice_pdf('in_3')

        assert result.success is False
        assert 'nope' in result.error


# ---------------------------------------------------------------------------
# Invoice webhook handler unit tests — call the StripeWebhookView handlers
# directly (no signature / HTTP layer) to pin down the past_due_source
# precedence rules. The handlers are plain instance methods that only touch the
# DB, so a bare StripeWebhookView() instance is sufficient.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestInvoiceHandlerPastDueSource:
    PERIOD_START = datetime(2026, 3, 1, tzinfo=timezone.utc)
    PERIOD_END = datetime(2026, 4, 1, tzinfo=timezone.utc)

    def setup_method(self):
        self.view = StripeWebhookView()

    def _org(self, **kw):
        defaults = dict(
            clerk_org_id='org_ih',
            name='Invoice Handler Org',
            billing_mode=Organisation.BILLING_SUBSCRIBED,
            billing_customer_id='cus_ih',
        )
        defaults.update(kw)
        return Organisation.objects.create(**defaults)

    def _invoice(self, org, provider_invoice_id='inv_ih', status=Invoice.STATUS_OPEN,
                 period_start=None, period_end=None):
        return Invoice.objects.create(
            organisation=org,
            provider_invoice_id=provider_invoice_id,
            status=status,
            amount=Decimal('5.00'),
            period_start=period_start or self.PERIOD_START,
            period_end=period_end or self.PERIOD_END,
        )

    # (a) Stripe-sourced past_due cleared by invoice.paid
    def test_invoice_paid_clears_stripe_set_past_due(self):
        org = self._org(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE,
        )
        invoice = self._invoice(org, status=Invoice.STATUS_UNCOLLECTABLE)

        self.view._handle_invoice_paid('inv_ih')

        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED
        assert org.past_due_source is None

    # (b) Clerk-sourced past_due is NOT stolen by invoice.paid
    def test_invoice_paid_keeps_clerk_set_past_due(self):
        org = self._org(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_CLERK,
        )
        invoice = self._invoice(org, status=Invoice.STATUS_UNCOLLECTABLE)

        self.view._handle_invoice_paid('inv_ih')

        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID  # invoice itself is settled
        assert org.billing_mode == Organisation.BILLING_PAST_DUE  # still blocked
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_CLERK

    # (c) Another uncollectable invoice still present -> stays past_due
    def test_invoice_paid_keeps_past_due_when_other_invoice_uncollectable(self):
        org = self._org(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE,
        )
        invoice = self._invoice(org, status=Invoice.STATUS_UNCOLLECTABLE)
        # Distinct period_start to satisfy the unique active-invoice constraint
        self._invoice(
            org,
            provider_invoice_id='inv_ih_other',
            status=Invoice.STATUS_UNCOLLECTABLE,
            period_start=datetime(2026, 2, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 3, 1, tzinfo=timezone.utc),
        )

        self.view._handle_invoice_paid('inv_ih')

        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_PAID  # this one is settled
        # Other uncollectable invoice keeps the org blocked, source preserved
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE

    # (d) invoice.payment_failed on a healthy org -> past_due, source=STRIPE_INVOICE
    def test_invoice_payment_failed_sets_past_due_stripe_source(self):
        org = self._org(billing_mode=Organisation.BILLING_SUBSCRIBED)
        invoice = self._invoice(org, status=Invoice.STATUS_OPEN)

        self.view._handle_invoice_payment_failed('inv_ih')

        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_UNCOLLECTABLE
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE

    # (e) Second failure while already past_due from Clerk -> source unchanged
    def test_invoice_payment_failed_does_not_relabel_clerk_source(self):
        org = self._org(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_CLERK,
        )
        invoice = self._invoice(org, status=Invoice.STATUS_OPEN)

        self.view._handle_invoice_payment_failed('inv_ih')

        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_UNCOLLECTABLE
        assert org.billing_mode == Organisation.BILLING_PAST_DUE
        # Clerk source is stickier: must NOT be relabelled to stripe_invoice
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_CLERK

    # (f) Unknown invoice id -> warns, no crash, no org/invoice mutated
    def test_invoice_paid_unknown_invoice_warns_no_crash(self, caplog, propagate_app_logs):
        org = self._org(
            billing_mode=Organisation.BILLING_PAST_DUE,
            past_due_source=Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE,
        )
        invoice = self._invoice(org, status=Invoice.STATUS_UNCOLLECTABLE)

        with caplog.at_level('WARNING', logger='app.utils.stripe'):
            self.view._handle_invoice_paid('inv_does_not_exist')

        assert 'no matching invoice for inv_does_not_exist' in caplog.text
        invoice.refresh_from_db()
        org.refresh_from_db()
        assert invoice.status == Invoice.STATUS_UNCOLLECTABLE  # untouched
        assert org.billing_mode == Organisation.BILLING_PAST_DUE  # untouched
        assert org.past_due_source == Organisation.PAST_DUE_SOURCE_STRIPE_INVOICE

    def test_invoice_payment_failed_unknown_invoice_warns_no_crash(self, caplog, propagate_app_logs):
        org = self._org(billing_mode=Organisation.BILLING_SUBSCRIBED)
        self._invoice(org, status=Invoice.STATUS_OPEN)

        with caplog.at_level('WARNING', logger='app.utils.stripe'):
            self.view._handle_invoice_payment_failed('inv_does_not_exist')

        assert 'no matching invoice for inv_does_not_exist' in caplog.text
        org.refresh_from_db()
        assert org.billing_mode == Organisation.BILLING_SUBSCRIBED  # untouched
        assert org.past_due_source is None
